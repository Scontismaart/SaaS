import uuid
from src.instagram.client import InstagramClient
from src.instagram.config import InstagramTenantConfig
from src.instagram.models import IgSendTextRequest
from src.core.channels.delivery import DeliveryUnconfirmed, validate_replayed_payload


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
        payload = {"to": to_ig_id, "type": "text", "text": {"body": text}, "channel": "instagram"}
        from src.core.channels.sandbox_policy import assert_recipient_allowed
        assert_recipient_allowed("instagram", to_ig_id)
        if idempotency_key:
            existing = await self.repo.check_idempotency(str(org_id), idempotency_key)
            if existing:
                validate_replayed_payload(existing, payload)
                if existing.get("wam_id") or existing.get("status") == "sending_ambiguous":
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
            content=payload,
            content_text=text,
            status="queued",
            idempotency_key=idempotency_key,
            handling_type=handling_type,
        )
        if idempotency_key and str(msg["id"]) != str(msg_id):
            # Race genuina su idempotency_key: un'altra richiesta ha gia'
            # inserito (o sta inserendo) il messaggio: niente doppio invio.
            validate_replayed_payload(msg, payload)
        msg_id = msg["id"]
        claimed = await self.repo.claim_outbound_delivery(msg_id, organization_id=org_id)
        if not claimed:
            raise DeliveryUnconfirmed("Outbound already claimed or requires reconciliation")

        client = InstagramClient(
            ig_user_id=ig_config.ig_user_id,
            access_token=ig_config.access_token,
        )
        try:
            response = await client.send_message(
                IgSendTextRequest(recipient={"id": to_ig_id}, message={"text": text})
            )
            if not response.message_id:
                raise DeliveryUnconfirmed("Instagram returned no provider message ID")
            updated = await self.repo.update_message_status(
                msg_id, "sent", wam_id=response.message_id, organization_id=org_id
            )
            if not updated:
                raise DeliveryUnconfirmed("Provider accepted message but persistence failed")
            return updated
        finally:
            await client.close()
