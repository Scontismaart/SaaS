import asyncio
import logging
import uuid
from pydantic import ValidationError
from src.core.security_logger import security_audit
from src.whatsapp.config import AppConfig, load_tenant_config
from src.core.crew_runner import genera_risposta_async
from src.core.bookings import SlotPienoError
from src.core.notifications.email_service import enqueue_escalation
from src.core.billing.suspension import is_org_suspended
from src.models.schemas import (
    MessaggioInput, CanaleMessaggio, ProfiloAttivita, WhatsAppBusinessProfile,
)

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 30

# Messaggio neutro per il cliente finale quando l'org e' sospesa: nessuna
# menzione di abbonamenti/fatturazione (esporrebbe lo stato di billing del
# locale a un cliente casuale). La notifica vera va al gestore via email.
ORG_SUSPENDED_REPLY = "Grazie per averci scritto, ti risponderemo al piu' presto."


def _profile_from_dict(raw: dict | None, fallback_name: str = "Attivita") -> ProfiloAttivita:
    raw = raw or {}
    try:
        validated = WhatsAppBusinessProfile.model_validate(raw)
    except ValidationError as e:
        logger.error("business_profile validation failed", extra={
            "errors": e.errors(),
            "raw": raw,
        })
        validated = WhatsAppBusinessProfile()
    return ProfiloAttivita(
        nome=validated.nome or fallback_name,
        tipo_attivita=validated.tipo_attivita or "attivita commerciale",
        tono=validated.tono or "cordiale e professionale",
        orari=validated.orari or "",
        servizi_principali=validated.servizi_principali or [],
        note_speciali=validated.note_speciali or [],
    )


class InboundProcessor:
    def __init__(self, app_config: AppConfig, repo, service, booking_service=None):
        self.app_config = app_config
        self.repo = repo
        self.service = service
        self.booking_service = booking_service

    async def process_next_batch(self):
        await self.repo.reap_stale_claims()
        messages = await self.repo.claim_inbound_messages(limit=10)
        for msg in messages:
            try:
                await self._process_one(msg)
            except Exception as e:
                logger.error("Error processing message %s: %s", msg["id"], e)

    async def _heartbeat_loop(self, msg_id):
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                await self.repo.update_heartbeat(msg_id)
        except asyncio.CancelledError:
            pass

    async def _process_one(self, msg: dict):
        org_id = msg["organization_id"]
        text = msg.get("content_text", "")
        content = msg.get("content", {})

        opt_out = await self.service.check_opt_out(text)
        if opt_out["is_opt_out"]:
            from_number = content.get("from", "")
            contact = await self.repo.get_or_create_contact(org_id, from_number)
            await self.repo.record_consent_event(
                contact_id=contact["id"],
                event_type="opt_out",
                method="keyword_match",
                triggering_message_id=msg["id"],
                matched_text=text,
            )
            security_audit("consent_opt_out", contact_id=str(contact["id"]), organization_id=str(org_id))
            await self.repo.try_mark_replied(msg["id"])
            return

        if self.booking_service:
            booking_reply = await self.booking_service.handle_reminder_reply(
                org_id, content.get("from", ""), text
            )
            if booking_reply:
                await self.repo.try_mark_replied(msg["id"])
                return

        state = await self.repo.get_org_subscription_state(org_id)
        if state and is_org_suspended(state.get("subscription_status"), state.get("trial_end")):
            logger.warning(
                "org_id=%s message_id=%s event=org_suspended — risposta AI inibita",
                org_id, msg["id"],
            )
            tenant_config = await load_tenant_config(org_id, self.app_config, self.repo)
            if await self.repo.try_mark_replied(msg["id"]):
                await self._send_ai_reply(org_id, msg, content, tenant_config, ORG_SUSPENDED_REPLY)
            return

        tenant_config = await load_tenant_config(org_id, self.app_config, self.repo)
        business_profile_raw = getattr(tenant_config, "business_profile", None) or {}

        fast_reply = await self.service.fast_path_match(text, business_profile_raw)
        if fast_reply:
            if await self.repo.try_mark_replied(msg["id"]):
                await self._send_ai_reply(org_id, msg, content, tenant_config, fast_reply)
            return

        profilo = _profile_from_dict(business_profile_raw)
        messaggio = MessaggioInput(
            testo=text,
            canale=CanaleMessaggio.WHATSAPP,
            id_conversazione=str(msg.get("conversation_id", "")),
        )

        heartbeat_task = asyncio.ensure_future(self._heartbeat_loop(msg["id"]))
        try:
            risposta = await genera_risposta_async(messaggio, profilo)
        finally:
            heartbeat_task.cancel()

        pren = risposta.prenotazione
        if pren and pren.data and pren.ora and pren.coperti:
            if self.booking_service:
                try:
                    created = await self.booking_service.create_booking(
                        org_id=org_id,
                        nome_cliente=pren.nome_cliente or "Cliente WhatsApp",
                        telefono=pren.telefono or content.get("from", ""),
                        data=pren.data,
                        ora=pren.ora,
                        coperti=pren.coperti,
                        note=pren.note,
                        origine="WhatsApp",
                        richiede_intervento=risposta.richiede_umano,
                        id_conversazione=str(msg.get("conversation_id", "")),
                    )
                    logger.info("Booking %s created from AI response for org %s", created["id"], org_id)
                except SlotPienoError as e:
                    if e.alternative:
                        alt_text = " o ".join(e.alternative)
                        risposta.risposta += (
                            f" Mi dispiace, alle {pren.ora} siamo al completo per {pren.coperti} persone."
                            f" Ti andrebbe bene alle {alt_text}?"
                        )
                    else:
                        risposta.risposta += (
                            f" Mi dispiace, alle {pren.ora} siamo al completo per {pren.coperti} persone."
                            f" Posso chiedere allo staff una fascia alternativa."
                        )
                    risposta.motivo = "slot_prenotazione_pieno"
                except Exception as e:
                    logger.error("Booking creation from AI failed for org %s: %s", org_id, e)

        if risposta.richiede_umano:
            conv = await self.repo.escalate_to_human(str(msg["conversation_id"]))
            if conv:
                enqueue_escalation(
                    org_id=str(org_id),
                    conversation_id=str(msg["conversation_id"]),
                    contact_name=content.get("from", "cliente"),
                    pool=self.repo.pool,
                )
            await self.repo.try_mark_replied(msg["id"])
            return

        if await self.repo.try_mark_replied(msg["id"]):
            await self._send_ai_reply(org_id, msg, content, tenant_config, risposta.risposta)

    async def _send_ai_reply(self, org_id, msg, content, tenant_config, testo_risposta):
        to_number = content.get("from", "")
        if not to_number or not tenant_config:
            logger.warning("Impossibile inviare risposta AI per messaggio %s: numero o tenant_config mancante", msg["id"])
            return
        payload = {"to": to_number, "type": "text", "text": {"body": testo_risposta}}
        try:
            await self.service.send_whatsapp_message(
                org_id=org_id,
                to_number=to_number,
                payload=payload,
                category="service",
                meta_client=None,
                tenant_config=tenant_config,
            )
        except self.service.MessageUsageExceeded:
            logger.warning("Quota messaggi esaurita per org %s: risposta AI non inviata", org_id)
        except Exception as e:
            logger.error("Invio risposta AI fallito per messaggio %s: %s", msg["id"], e)
