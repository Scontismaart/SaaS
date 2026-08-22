import uuid
import re
import json
from datetime import datetime, timezone
from typing import Optional
from src.whatsapp.config import AppConfig, TenantConfig
from src.whatsapp.models import SendTextRequest, OutboundTextPayload


OPT_OUT_KEYWORDS = {
    "it": ["stop", "annulla", "basta", "non scrivermi più", "cancellami", "disiscrivi"],
    "en": ["stop", "unsubscribe", "cancel", "opt out", "remove me"],
}

HUMAN_REQUEST_KEYWORDS = {
    "it": ["operatore", "umano", "parlare con una persona", "persona reale", "staff"],
    "en": ["operator", "human", "talk to a person", "real person"],
}

_FAST_PATH_GREETINGS = ["ciao", "buongiorno", "buonasera", "salve", "hey", "hello", "hi"]
_FAST_PATH_THANKS = ["grazie", "grazie mille", "grazie tante", "perfetto", "ok grazie", "grazie arrivederci"]


def _normalize_text(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text).lower().strip()


class WhatsAppService:
    class MessageBlockedByOptOut(Exception):
        pass

    class MessageUsageExceeded(Exception):
        pass

    def __init__(self, app_config: AppConfig, repo):
        self.app_config = app_config
        self.repo = repo

    async def send_whatsapp_message(
        self,
        org_id: uuid.UUID,
        to_number: str,
        payload: dict,
        category: str,
        meta_client,
        tenant_config: TenantConfig,
        idempotency_key: str | None = None,
        handling_type: str | None = None,
    ) -> dict:
        if idempotency_key:
            existing = await self.repo.check_idempotency(str(org_id), idempotency_key)
            if existing:
                return existing
        usage = await self.repo.check_message_usage(org_id)
        if usage and usage["messages_limit"] is not None:
            if usage["messages_used_this_period"] >= usage["messages_limit"]:
                raise self.MessageUsageExceeded(
                    f"Message limit reached for organization {org_id}: "
                    f"{usage['messages_used_this_period']}/{usage['messages_limit']}"
                )
        prefs = await self.repo.get_contact_prefs(org_id, to_number)
        if prefs and prefs.get("marketing_opt_out") and category == "marketing":
            raise self.MessageBlockedByOptOut(
                f"Contact {to_number} has marketing opt-out"
            )
        contact = await self.repo.get_or_create_contact(org_id, to_number)
        conv = await self.repo.get_or_create_conversation(org_id, contact["id"])
        msg_id = uuid.uuid4()
        msg = await self.repo.upsert_message(
            id=msg_id,
            organization_id=org_id,
            conversation_id=conv["id"],
            wam_id=None,
            direction="outbound",
            message_type=payload.get("type", "text"),
            content=payload,
            content_text=payload.get("text", {}).get("body", ""),
            status="queued",
            idempotency_key=idempotency_key,
            handling_type=handling_type,
        )
        if idempotency_key and str(msg["id"]) != str(msg_id):
            # Race genuina: un'altra richiesta con la stessa idempotency_key
            # ha vinto l'insert tra il pre-check e qui. Il messaggio esiste
            # gia' (o e' in corso): non tentare un secondo invio.
            return msg
        result = await self.attempt_delivery(
            message_id=msg_id,
            phone_number_id=tenant_config.phone_number_id,
            access_token=tenant_config.access_token,
            payload=payload,
            meta_client=meta_client,
            organization_id=org_id,
        )
        if result:
            await self.repo.increment_message_usage(org_id)
        return result

    async def attempt_delivery(
        self,
        message_id: uuid.UUID,
        phone_number_id: str,
        access_token: str,
        payload: dict,
        meta_client=None,
        *,
        organization_id,
    ) -> dict:
        if meta_client is None:
            from src.whatsapp.client import MetaClient
            from src.whatsapp.config import TenantConfig
            meta_client = MetaClient(
                TenantConfig(
                    organization_id=uuid.UUID(int=0),
                    phone_number_id=phone_number_id,
                    waba_id="",
                    access_token=access_token,
                )
            )
        send_request = SendTextRequest(
            messaging_product="whatsapp",
            recipient_type="individual",
            to=payload.get("to", payload.get("recipient", "")),
            type=payload.get("type", "text"),
            text=OutboundTextPayload(body=payload.get("text", {}).get("body", "")),
            biz_opaque_callback_data=str(message_id),
        )
        try:
            response = await meta_client.send_message(send_request)
            wam_id = response.messages[0].id if response.messages else None
            updated = await self.repo.update_message_status(
                message_id, "sent", wam_id=wam_id, organization_id=organization_id
            )
            return updated or {"status": "sent", "wam_id": wam_id}
        except Exception as e:
            await self.repo.update_message_status(message_id, "failed", error_code="send_error",
                                                  error_title=str(e), organization_id=organization_id)
            raise

    async def check_opt_out(self, text: str, lang: str = "it") -> dict:
        normalized = _normalize_text(text)
        keywords = OPT_OUT_KEYWORDS.get(lang, OPT_OUT_KEYWORDS["it"])
        for keyword in keywords:
            if keyword in normalized:
                return {"is_opt_out": True, "confidence": "high"}
        return {"is_opt_out": False, "confidence": "low"}

    async def check_human_request(self, text: str, lang: str = "it") -> bool:
        """True se il messaggio esplicita la richiesta di parlare con una persona."""
        normalized = _normalize_text(text)
        keywords = HUMAN_REQUEST_KEYWORDS.get(lang, HUMAN_REQUEST_KEYWORDS["it"])
        return any(kw in normalized for kw in keywords)

    async def fast_path_match(self, text: str, business_profile: dict) -> Optional[str]:
        normalized = _normalize_text(text)
        name = business_profile.get("name", "")
        for g in _FAST_PATH_GREETINGS:
            if g == normalized or normalized.startswith(g + " "):
                return f"Ciao! Benvenuto in {name}. Come possiamo aiutarti?"
        for t in _FAST_PATH_THANKS:
            if t == normalized or normalized.startswith(t):
                return "Prego! A nostra disposizione. Buona giornata!"
        orari = business_profile.get("orari", "")
        if orari and ("orari" in normalized or "aperto" in normalized or "chiuso" in normalized):
            return f"I nostri orari: {orari}"
        return None
