import json
import uuid
from datetime import datetime, timezone

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
    if new_status == "sending_ambiguous" and current_status in ("queued", "processing"):
        # Pre-mark Send-Then-Mark: mossa laterale consentita prima della chiamata Meta.
        return True
    return STATUS_RANK.get(new_status, 0) > STATUS_RANK.get(current_status, 0)


class MessageRepository(TenantScopedRepository):
    """Repository specializzato per Code Messaggi, Claim atomici (P0), Retry e Deduplica."""

    def __init__(self, pool):
        self.pool = pool

    # ── Upsert & Status Updates ───────────────────────────────────

    async def upsert_message(self, id, organization_id, conversation_id, wam_id, direction,
                              message_type, content, content_text, status, handling_type=None,
                              idempotency_key=None, conn=None):
        if conn is None:
            async with self.scoped_conn(organization_id) as conn:
                return await self._upsert_message(conn, id, organization_id, conversation_id,
                    wam_id, direction, message_type, content, content_text, status,
                    handling_type, idempotency_key)
        return await self._upsert_message(conn, id, organization_id, conversation_id,
            wam_id, direction, message_type, content, content_text, status,
            handling_type, idempotency_key)

    async def _upsert_message(self, conn, id, organization_id, conversation_id, wam_id, direction,
                               message_type, content, content_text, status, handling_type=None,
                               idempotency_key=None):
        if idempotency_key:
            row = await conn.fetchrow("""
                INSERT INTO messages (id, organization_id, conversation_id, wam_id,
                                      direction, message_type, content, content_text,
                                      status, handling_type, idempotency_key)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10, $11)
                ON CONFLICT (organization_id, idempotency_key) WHERE idempotency_key IS NOT NULL
                    DO NOTHING
                RETURNING *
            """, id, organization_id, conversation_id, wam_id, direction, message_type,
                json.dumps(content), content_text, status, handling_type, idempotency_key)
            if row:
                return dict(row)
            row = await conn.fetchrow(
                "SELECT * FROM messages WHERE organization_id = $1 AND idempotency_key = $2",
                organization_id, idempotency_key,
            )
            return dict(row)
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
        row = await conn.fetchrow(
            "SELECT * FROM messages WHERE wam_id = $1 AND organization_id = $2",
            wam_id, organization_id,
        )
        return dict(row) if row else None

    async def update_message_status(self, message_id, new_status, wam_id=None, error_code=None,
                                      error_title=None, error_details=None, biz_opaque_callback_data=None,
                                      *, organization_id):
        async with self.scoped_conn(organization_id) as conn:
            current = await conn.fetchrow(
                "SELECT status FROM messages WHERE id = $1 AND organization_id = $2::uuid",
                message_id, organization_id,
            )
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
                f"UPDATE messages SET {', '.join(set_parts)} WHERE id = $1 AND organization_id = ${idx}::uuid RETURNING *",
                *params, organization_id
            )
            return dict(row) if row else None

    async def update_message_status_by_wam_id(self, wam_id, new_status, error_code=None,
                                                error_title=None, error_details=None,
                                                *, organization_id):
        async with self.scoped_conn(organization_id) as conn:
            current = await conn.fetchrow(
                "SELECT id, status FROM messages WHERE wam_id = $1 AND organization_id = $2::uuid",
                wam_id, organization_id,
            )
            if not current:
                return None
            return await self.update_message_status(
                current["id"], new_status, wam_id=wam_id,
                error_code=error_code, error_title=error_title, error_details=error_details,
                organization_id=organization_id,
            )

    # ── Claim Atomici & Concorrenza P0 ────────────────────────────

    @system_scope("worker queue: claim globale SKIP LOCKED, solo background job fidati")
    async def claim_inbound_messages(self, limit=10):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch("""
                    UPDATE messages SET status = 'processing', claimed_at = NOW(),
                        heartbeat_at = NOW()
                    WHERE id IN (
                        SELECT id FROM messages
                        WHERE direction = 'inbound' AND status = 'received_pending_ai'
                        AND deleted_at IS NULL AND replied_at IS NULL
                        ORDER BY created_at
                        LIMIT $1
                        FOR UPDATE SKIP LOCKED
                    )
                    RETURNING *,
                        (SELECT c.canale FROM conversations c
                         WHERE c.id = messages.conversation_id) AS canale
                """, limit)
                return [dict(r) for r in rows]

    async def claim_message_and_check_quota(self, msg_id: str, org_id: str) -> dict:
        async with self.scoped_conn(org_id) as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT id, billed_at, ai_reply_cache, sent_at, quota_exceeded_at, processing_at FROM messages WHERE id = $1::uuid AND organization_id = $2::uuid FOR UPDATE",
                    msg_id, org_id
                )
                if not row:
                    return {"status": "not_found"}

                if row["sent_at"] is not None:
                    return {"status": "already_sent"}

                if row["quota_exceeded_at"] is not None:
                    return {"status": "quota_exceeded"}

                if (
                    row["processing_at"] is not None
                    and row["ai_reply_cache"] is None
                    and (datetime.now(timezone.utc) - row["processing_at"]).total_seconds() < 30
                ):
                    return {"status": "currently_processing"}

                if row["billed_at"] is None:
                    updated_org = await conn.fetchrow("""
                        UPDATE organizations
                        SET messages_used_this_period = messages_used_this_period + 1
                        WHERE id = $1::uuid AND (messages_limit IS NULL OR messages_used_this_period < messages_limit)
                        RETURNING messages_used_this_period
                    """, org_id)

                    if not updated_org:
                        await conn.execute(
                            "UPDATE messages SET quota_exceeded_at = now() WHERE id = $1::uuid AND organization_id = $2::uuid",
                            msg_id, org_id
                        )
                        return {"status": "quota_exceeded"}

                    await conn.execute(
                        "UPDATE messages SET billed_at = now() WHERE id = $1::uuid AND organization_id = $2::uuid",
                        msg_id, org_id
                    )

                cache_val = row["ai_reply_cache"]
                if isinstance(cache_val, str):
                    try:
                        cache_val = json.loads(cache_val)
                    except Exception:
                        cache_val = {"text": cache_val, "richiede_umano": False}

                if cache_val is None:
                    await conn.execute(
                        "UPDATE messages SET processing_at = now() WHERE id = $1::uuid AND organization_id = $2::uuid", msg_id, org_id
                    )

                return {"status": "claimed", "ai_reply_cache": cache_val}

    async def try_mark_replied(self, message_id, handling_type: str | None = None, *,
                               organization_id):
        """Atomically marks a message as replied+handled."""
        async with self.scoped_conn(organization_id) as conn:
            row = await conn.fetchrow("""
                UPDATE messages SET replied_at = NOW(), status = 'handled',
                    handling_type = COALESCE($2, handling_type),
                    updated_at = NOW()
                WHERE id = $1 AND organization_id = $3::uuid AND replied_at IS NULL
                RETURNING *
            """, message_id, handling_type, organization_id)
            return dict(row) if row else None

    async def update_heartbeat(self, message_id, organization_id):
        """Periodic heartbeat — tells the reaper this claim is still alive."""
        async with self.scoped_conn(organization_id) as conn:
            await conn.execute(
                "UPDATE messages SET heartbeat_at = NOW() WHERE id = $1 AND organization_id = $2::uuid",
                message_id, organization_id,
            )

    @system_scope("worker queue: claim globale SKIP LOCKED, solo background job fidati")
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

    @system_scope("tabella indiretta (via messages), solo worker")
    async def insert_delivery_attempt(self, message_id, next_retry_at):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO message_delivery_attempts (id, message_id, next_retry_at)
                VALUES ($1, $2, $3)
                RETURNING *
            """, uuid.uuid4(), message_id, next_retry_at)
            return dict(row)

    @system_scope("tabella indiretta (via messages), solo worker")
    async def update_delivery_attempt(self, attempt_id, status, error_details=None):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                UPDATE message_delivery_attempts
                SET status = $2, error_details = $3::jsonb
                WHERE id = $1
                RETURNING *
            """, attempt_id, status, json.dumps(error_details) if error_details else None)
            return dict(row) if row else None

    @system_scope("retry worker: org letta dal payload e riusata a valle")
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

    @system_scope("retention/reaper globale: manutenzione cross-tenant programmata")
    async def reap_stale_claims(self, timeout_minutes=15, dead_letter_threshold=3):
        """Libera i claim rimasti bloccati oltre timeout_minutes."""
        async with self.pool.acquire() as conn:
            dead = await conn.fetch("""
                UPDATE messages SET status = 'dead', claimed_at = NULL
                WHERE status = 'processing'
                AND (
                    (heartbeat_at IS NOT NULL AND heartbeat_at < NOW() - ($1 || ' minutes')::INTERVAL)
                    OR
                    (heartbeat_at IS NULL AND claimed_at < NOW() - ($1 || ' minutes')::INTERVAL)
                )
                AND dead_letter_count >= $2
                RETURNING *
            """, str(timeout_minutes), dead_letter_threshold)
            msgs = await conn.fetch("""
                UPDATE messages SET status = 'received_pending_ai', claimed_at = NULL,
                    heartbeat_at = NULL, dead_letter_count = dead_letter_count + 1
                WHERE status = 'processing'
                AND (
                    (heartbeat_at IS NOT NULL AND heartbeat_at < NOW() - ($1 || ' minutes')::INTERVAL)
                    OR
                    (heartbeat_at IS NULL AND claimed_at < NOW() - ($1 || ' minutes')::INTERVAL)
                )
                RETURNING *
            """, str(timeout_minutes))
            attempts = await conn.fetch("""
                UPDATE message_delivery_attempts SET status = 'pending', claimed_at = NULL
                WHERE status = 'processing' AND claimed_at < NOW() - ($1 || ' minutes')::INTERVAL
                RETURNING *
            """, str(timeout_minutes))
            return [dict(r) for r in dead] + [dict(r) for r in msgs] + [dict(r) for r in attempts]

    @system_scope("retention/reaper globale: manutenzione cross-tenant programmata")
    async def delete_expired_messages(self, retention_days: int = 60) -> int:
        async with self.pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE messages SET deleted_at = NOW()
                WHERE deleted_at IS NULL
                AND created_at < NOW() - ($1 || ' days')::INTERVAL
            """, str(retention_days))
            return int(result.split()[-1]) if result else 0

    @system_scope("retention/reaper globale: manutenzione cross-tenant programmata")
    async def purge_soft_deleted_messages(self, grace_days: int = 30) -> int:
        async with self.pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM messages
                WHERE deleted_at IS NOT NULL
                AND deleted_at < NOW() - ($1 || ' days')::INTERVAL
            """, str(grace_days))
            return int(result.split()[-1]) if result else 0

    async def get_outbound_dedup(self, organization_id, message_id) -> dict | None:
        async with self.scoped_conn(organization_id) as conn:
            row = await conn.fetchrow("""
                SELECT response_text FROM outbound_dedup
                WHERE message_id = $2 AND organization_id = $1
            """, organization_id, message_id)
            return dict(row) if row else None

    async def save_outbound_dedup(self, message_id: uuid.UUID, org_id: uuid.UUID, response_text: str):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO outbound_dedup (message_id, organization_id, response_text)
                VALUES ($1, $2, $3)
                ON CONFLICT (message_id) DO UPDATE SET response_text = EXCLUDED.response_text
            """, message_id, org_id, response_text)

    async def get_last_ai_outbound_message(self, organization_id,
                                           conversation_id) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM messages
                WHERE organization_id = $1::uuid
                  AND conversation_id = $2::uuid
                  AND direction = 'outbound'
                  AND handling_type = 'ai_handled'
                  AND deleted_at IS NULL
                ORDER BY created_at DESC
                LIMIT 1
            """, organization_id, conversation_id)
            return dict(row) if row else None

    async def get_message_org_scoped(self, organization_id, message_id) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM messages
                WHERE id = $2::uuid AND organization_id = $1::uuid
                  AND deleted_at IS NULL
            """, organization_id, message_id)
            return dict(row) if row else None

    async def registra_feedback(self, organization_id, message_id, conversation_id,
                                source: str, value: str,
                                created_by_user_id=None) -> dict:
        async with self.pool.acquire() as conn:
            if source == "customer_emoji":
                row = await conn.fetchrow("""
                    INSERT INTO message_feedback
                        (id, organization_id, message_id, conversation_id, source, value)
                    VALUES ($1, $2::uuid, $3::uuid, $4::uuid, 'customer_emoji', $5)
                    ON CONFLICT (message_id) WHERE source = 'customer_emoji'
                        DO UPDATE SET value = EXCLUDED.value
                    RETURNING *
                """, uuid.uuid4(), organization_id, message_id, conversation_id, value)
            else:
                row = await conn.fetchrow("""
                    INSERT INTO message_feedback
                        (id, organization_id, message_id, conversation_id, source,
                         value, created_by_user_id)
                    VALUES ($1, $2::uuid, $3::uuid, $4::uuid, 'staff_ui', $5, $6::uuid)
                    ON CONFLICT (message_id, created_by_user_id) WHERE source = 'staff_ui'
                        DO UPDATE SET value = EXCLUDED.value
                    RETURNING *
                """, uuid.uuid4(), organization_id, message_id, conversation_id,
                    value, created_by_user_id)
            return dict(row)

    async def check_idempotency(self, org_id: str, idempotency_key: str) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM messages WHERE organization_id = $1::uuid AND idempotency_key = $2",
                org_id, idempotency_key
            )
            return dict(row) if row else None

    async def check_booking_exists(self, msg_id: str, org_id: str) -> bool:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM bookings WHERE organization_id = $1::uuid AND source_message_id = $2",
                org_id, str(msg_id)
            )
            return bool(row)

    async def save_ai_reply(self, msg_id: str, reply: dict | str, richiede_umano: bool = False,
                            motivo: str = "", *, organization_id) -> None:
        if isinstance(reply, dict):
            payload = reply
        else:
            payload = {
                "text": reply,
                "richiede_umano": richiede_umano,
                "motivo": motivo,
            }
        async with self.scoped_conn(organization_id) as conn:
            await conn.execute(
                "UPDATE messages SET ai_reply_cache = $2::jsonb, ai_reply_generated_at = now() WHERE id = $1::uuid AND organization_id = $3::uuid",
                msg_id, json.dumps(payload), organization_id
            )

    async def mark_message_sent(self, msg_id: str, meta_message_id: str, organization_id) -> None:
        async with self.scoped_conn(organization_id) as conn:
            await conn.execute(
                "UPDATE messages SET sent_at = now(), meta_message_id = $2 WHERE id = $1::uuid AND organization_id = $3::uuid",
                msg_id, str(meta_message_id), organization_id
            )

    async def get_messages_by_org(self, organization_id: uuid.UUID | str) -> list[dict]:
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM messages WHERE organization_id = $1 AND deleted_at IS NULL ORDER BY created_at DESC",
                organization_id,
            )
            return [dict(r) for r in rows]
