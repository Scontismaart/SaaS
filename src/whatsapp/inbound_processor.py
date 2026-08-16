import asyncio
import logging
import uuid

from pydantic import ValidationError

from src.core.billing.suspension import is_org_suspended
from src.core.bookings import SlotPienoError
from src.core.crew_runner import genera_risposta_async
from src.core.documenti.rag_context import recupera_contesto_documenti
from src.core.guardrails.intent_classifier import classifica_intent
from src.core.guardrails.validator import applica_guardrail, valida_risposta
from src.core.llm_config import LLMRouteRequest, budget_ratio_from_billing, route_llm
from src.core.notifications.email_service import enqueue_escalation
from src.core.security_logger import security_audit
from src.models.schemas import (
    CanaleMessaggio,
    MessaggioInput,
    ProfiloAttivita,
    WhatsAppBusinessProfile,
)
from src.whatsapp.config import AppConfig, load_tenant_config

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 30

# Messaggio neutro per il cliente finale quando l'org e' sospesa: nessuna
# menzione di abbonamenti/fatturazione (esporrebbe lo stato di billing del
# locale a un cliente casuale). La notifica vera va al gestore via email.
ORG_SUSPENDED_REPLY = "Grazie per averci scritto, ti risponderemo al piu' presto."

DISCLOSURE_TEXT = (
    "Ciao! Sono l'assistente automatico di {nome}, un sistema di intelligenza "
    "artificiale. Scrivi OPERATORE se vuoi parlare con una persona."
)

HUMAN_WAIT_REPLY = "Ti passo una persona dello staff, un attimo!"


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


