import uuid
from src.instagram.client import InstagramClient
from src.instagram.config import InstagramTenantConfig
from src.instagram.models import IgSendTextRequest


class InstagramService:
    """Invio messaggi outbound su Instagram DM. Persiste l'outbound in
    messages (stessa tabella del canale WhatsApp, wam_id=NULL) e aggiorna lo
    stato dopo l'invio. L'idempotenza reply usa la stessa chiave parziale
    (organization_id, idempotency_key) del canale WhatsApp."""

    def __init__(self, wrepo):
        self.repo = wrepo

    async def send_instagram_message(
        self,
        org_id: uuid.UUID,
        to_ig_id: str,
        text: str,
        ig_config: InstagramTenantConfig,
        idempotency_key: str | None = None,
        handling_type: str | None = None,
    ) -> dict:
        if idempotency_key:
            existing = await self.repo.check_idempotency(str(org_id), idempotency_key)
            if existing:
                return existing

        contact = await self.repo.get_or_create_contact(org_id, to_ig_id)
        conv = await self.repo.get_or_create_conversation(org_id, contact["id"], canale="instagram")
        msg_id = uuid.uuid4()
        msg = await self.repo.upsert_message(
            id=msg_id,
            organization_id=org_id,
            conversation_id=conv["id"],
            wam_id=None,
            direction="outbound",
            message_type="text",
            content={"to": to_ig_id, "type": "text", "text": {"body": text}, "channel": "instagram"},
            content_text=text,
            status="queued",
            idempotency_key=idempotency_key,
            handling_type=handling_type,
        )
        if idempotency_key and str(msg["id"]) != str(msg_id):
            # Race genuina su idempotency_key: un'altra richiesta ha gia'
            # inserito (o sta inserendo) il messaggio: niente doppio invio.
            return msg

        client = InstagramClient(
            ig_user_id=ig_config.ig_user_id,
            access_token=ig_config.access_token,
        )
        try:
            response = await client.send_message(
                IgSendTextRequest(recipient={"id": to_ig_id}, message={"text": text})
            )
            updated = await self.repo.update_message_status(
                msg_id, "sent", wam_id=response.message_id
            )
            return updated or {"status": "sent", "wam_id": response.message_id}
        except Exception as e:
            await self.repo.update_message_status(msg_id, "failed", error_code="send_error", error_title=str(e))
            raise
        finally:
            await client.close()
