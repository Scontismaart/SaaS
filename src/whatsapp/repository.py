import json
import os
import uuid

from cryptography.fernet import Fernet

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


class Repository:
    def __init__(self, pool):
        self.pool = pool

    async def get_org_by_phone_number_id(self, phone_number_id: str):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT o.id as organization_id, o.name, o.business_profile,
                       wa.id as account_id, wa.phone_number_id, wa.waba_id,
                       wa.access_token, wa.verify_token
                FROM whatsapp_accounts wa
                JOIN organizations o ON o.id = wa.organization_id
                WHERE wa.phone_number_id = $1
            """, phone_number_id)
            return dict(row) if row else None

    async def get_org_by_waba_id(self, waba_id: str):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT o.id as organization_id, o.name, o.business_profile,
                       wa.id as account_id, wa.phone_number_id, wa.waba_id,
                       wa.access_token, wa.verify_token
                FROM whatsapp_accounts wa
                JOIN organizations o ON o.id = wa.organization_id
                WHERE wa.waba_id = $1
            """, waba_id)
            return dict(row) if row else None

    async def get_tenant_config(self, org_id):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT wa.access_token, wa.phone_number_id, wa.waba_id,
                       o.business_profile
                FROM whatsapp_accounts wa
                JOIN organizations o ON o.id = wa.organization_id
                WHERE wa.organization_id = $1
                LIMIT 1
            """, org_id)
            return dict(row) if row else None

    @staticmethod
    def encrypt_token(plaintext: str) -> str:
        key = os.environ.get("ENCRYPTION_KEY")
        if not key:
            raise RuntimeError("ENCRYPTION_KEY not set")
        return Fernet(key.encode()).encrypt(plaintext.encode()).decode()

    async def save_tenant_config(self, org_id, phone_number_id: str, waba_id: str, access_token: str):
        encrypted = self.encrypt_token(access_token)
        async with self.pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT id FROM whatsapp_accounts WHERE organization_id = $1", org_id
            )
            if existing:
                row = await conn.fetchrow("""
                    UPDATE whatsapp_accounts
                    SET phone_number_id = $2, waba_id = $3, access_token = $4, updated_at = NOW()
                    WHERE organization_id = $1
                    RETURNING *
                """, org_id, phone_number_id, waba_id, encrypted)
            else:
                row = await conn.fetchrow("""
                    INSERT INTO whatsapp_accounts (id, organization_id, phone_number_id, waba_id, access_token)
                    VALUES ($1, $2, $3, $4, $5)
                    RETURNING *
                """, uuid.uuid4(), org_id, phone_number_id, waba_id, encrypted)
            return dict(row)

    async def get_or_create_contact(self, org_id, phone):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO contacts (id, organization_id, phone_number)
                VALUES ($1, $2, $3)
                ON CONFLICT (organization_id, phone_number) DO UPDATE
                    SET updated_at = NOW()
                RETURNING *
            """, uuid.uuid4(), org_id, phone)
            return dict(row)

    async def get_or_create_conversation(self, org_id, contact_id):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO conversations (id, organization_id, contact_id)
                VALUES ($1, $2, $3)
                ON CONFLICT (organization_id, contact_id) DO UPDATE
                    SET last_message_at = NOW()
                RETURNING *
            """, uuid.uuid4(), org_id, contact_id)
            return dict(row)

    async def get_contact_prefs(self, org_id, phone):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM contacts
                WHERE organization_id = $1 AND phone_number = $2 AND deleted_at IS NULL
            """, org_id, phone)
            return dict(row) if row else None

    async def upsert_message(self, id, organization_id, conversation_id, wam_id, direction,
                              message_type, content, content_text, status, handling_type=None):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO messages (id, organization_id, conversation_id, wam_id,
                                      direction, message_type, content, content_text, status, handling_type)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10)
                ON CONFLICT (wam_id) WHERE wam_id IS NOT NULL DO NOTHING
                RETURNING *
            """, id, organization_id, conversation_id, wam_id, direction, message_type,
                json.dumps(content), content_text, status, handling_type)
            if row:
                return dict(row)
            row = await conn.fetchrow("SELECT * FROM messages WHERE wam_id = $1", wam_id)
            return dict(row)

    async def update_message_status(self, message_id, new_status, wam_id=None, error_code=None,
                                      error_title=None, error_details=None, biz_opaque_callback_data=None):
        async with self.pool.acquire() as conn:
            current = await conn.fetchrow("SELECT status FROM messages WHERE id = $1", message_id)
            if not current:
                return None
            if not apply_status_update(current["status"], new_status):
                return dict(current)
            set_parts = ["status = $2"]
            params = [message_id, new_status]
            idx = 3
            if wam_id:
                set_parts.append(f"wam_id = ${idx}")
                params.append(wam_id)
                idx += 1
            if error_code:
                set_parts.append(f"error_code = ${idx}")
                params.append(error_code)
                idx += 1
            if error_title:
                set_parts.append(f"error_title = ${idx}")
                params.append(error_title)
                idx += 1
            if error_details:
                set_parts.append(f"error_details = ${idx}::jsonb")
                params.append(json.dumps(error_details))
                idx += 1
            if new_status == "sent":
                set_parts.append("sent_at = NOW()")
            elif new_status == "delivered":
                set_parts.append("delivered_at = NOW()")
            elif new_status == "read":
                set_parts.append("read_at = NOW()")
            set_parts.append("updated_at = NOW()")
            row = await conn.fetchrow(
                f"UPDATE messages SET {', '.join(set_parts)} WHERE id = $1 RETURNING *",
                *params
            )
            return dict(row) if row else None

    async def update_message_status_by_wam_id(self, wam_id, new_status, error_code=None,
                                                error_title=None, error_details=None):
        async with self.pool.acquire() as conn:
            current = await conn.fetchrow(
                "SELECT id, status FROM messages WHERE wam_id = $1", wam_id
            )
            if not current:
                return None
            return await self.update_message_status(
                current["id"], new_status, wam_id=wam_id,
                error_code=error_code, error_title=error_title, error_details=error_details,
            )

    async def claim_inbound_messages(self, limit=10):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch("""
                    UPDATE messages SET status = 'processing', claimed_at = NOW()
                    WHERE id IN (
                        SELECT id FROM messages
                        WHERE direction = 'inbound' AND status = 'received_pending_ai'
                        AND deleted_at IS NULL
                        ORDER BY created_at
                        LIMIT $1
                        FOR UPDATE SKIP LOCKED
                    )
                    RETURNING *
                """, limit)
                return [dict(r) for r in rows]

    async def claim_delivery_attempts(self, limit=10):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch("""
                    SELECT * FROM message_delivery_attempts
                    WHERE status = 'pending' AND next_retry_at <= NOW()
                    ORDER BY next_retry_at
                    LIMIT $1
                    FOR UPDATE SKIP LOCKED
                """, limit)
                if rows:
                    ids = [r["id"] for r in rows]
                    await conn.execute(
                        "UPDATE message_delivery_attempts SET status = 'processing', claimed_at = NOW() WHERE id = ANY($1)",
                        ids,
                    )
                return [dict(r) for r in rows]

    async def record_consent_event(self, contact_id, event_type, method,
                                     triggering_message_id=None, matched_text=None):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO contact_consent_log (id, contact_id, event_type, method,
                                                  triggering_message_id, matched_text)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING *
            """, uuid.uuid4(), contact_id, event_type, method, triggering_message_id, matched_text)
            return dict(row)

    async def insert_delivery_attempt(self, message_id, next_retry_at):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO message_delivery_attempts (id, message_id, next_retry_at)
                VALUES ($1, $2, $3)
                RETURNING *
            """, uuid.uuid4(), message_id, next_retry_at)
            return dict(row)

    async def update_delivery_attempt(self, attempt_id, status, error_details=None):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                UPDATE message_delivery_attempts
                SET status = $2, error_details = $3::jsonb
                WHERE id = $1
                RETURNING *
            """, attempt_id, status, json.dumps(error_details) if error_details else None)
            return dict(row) if row else None

    async def reconstruct_payload_for_retry(self, message_id):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM messages WHERE id = $1", message_id
            )
            if not row:
                return None
            result = dict(row)
            if isinstance(result.get("content"), str):
                result["content"] = json.loads(result["content"])
            return result

    async def reap_stale_claims(self, timeout_minutes=5):
        async with self.pool.acquire() as conn:
            msgs = await conn.fetch("""
                UPDATE messages SET status = 'received_pending_ai', claimed_at = NULL
                WHERE status = 'processing' AND claimed_at < NOW() - ($1 || ' minutes')::INTERVAL
                RETURNING *
            """, str(timeout_minutes))
            attempts = await conn.fetch("""
                UPDATE message_delivery_attempts SET status = 'pending', claimed_at = NULL
                WHERE status = 'processing' AND claimed_at < NOW() - ($1 || ' minutes')::INTERVAL
                RETURNING *
            """, str(timeout_minutes))
            return [dict(r) for r in msgs] + [dict(r) for r in attempts]

    async def soft_delete_message(self, message_id: uuid.UUID) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE messages SET deleted_at = NOW() WHERE id = $1", message_id)

    async def soft_delete_conversation(self, conversation_id: uuid.UUID) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE conversations SET deleted_at = NOW() WHERE id = $1", conversation_id)

    async def soft_delete_contact(self, contact_id: uuid.UUID) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE contacts SET deleted_at = NOW() WHERE id = $1", contact_id)

    async def delete_expired_messages(self, retention_days: int = 60) -> int:
        async with self.pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE messages SET deleted_at = NOW()
                WHERE deleted_at IS NULL
                AND created_at < NOW() - ($1 || ' days')::INTERVAL
            """, str(retention_days))
            return int(result.split()[-1]) if result else 0

    async def purge_soft_deleted_messages(self, grace_days: int = 30) -> int:
        async with self.pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM messages
                WHERE deleted_at IS NOT NULL
                AND deleted_at < NOW() - ($1 || ' days')::INTERVAL
            """, str(grace_days))
            return int(result.split()[-1]) if result else 0

    async def cleanup_empty_conversations(self) -> int:
        async with self.pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE conversations SET deleted_at = NOW()
                WHERE deleted_at IS NULL
                AND NOT EXISTS (
                    SELECT 1 FROM messages
                    WHERE messages.conversation_id = conversations.id
                    AND messages.deleted_at IS NULL
                )
            """)
            return int(result.split()[-1]) if result else 0

    async def check_message_usage(self, org_id: uuid.UUID) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT messages_used_this_period, messages_limit
                FROM organizations WHERE id = $1
            """, org_id)
            return dict(row) if row else None

    async def increment_message_usage(self, org_id: uuid.UUID) -> int:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                UPDATE organizations
                SET messages_used_this_period = messages_used_this_period + 1
                WHERE id = $1
                RETURNING messages_used_this_period
            """, org_id)
            return row["messages_used_this_period"] if row else 0

    async def upsert_template(self, organization_id, name, language, category, status, components):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO whatsapp_templates (id, organization_id, name, language, category, status, components)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
                ON CONFLICT (organization_id, name, language) DO UPDATE
                    SET status = $6, components = $7::jsonb, updated_at = NOW()
                RETURNING *
            """, uuid.uuid4(), organization_id, name, language, category, status,
                json.dumps(components))
            return dict(row)

    async def update_template_status(self, name=None, language=None, status=None, reason=None, organization_id=None):
        async with self.pool.acquire() as conn:
            parts = ["status = $3", "updated_at = NOW()"]
            params = [name, language, status]
            idx = 4
            if reason:
                parts.append(f"rejected_reason = ${idx}")
                params.append(reason)
                idx += 1
            if organization_id:
                parts.append(f"organization_id = ${idx}")
                params.append(organization_id)
                idx += 1
            await conn.execute(
                f"UPDATE whatsapp_templates SET {', '.join(parts)} WHERE name = $1 AND language = $2",
                *params
            )