async def decorate_with_disclosure(org_id: str, from_number: str, testo: str, repo,
                                   nome_attivita: str = "Attivita") -> str:
    """Prepende la disclosure AI al primo messaggio automatico per quel contatto."""
    contact = await repo.get_or_create_contact(org_id, from_number)
    sent = await repo.mark_ai_disclosure_sent(contact["id"])
    if not sent:
        return testo
    return DISCLOSURE_TEXT.format(nome=nome_attivita) + "\n\n" + testo


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
        # Canale di origine della conversazione (join in claim_inbound_messages):
        # opt-out, OPERATORE, AI, escalation sono channel-agnostic, cambia
        # solo l'invio della risposta (dispatch in _send_ai_reply).
        canale = msg.get("canale") or "whatsapp"

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
            await self.repo.try_mark_replied(msg["id"], handling_type="opt_out")
            return

        wants_human = await self.service.check_human_request(text)
        if wants_human:
            from_number = content.get("from", "")
            tenant_config = await load_tenant_config(org_id, self.app_config, self.repo)
            if not await self.repo.try_mark_replied(msg["id"], handling_type="escalated"):
                return
            await self._send_ai_reply(org_id, msg, content, tenant_config, HUMAN_WAIT_REPLY, handling_type="automation")
            conv = await self.repo.escalate_to_human(str(msg["conversation_id"]))
            if conv:
                enqueue_escalation(
                    org_id=str(org_id),
                    conversation_id=str(msg["conversation_id"]),
                    contact_name=from_number or "cliente",
                    pool=self.repo.pool,
                )
            return

        if self.booking_service:
            booking_reply = await self.booking_service.handle_reminder_reply(
                org_id, content.get("from", ""), text
            )
            if booking_reply:
                await self.repo.try_mark_replied(msg["id"], handling_type="automation")
                return

        state = await self.repo.get_org_subscription_state(org_id)
        if state and is_org_suspended(state.get("subscription_status"), state.get("trial_end")):
            logger.warning(
                "org_id=%s message_id=%s event=org_suspended — risposta AI inibita",
                org_id, msg["id"],
            )
            tenant_config = await load_tenant_config(org_id, self.app_config, self.repo)
            if await self.repo.try_mark_replied(msg["id"], handling_type="suspended"):
                await self._send_ai_reply(org_id, msg, content, tenant_config, ORG_SUSPENDED_REPLY, handling_type="automation")
            return

        tenant_config = await load_tenant_config(org_id, self.app_config, self.repo)
        if tenant_config is not None:
            business_profile_raw = getattr(tenant_config, "business_profile", None) or {}
        else:
            # Org senza account WhatsApp (es. solo Instagram): il profilo
            # business e' a livello organizzazione, non di canale.
            business_profile_raw = await self.repo.get_org_business_profile(org_id) or {}

        fast_reply = await self.service.fast_path_match(text, business_profile_raw)
        if fast_reply:
            from_number = content.get("from", "")
            nome = (business_profile_raw or {}).get("nome") or "Attivita"
            replied = await self.repo.try_mark_replied(msg["id"], handling_type="ai_handled")
            if not replied:
                return
            decorated = await decorate_with_disclosure(org_id, from_number, fast_reply, self.repo, nome_attivita=nome)
            await self._send_ai_reply(org_id, msg, content, tenant_config, decorated)
            return

        profilo = _profile_from_dict(business_profile_raw)
        messaggio = MessaggioInput(
            testo=text,
            canale=CanaleMessaggio(canale),
            id_conversazione=str(msg.get("conversation_id", "")),
        )

        # Classificatore di intent (task 12): gira prima del responder e
        # informa il routing del modello. Mai bloccante, mai solleva.
        intent_result = await classifica_intent(text)
        if intent_result.source == "llm":
            try:
                await self.repo.record_usage(
                    org_id,
                    "intent_classification",
                    metadata={
                        "intent": intent_result.intent,
                        "confidence": intent_result.confidence,
                        "message_id": str(msg["id"]),
                    },
                )
            except Exception as e:
                logger.warning("Intent usage logging failed for org %s msg %s: %s", org_id, msg["id"], e)

        heartbeat_task = asyncio.ensure_future(self._heartbeat_loop(msg["id"]))
        try:
            contesto = await recupera_contesto_documenti(str(org_id), text, self.repo)
            risposta = await genera_risposta_async(
                messaggio, profilo, billing=state, contesto_documenti=contesto.testo,
                intent=intent_result.intent,
            )
        finally:
            heartbeat_task.cancel()

        # Guardrail post-LLM (task 12): la risposta viene validata contro il
        # contesto RAG prima di qualsiasi uso. "block" sostituisce il testo
        # col fallback staff e forza richiede_umano -> escalation HITL.
        esito = valida_risposta(risposta, contesto.chunks, profilo)
        if esito.azione != "none":
            risposta = applica_guardrail(risposta, esito)
            if esito.azione == "block":
                logger.warning(
                    "guardrail block org_id=%s message_id=%s motivo=%s",
                    org_id, msg["id"], esito.motivo,
                )
                try:
                    await self.repo.record_usage(
                        org_id,
                        "guardrail_block",
                        metadata={
                            "motivo": esito.motivo,
                            "violazioni": list(esito.violazioni),
                            "conversation_id": str(msg.get("conversation_id", "")),
                            "message_id": str(msg["id"]),
                        },
                    )
                except Exception as e:
                    logger.warning("Guardrail usage logging failed for org %s msg %s: %s", org_id, msg["id"], e)

        try:
            route = route_llm(
                LLMRouteRequest(
                    task_type="customer_message",
                    user_text=text,
                    remaining_budget_ratio=budget_ratio_from_billing(state),
                    intent=intent_result.intent,
                )
            )
            await self.repo.record_usage(
                org_id,
                "ai_response",
                quantity=1,
                metadata={
                    "channel": canale,
                    "model": route.model,
                    "tier": route.tier,
                    "reason": route.reason,
                    "intent": intent_result.intent,
                    "intent_source": intent_result.source,
                    "conversation_id": str(msg.get("conversation_id", "")),
                    "message_id": str(msg["id"]),
                },
            )
        except Exception as e:
            logger.warning("AI usage logging failed for org %s msg %s: %s", org_id, msg["id"], e)

        pren = risposta.prenotazione
        if pren and pren.data and pren.ora and pren.coperti:
            if self.booking_service:
                try:
                    created = await self.booking_service.create_booking(
                        org_id=org_id,
                        nome_cliente=pren.nome_cliente or (
                            "Cliente Instagram" if canale == "instagram" else "Cliente WhatsApp"
                        ),
                        telefono=pren.telefono or ("" if canale == "instagram" else content.get("from", "")),
                        data=pren.data,
                        ora=pren.ora,
                        coperti=pren.coperti,
                        note=pren.note,
                        origine="Instagram" if canale == "instagram" else "WhatsApp",
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
            # Il messaggio e' gestito: se il responder ha lasciato un testo
            # di attesa lo inviamo (il cliente non resta in silenzio mentre
            # lo staff prende in carico), poi escalation + email al titolare.
            replied = await self.repo.try_mark_replied(msg["id"], handling_type="escalated")
            if not replied:
                return
            if risposta.risposta:
                from_number = content.get("from", "")
                decorated = await decorate_with_disclosure(
                    org_id, from_number, risposta.risposta, self.repo, profilo.nome
                )
                await self._send_ai_reply(org_id, msg, content, tenant_config, decorated)
            conv = await self.repo.escalate_to_human(str(msg["conversation_id"]))
            if conv:
                enqueue_escalation(
                    org_id=str(org_id),
                    conversation_id=str(msg["conversation_id"]),
                    contact_name=content.get("from", "cliente"),
                    pool=self.repo.pool,
                )
            return

        replied = await self.repo.try_mark_replied(msg["id"], handling_type="ai_handled")
        if not replied:
            return
        from_number = content.get("from", "")
        decorated = await decorate_with_disclosure(org_id, from_number, risposta.risposta, self.repo, profilo.nome)
        await self._send_ai_reply(org_id, msg, content, tenant_config, decorated)

    async def _send_ai_reply(self, org_id, msg, content, tenant_config, testo_risposta,
                             handling_type="ai_handled"):
        canale = msg.get("canale") or "whatsapp"
        if canale == "instagram":
            await self._send_instagram_reply(org_id, msg, content, testo_risposta, handling_type=handling_type)
            return
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
                handling_type=handling_type,
            )
        except self.service.MessageUsageExceeded:
            logger.warning("Quota messaggi esaurita per org %s: risposta AI non inviata", org_id)
        except Exception as e:
            logger.error("Invio risposta AI fallito per messaggio %s: %s", msg["id"], e)

    async def _send_instagram_reply(self, org_id, msg, content, testo_risposta,
                                    handling_type="ai_handled"):
        """Invio della risposta AI via Instagram DM. Se l'org non ha un
        account Instagram collegato (non dovrebbe accadere: il webhook
        arriva solo per account registrati) logga e non crasha."""
        to_ig_id = content.get("from", "")
        if not to_ig_id:
            logger.warning("Impossibile inviare risposta AI Instagram per messaggio %s: mittente mancante", msg["id"])
            return
        from src.instagram.config import load_instagram_config
        from src.instagram.repository import InstagramRepository
        from src.instagram.service import InstagramService

        try:
            ig_config = await load_instagram_config(
                org_id, self.app_config.encryption_key, InstagramRepository(self.repo.pool)
            )
            if not ig_config:
                logger.warning("Org %s: account Instagram non configurato, risposta AI non inviata", org_id)
                return
            await InstagramService(self.repo).send_instagram_message(
                org_id=org_id,
                to_ig_id=to_ig_id,
                text=testo_risposta,
                ig_config=ig_config,
                handling_type=handling_type,
            )
        except Exception as e:
            logger.error("Invio risposta AI Instagram fallito per messaggio %s: %s", msg["id"], e)
