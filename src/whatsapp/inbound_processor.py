import asyncio
import logging
import uuid
from src.core.security_logger import security_audit
from src.whatsapp.config import AppConfig, load_tenant_config
from src.core.crew_runner import genera_risposta_async
from src.core.notifications.email_service import send_escalation_notification
from src.models.schemas import MessaggioInput, CanaleMessaggio, ProfiloAttivita

logger = logging.getLogger(__name__)


def _profile_from_dict(raw: dict | None, fallback_name: str = "Attivita") -> ProfiloAttivita:
    """Adatta il business_profile grezzo (JSONB, forma non ancora
    standardizzata: manca un onboarding UI che ne fissi lo schema) al
    modello ProfiloAttivita richiesto dall'agente AI. Best-effort con
    fallback sicuri: da rivedere quando l'onboarding definira' la forma
    reale dei dati salvati per organizzazione."""
    raw = raw or {}
    return ProfiloAttivita(
        nome=raw.get("nome") or raw.get("name") or fallback_name,
        tipo_attivita=raw.get("tipo_attivita") or raw.get("type") or "attivita commerciale",
        tono=raw.get("tono") or raw.get("tone") or "cordiale e professionale",
        orari=raw.get("orari") or raw.get("hours") or "",
        servizi_principali=raw.get("servizi_principali") or raw.get("services") or [],
        note_speciali=raw.get("note_speciali") or raw.get("notes") or [],
    )


class InboundProcessor:
    def __init__(self, app_config: AppConfig, repo, service):
        self.app_config = app_config
        self.repo = repo
        self.service = service

    async def process_next_batch(self):
        await self.repo.reap_stale_claims()
        messages = await self.repo.claim_inbound_messages(limit=10)
        for msg in messages:
            try:
                await self._process_one(msg)
            except Exception as e:
                logger.error("Error processing message %s: %s", msg["id"], e)

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
            await self.repo.update_message_status(msg["id"], "handled")
            return

        tenant_config = await load_tenant_config(org_id, self.app_config, self.repo)
        business_profile_raw = getattr(tenant_config, "business_profile", None) or {}

        fast_reply = await self.service.fast_path_match(text, business_profile_raw)
        if fast_reply:
            await self._send_ai_reply(org_id, msg, content, tenant_config, fast_reply)
            await self.repo.update_message_status(msg["id"], "handled")
            return

        profilo = _profile_from_dict(business_profile_raw)
        messaggio = MessaggioInput(
            testo=text,
            canale=CanaleMessaggio.WHATSAPP,
            id_conversazione=str(msg.get("conversation_id", "")),
        )
        risposta = await genera_risposta_async(messaggio, profilo)

        if risposta.richiede_umano:
            conv = await self.repo.escalate_to_human(str(msg["conversation_id"]))
            if conv:
                contact_name = content.get("from", "cliente")
                try:
                    await send_escalation_notification(
                        org_id=str(org_id),
                        conversation_id=str(msg["conversation_id"]),
                        contact_name=contact_name,
                        pool=self.repo.pool,
                    )
                except Exception as e:
                    # La notifica non deve mai bloccare l'escalation: il ticket
                    # e' comunque in PENDING_STAFF e visibile in inbox anche
                    # se l'email non parte (es. SMTP non configurato).
                    logger.error("Escalation email failed for conversation %s: %s", msg["conversation_id"], e)
            await self.repo.update_message_status(msg["id"], "escalated")
            return

        await self._send_ai_reply(org_id, msg, content, tenant_config, risposta.risposta)
        await self.repo.update_message_status(msg["id"], "handled")

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
