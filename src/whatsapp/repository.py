from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
import uuid
from typing import Any

from cryptography.fernet import Fernet

from src.core.db.repositories.billing_repo import BillingRepository
from src.core.db.repositories.booking_repo import BookingRepository
from src.core.db.repositories.contact_repo import ContactRepository
from src.core.db.repositories.conversation_repo import ConversationRepository
from src.core.db.repositories.document_repo import DocumentRepository
from src.core.db.repositories.message_repo import MessageRepository
from src.core.db.repositories.organization_repo import OrganizationRepository
from src.core.db.scoping import TenantScopedRepository, system_scope

STATUS_RANK = {
    "queued": 0,
    "processing": 0,
    "sending_ambiguous": 0,
    "sent": 1,
    "delivered": 2,
    "read": 3,
    "failed": 4,
}


def apply_status_update(current_status: str, new_status: str) -> bool:
    if new_status == "failed":
        return True
    return STATUS_RANK.get(new_status, 0) > STATUS_RANK.get(current_status, 0)


class Repository(TenantScopedRepository):
    """Facade di retrocompatibilità per WhatsApp Repository.

    Delega tutte le operazioni ai repository specializzati per dominio:
    - OrganizationRepository
    - ContactRepository
    - ConversationRepository
    - MessageRepository
    - BookingRepository
    - DocumentRepository
    - BillingRepository
    """

    def __init__(self, pool):
        self.pool = pool
        self._org_repo = OrganizationRepository(pool)
        self._contact_repo = ContactRepository(pool)
        self._conv_repo = ConversationRepository(pool)
        self._msg_repo = MessageRepository(pool)
        self._booking_repo = BookingRepository(pool)
        self._doc_repo = DocumentRepository(pool)
        self._billing_repo = BillingRepository(pool)

        # Accesso diretto ai sotto-repository per migrazione progressiva
        self.org_repo = self._org_repo
        self.contact_repo = self._contact_repo
        self.conv_repo = self._conv_repo
        self.msg_repo = self._msg_repo
        self.booking_repo = self._booking_repo
        self.doc_repo = self._doc_repo
        self.billing_repo = self._billing_repo

    # ── Tenant Resolution & Config ────────────────────────────

    @system_scope("tenant-resolution: lookup da webhook Meta (identita' platform-unique, pre-auth)")
    async def get_org_by_phone_number_id(self, phone_number_id: str):
        return await self._org_repo.get_org_by_phone_number_id(phone_number_id)

    @system_scope("tenant-resolution: lookup da webhook Meta (identita' platform-unique, pre-auth)")
    async def get_org_by_waba_id(self, waba_id: str):
        return await self._org_repo.get_org_by_waba_id(waba_id)

    async def get_org_subscription_state(self, org_id):
        return await self._billing_repo.get_org_subscription_state(org_id)

    async def record_usage(self, organization_id, event_type, quantity=1, metadata=None):
        return await self._billing_repo.record_usage(
            organization_id, event_type, quantity=quantity, metadata=metadata
        )

    async def get_tenant_config(self, org_id):
        return await self._org_repo.get_tenant_config(org_id)

    async def save_tenant_config(self, org_id, access_token, phone_number_id,
                                 waba_id, verify_token=None):
        return await self._org_repo.save_tenant_config(
            org_id, access_token, phone_number_id, waba_id, verify_token=verify_token
        )

    async def delete_tenant_config(self, org_id):
        return await self._org_repo.delete_tenant_config(org_id)

    def encrypt_token(self, token: str) -> str:
        return self._org_repo.encrypt_token(token)

    def decrypt_token(self, encrypted_token: str) -> str:
        return self._org_repo.decrypt_token(encrypted_token)

    async def get_org_business_profile(self, org_id):
        return await self._org_repo.get_org_business_profile(org_id)

    # ── Contacts & Consent ────────────────────────────────────

    async def get_or_create_contact(self, org_id, wa_id, profile_name=None):
        return await self._contact_repo.get_or_create_contact(org_id, wa_id, profile_name=profile_name)

    async def get_contact_consent(self, org_id, contact_id):
        return await self._contact_repo.get_contact_consent(org_id, contact_id)

    async def get_contact_prefs(self, org_id, contact_id):
        return await self._contact_repo.get_contact_prefs(org_id, contact_id)

    async def record_consent_event(self, org_id, contact_id, channel, consent_type,
                                   event_type, source, reason=None, metadata=None):
        return await self._contact_repo.record_consent_event(
            org_id, contact_id, channel, consent_type, event_type, source,
            reason=reason, metadata=metadata,
        )

    async def mark_ai_disclosure_sent(self, org_id, contact_id):
        return await self._contact_repo.mark_ai_disclosure_sent(org_id, contact_id)

    # ── Conversations ─────────────────────────────────────────

    async def get_or_create_conversation(self, org_id, contact_id):
        return await self._conv_repo.get_or_create_conversation(org_id, contact_id)

    async def get_conversation(self, org_id, conversation_id):
        return await self._conv_repo.get_conversation(org_id, conversation_id)

    async def set_conversation_ai_active(self, org_id, conv_id, is_active: bool):
        return await self._conv_repo.set_conversation_ai_active(org_id, conv_id, is_active=is_active)

    # ── Inbound / Outbound Messages & Idempotency ─────────────

    async def check_idempotency(self, message_id, org_id=None):
        return await self._msg_repo.check_idempotency(message_id, org_id=org_id)

    async def claim_inbound_messages(self, limit: int = 10):
        return await self._msg_repo.claim_inbound_messages(limit=limit)

    async def claim_message_and_check_quota(
        self, message_id: uuid.UUID, org_id: uuid.UUID
    ) -> tuple[dict | None, bool]:
        return await self._msg_repo.claim_message_and_check_quota(message_id, org_id)

    async def upsert_message(self, message_id, organization_id, conversation_id,
                             direction, message_type, content, sender_id,
                             status="queued", raw_payload=None, failure_reason=None,
                             conn=None):
        return await self._msg_repo.upsert_message(
            message_id, organization_id, conversation_id, direction, message_type,
            content, sender_id, status=status, raw_payload=raw_payload,
            failure_reason=failure_reason, conn=conn,
        )

    async def _upsert_message(self, conn, message_id, organization_id, conversation_id,
                              direction, message_type, content, sender_id,
                              status="queued", raw_payload=None, failure_reason=None):
        return await self._msg_repo._upsert_message(
            conn, message_id, organization_id, conversation_id, direction, message_type,
            content, sender_id, status=status, raw_payload=raw_payload,
            failure_reason=failure_reason,
        )

    async def get_message_org_scoped(self, message_id: uuid.UUID, org_id: uuid.UUID) -> dict | None:
        return await self._msg_repo.get_message_org_scoped(message_id, org_id)

    async def insert_delivery_attempt(self, message_id, attempt_number, status,
                                      error_code=None, error_message=None,
                                      latency_ms=None, raw_response=None,
                                      failure_category=None):
        return await self._msg_repo.insert_delivery_attempt(
            message_id, attempt_number, status, error_code=error_code,
            error_message=error_message, latency_ms=latency_ms,
            raw_response=raw_response, failure_category=failure_category,
        )

    async def claim_delivery_attempts(self, limit: int = 10, batch_window_seconds: int = 60):
        return await self._msg_repo.claim_delivery_attempts(
            limit=limit, batch_window_seconds=batch_window_seconds
        )

    async def update_delivery_attempt(self, attempt_id: uuid.UUID, status: str,
                                      error_code=None, error_message=None,
                                      latency_ms=None, raw_response=None,
                                      failure_category=None):
        return await self._msg_repo.update_delivery_attempt(
            attempt_id, status, error_code=error_code, error_message=error_message,
            latency_ms=latency_ms, raw_response=raw_response,
            failure_category=failure_category,
        )

    async def update_message_status(self, message_id, status, failure_reason=None):
        return await self._msg_repo.update_message_status(
            message_id, status, failure_reason=failure_reason
        )

    async def update_message_status_by_wam_id(self, wam_id, status, error_code=None, error_message=None):
        return await self._msg_repo.update_message_status_by_wam_id(
            wam_id, status, error_code=error_code, error_message=error_message
        )

    async def list_conversation_messages(self, org_id, conversation_id, limit=20):
        return await self._msg_repo.list_conversation_messages(org_id, conversation_id, limit=limit)

    async def get_last_ai_outbound_message(self, org_id, conversation_id):
        return await self._msg_repo.get_last_ai_outbound_message(org_id, conversation_id)

    async def save_ai_reply(self, org_id, conv_id, text, model=None,
                            tokens_in=None, tokens_out=None, reply_to_id=None):
        return await self._msg_repo.save_ai_reply(
            org_id, conv_id, text, model=model, tokens_in=tokens_in,
            tokens_out=tokens_out, reply_to_id=reply_to_id,
        )

    async def mark_message_sent(self, message_id, org_id, wam_id, raw_response=None):
        return await self._msg_repo.mark_message_sent(message_id, org_id, wam_id, raw_response=raw_response)

    async def try_mark_replied(self, message_id: uuid.UUID, org_id: uuid.UUID) -> bool:
        return await self._msg_repo.try_mark_replied(message_id, org_id)

    async def get_outbound_dedup(self, message_id, org_id):
        return await self._msg_repo.get_outbound_dedup(message_id, org_id)

    async def save_outbound_dedup(self, message_id, org_id, response_text):
        return await self._msg_repo.save_outbound_dedup(message_id, org_id, response_text)

    # ── Message Usage & Quota ─────────────────────────────────

    async def check_message_usage(self, org_id: uuid.UUID) -> dict | None:
        return await self._billing_repo.check_message_usage(org_id)

    async def increment_message_usage(self, org_id: uuid.UUID, conn=None) -> int:
        return await self._billing_repo.increment_message_usage(org_id, conn=conn)

    async def _increment_message_usage(self, conn, org_id: uuid.UUID) -> int | None:
        return await self._billing_repo._increment_message_usage(conn, org_id)

    # ── WhatsApp Templates ────────────────────────────────────

    async def upsert_template(self, organization_id, name, language, category, status, components):
        return await self._org_repo.upsert_template(
            organization_id, name, language, category, status, components
        )

    async def update_template_status(self, organization_id, name, language, status):
        return await self._org_repo.update_template_status(organization_id, name, language, status)

    # ── RAG & FAQ Cache ───────────────────────────────────────

    async def search_similar(self, organization_id, query_embedding,
                             top_k=3, similarity_threshold=0.3):
        return await self._doc_repo.search_similar(
            organization_id, query_embedding, top_k=top_k, similarity_threshold=similarity_threshold
        )

    def _vec_str(self, vec):
        return self._doc_repo._vec_str(vec)

    async def faq_cache_lookup(self, organization_id: uuid.UUID, query_hash: str) -> dict | None:
        return await self._doc_repo.faq_cache_lookup(organization_id, query_hash)

    async def faq_cache_store(
        self,
        organization_id: uuid.UUID,
        query_hash: str,
        raw_query: str,
        answer_text: str,
        source_doc_ids: list,
        ttl_hours: int = 24,
    ) -> None:
        return await self._doc_repo.faq_cache_store(
            organization_id, query_hash, raw_query, answer_text,
            source_doc_ids, ttl_hours=ttl_hours,
        )

    async def faq_cache_invalidate(self, organization_id: uuid.UUID) -> None:
        return await self._doc_repo.faq_cache_invalidate(organization_id)

    # ── Outbox Reconstruct & Stale Claims ──────────────────────

    async def reconstruct_payload_for_retry(self, message_id: uuid.UUID) -> dict | None:
        return await self._msg_repo.reconstruct_payload_for_retry(message_id)

    async def reap_stale_claims(self, stale_seconds: int = 300) -> int:
        return await self._msg_repo.reap_stale_claims(stale_seconds=stale_seconds)

    # ── Human Escalation & Inbox Tickets ──────────────────────

    async def escalate_to_human(self, org_id, conv_id, reason=None, priority="medium"):
        return await self._conv_repo.escalate_to_human(
            org_id, conv_id, reason=reason, priority=priority
        )

    async def assign_ticket(self, org_id, ticket_id, user_id):
        return await self._conv_repo.assign_ticket(org_id, ticket_id, user_id)

    async def claim_ticket(self, org_id, ticket_id, user_id):
        return await self._conv_repo.claim_ticket(org_id, ticket_id, user_id)

    async def release_ticket(self, org_id, ticket_id, user_id):
        return await self._conv_repo.release_ticket(org_id, ticket_id, user_id)

    async def update_heartbeat(self, org_id, ticket_id, user_id):
        return await self._conv_repo.update_heartbeat(org_id, ticket_id, user_id)

    async def resolve_ticket(self, org_id, ticket_id, user_id, reactivate_ai=False):
        return await self._conv_repo.resolve_ticket(
            org_id, ticket_id, user_id, reactivate_ai=reactivate_ai
        )

    async def list_tickets(self, org_id, status=None, priority=None, assigned_to=None,
                           limit=50, offset=0):
        return await self._conv_repo.list_tickets(
            org_id, status=status, priority=priority, assigned_to=assigned_to,
            limit=limit, offset=offset,
        )

    async def list_team_members(self, org_id):
        return await self._org_repo.list_team_members(org_id)

    # ── Bookings Check ────────────────────────────────────────

    async def check_booking_exists(
        self,
        org_id: uuid.UUID,
        phone: str,
        target_date,
        target_time=None,
    ) -> bool:
        return await self._booking_repo.check_booking_exists(
            org_id, phone, target_date, target_time=target_time
        )

    # ── Feedback ──────────────────────────────────────────────

    async def registra_feedback(self, organization_id, message_id, rating, comment=None,
                                created_by=None):
        return await self._msg_repo.registra_feedback(
            organization_id, message_id, rating, comment=comment, created_by=created_by
        )

    # ── Data Retention & Cleanup ──────────────────────────────

    async def delete_expired_messages(self, batch_size: int = 500) -> int:
        return await self._msg_repo.delete_expired_messages(batch_size=batch_size)

    async def purge_soft_deleted_messages(self, batch_size: int = 500) -> int:
        return await self._msg_repo.purge_soft_deleted_messages(batch_size=batch_size)

    async def cleanup_empty_conversations(self, batch_size: int = 500) -> int:
        return await self._conv_repo.cleanup_empty_conversations(batch_size=batch_size)


# Alias per retrocompatibilità esplicita
WhatsAppRepository = Repository
