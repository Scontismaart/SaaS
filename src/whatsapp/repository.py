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

    async def get_org_subscription_state(self, org_id):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT subscription_status, trial_end,
                       messages_used_this_period, messages_limit
                FROM organizations WHERE id = $1
            """, org_id)
            return dict(row) if row else None

    async def record_usage(self, organization_id, event_type, quantity=1,
                            metadata=None):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO usage_events (id, organization_id, event_type,
                                          quantity, metadata)
                VALUES ($1, $2, $3, $4, $5::jsonb)
                RETURNING *
            """, uuid.uuid4(), organization_id, event_type, quantity,
            json.dumps(metadata or {}))
            return dict(row)

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

    async def get_org_business_profile(self, org_id):
        """Profilo business a livello organizzazione (canale-agnostico):
        serve quando l'org non ha account WhatsApp (es. solo Instagram)."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT business_profile FROM organizations WHERE id = $1", org_id
            )
            return dict(row)["business_profile"] if row else None

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

    async def get_or_create_conversation(self, org_id, contact_id, canale: str = "whatsapp"):
        """canale: origine della conversazione. L'identita' del contatto
        (contacts.phone_number) e' gia' channel-agnostic (numero WA o IG id),
        quindi una conversazione nuova nasce col canale del primo messaggio."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO conversations (id, organization_id, contact_id, canale)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (organization_id, contact_id) DO UPDATE
                    SET last_message_at = NOW()
                RETURNING *
            """, uuid.uuid4(), org_id, contact_id, canale)
            return dict(row)

    async def get_contact_prefs(self, org_id, phone):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM contacts
                WHERE organization_id = $1 AND phone_number = $2 AND deleted_at IS NULL
            """, org_id, phone)
            return dict(row) if row else None

    async def upsert_message(self, id, organization_id, conversation_id, wam_id, direction,
                              message_type, content, content_text, status, handling_type=None,
                              idempotency_key=None, conn=None):
        if conn is None:
            async with self.pool.acquire() as conn:
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

    async def try_mark_replied(self, message_id, handling_type: str | None = None):
        """Atomically marks a message as replied+handled. Returns the updated
        row if this call won the race, or None if another worker already marked
        it. Call BEFORE sending the WhatsApp reply so only one worker proceeds.
        handling_type va al trigger event_log: 'ai_handled' (AI gestita),
        'escalated' (staff), 'automation' (fast path/reminder), 'opt_out',
        'suspended'."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                UPDATE messages SET replied_at = NOW(), status = 'handled',
                    handling_type = COALESCE($2, handling_type),
                    updated_at = NOW()
                WHERE id = $1 AND replied_at IS NULL
                RETURNING *
            """, message_id, handling_type)
            return dict(row) if row else None

    async def update_heartbeat(self, message_id):
        """Periodic heartbeat — tells the reaper this claim is still alive."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE messages SET heartbeat_at = NOW() WHERE id = $1",
                message_id,
            )

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
            new_status = "granted" if event_type == "opt_in" else "withdrawn"
            await conn.execute("""
                UPDATE contacts SET consent_status = $1, consent_updated_at = NOW()
                WHERE id = $2
            """, new_status, contact_id)
            return dict(row)

    async def get_contact_consent(self, contact_id) -> str | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT consent_status FROM contacts WHERE id = $1 AND deleted_at IS NULL",
                contact_id,
            )
            return row["consent_status"] if row else None

    async def mark_ai_disclosure_sent(self, contact_id: uuid.UUID) -> bool:
        """Atomicamente segna il contatto come destinatario della disclosure AI.
        Ritorna True solo per il chiamante che vince la race (primo UPDATE);
        False se la disclosure era gia' stata segnata o il contatto non esiste."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE contacts SET ai_disclosure_sent_at = NOW()
                   WHERE id = $1::uuid AND ai_disclosure_sent_at IS NULL
                   RETURNING id""",
                contact_id,
            )
            return row is not None

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

    async def reap_stale_claims(self, timeout_minutes=15, dead_letter_threshold=3):
        """Libera i claim rimasti bloccati oltre timeout_minutes.

        Per i messaggi usa heartbeat_at invece di claimed_at: un worker che
        sta ancora girando (aggiornamento heartbeat periodico) non viene
        considerato stale anche se ha superato il timeout. Se heartbeat_at
        e' NULL (record creato prima della migrazione 012) cade sul
        claimed_at come backward compat.

        Se un messaggio e' gia' stato reclamato dead_letter_threshold volte
        consecutive, viene marcato 'dead' invece di essere rimesso in coda
        all'infinito (audit 4.2)."""
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

    async def increment_message_usage(self, org_id: uuid.UUID, conn=None) -> int:
        if conn is None:
            async with self.pool.acquire() as conn:
                return await self._increment_message_usage(conn, org_id)
        return await self._increment_message_usage(conn, org_id)

    async def _increment_message_usage(self, conn, org_id: uuid.UUID) -> int:
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

    # ── RAG: Document Search ────────────────────────────────────

    async def search_similar(self, organization_id: str, embedding: list, k: int = 3) -> list[dict]:
        """Chunk piu' simili tra i documenti dell'org (distanza cosine, `<=>`).
        Lo scope `WHERE dc.organization_id = $1` e' la barriera di tensione
        tra tenant: il risultato e' sempre limitato ai documenti dell'org
        che richiede, indipendentemente da chi costruisce il prompt."""
        async with self.pool.acquire() as conn:
            vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
            rows = await conn.fetch("""
                SELECT dc.id, dc.content, dc.metadata, dc.chunk_index,
                       dc.document_id, d.nome as document_name,
                       dc.embedding <=> $2::vector AS distance
                FROM document_chunks dc
                JOIN documents d ON d.id = dc.document_id
                WHERE dc.organization_id = $1::uuid
                ORDER BY dc.embedding <=> $2::vector
                LIMIT $3
            """, organization_id, vec_str, k)
            results = [dict(r) for r in rows]
            for r in results:
                if isinstance(r.get("metadata"), str):
                    r["metadata"] = json.loads(r["metadata"])
            return results

    # ── HITL: Ticket State Machine ──────────────────────────────

    async def list_tickets(self, org_id: str, status: str | None = None, priorita: str | None = None) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """WITH enriched AS (
                       SELECT c.*, u.nome AS assigned_nome, u.email AS assigned_email,
                              ct.phone_number AS phone_number,
                              o.sla_minutes,
                              (c.pending_staff_at + (o.sla_minutes || ' minutes')::interval) AS sla_due_at,
                              (c.pending_staff_at + (o.sla_minutes || ' minutes')::interval) < NOW() AS is_overdue,
                              COALESCE(el.priorita,
                                       CASE WHEN c.ticket_status IN ('PENDING_STAFF', 'CLAIMED') THEN 'alta'
                                            ELSE 'media' END) AS priorita,
                              lm.content_text AS last_message_preview
                       FROM conversations c
                       LEFT JOIN user_profiles u ON u.id = c.assigned_to
                       LEFT JOIN contacts ct ON ct.id = c.contact_id
                       JOIN organizations o ON o.id = c.organization_id
                       LEFT JOIN LATERAL (
                           SELECT e.priorita
                           FROM event_log e
                           WHERE e.organization_id = c.organization_id
                             AND e.dettagli->>'conversation_id' = c.id::text
                           ORDER BY CASE e.priorita WHEN 'alta' THEN 0 WHEN 'media' THEN 1 ELSE 2 END,
                                    e.created_at DESC
                           LIMIT 1
                       ) el ON TRUE
                       LEFT JOIN LATERAL (
                           SELECT m.content_text
                           FROM messages m
                           WHERE m.conversation_id = c.id AND m.deleted_at IS NULL
                           ORDER BY m.created_at DESC
                           LIMIT 1
                       ) lm ON TRUE
                       WHERE c.organization_id = $1::uuid AND c.deleted_at IS NULL
                   )
                   SELECT * FROM enriched
                   WHERE ($2::text IS NULL OR ticket_status = $2)
                     AND ($3::text IS NULL OR priorita = $3)
                   ORDER BY pending_staff_at ASC NULLS LAST,
                            claimed_at ASC NULLS LAST,
                            created_at ASC""",
                org_id, status, priorita
            )
            return [dict(r) for r in rows]

    async def get_conversation(self, conversation_id: str) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """WITH enriched AS (
                       SELECT c.*, u.nome AS assigned_nome, u.email AS assigned_email,
                              ct.phone_number AS phone_number,
                              o.sla_minutes,
                              (c.pending_staff_at + (o.sla_minutes || ' minutes')::interval) AS sla_due_at,
                              (c.pending_staff_at + (o.sla_minutes || ' minutes')::interval) < NOW() AS is_overdue,
                              COALESCE(el.priorita,
                                       CASE WHEN c.ticket_status IN ('PENDING_STAFF', 'CLAIMED') THEN 'alta'
                                            ELSE 'media' END) AS priorita,
                              lm.content_text AS last_message_preview
                       FROM conversations c
                       LEFT JOIN user_profiles u ON u.id = c.assigned_to
                       LEFT JOIN contacts ct ON ct.id = c.contact_id
                       JOIN organizations o ON o.id = c.organization_id
                       LEFT JOIN LATERAL (
                           SELECT e.priorita
                           FROM event_log e
                           WHERE e.organization_id = c.organization_id
                             AND e.dettagli->>'conversation_id' = c.id::text
                           ORDER BY CASE e.priorita WHEN 'alta' THEN 0 WHEN 'media' THEN 1 ELSE 2 END,
                                    e.created_at DESC
                           LIMIT 1
                       ) el ON TRUE
                       LEFT JOIN LATERAL (
                           SELECT m.content_text
                           FROM messages m
                           WHERE m.conversation_id = c.id AND m.deleted_at IS NULL
                           ORDER BY m.created_at DESC
                           LIMIT 1
                       ) lm ON TRUE
                       WHERE c.id = $1::uuid AND c.deleted_at IS NULL
                   )
                   SELECT * FROM enriched""",
                conversation_id
            )
            return dict(row) if row else None

    async def list_conversation_messages(
        self, org_id: str, conversation_id: str, limit: int = 50, offset: int = 0
    ) -> list[dict]:
        """Storico messaggi di una conversazione per l'inbox HITL: ordine
        cronologico ASC, soft-delete escluse (GDPR). total via window
        function per la paginazione lato UI."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, direction, message_type, content_text, status,
                          handling_type, created_at,
                          COUNT(*) OVER() AS total
                   FROM messages
                   WHERE conversation_id = $1::uuid
                     AND organization_id = $2::uuid
                     AND deleted_at IS NULL
                   ORDER BY created_at ASC
                   LIMIT $3 OFFSET $4""",
                conversation_id, org_id, limit, offset
            )
            return [dict(r) for r in rows]

    async def escalate_to_human(self, conversation_id: str) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE conversations
                   SET ticket_status = 'PENDING_STAFF',
                       pending_staff_at = NOW(),
                       updated_at = NOW(),
                       version = version + 1
                   WHERE id = $1::uuid
                     AND ticket_status NOT IN ('PENDING_STAFF', 'CLAIMED', 'RESOLVED')
                     AND deleted_at IS NULL
                   RETURNING *""",
                conversation_id
            )
            return dict(row) if row else None

    async def claim_ticket(self, conversation_id: str, staff_user_id: str, expected_version: int) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE conversations
                   SET ticket_status = 'CLAIMED',
                       assigned_to = $2::uuid,
                       claimed_at = NOW(),
                       updated_at = NOW(),
                       version = version + 1
                   WHERE id = $1::uuid
                     AND version = $3
                     AND ticket_status = 'PENDING_STAFF'
                     AND deleted_at IS NULL
                   RETURNING *""",
                conversation_id, staff_user_id, expected_version
            )
            return dict(row) if row else None

    async def release_ticket(self, conversation_id: str, staff_user_id: str) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE conversations
                   SET ticket_status = 'PENDING_STAFF',
                       assigned_to = NULL,
                       claimed_at = NULL,
                       updated_at = NOW(),
                       version = version + 1
                   WHERE id = $1::uuid
                     AND assigned_to = $2::uuid
                     AND ticket_status = 'CLAIMED'
                     AND deleted_at IS NULL
                   RETURNING *""",
                conversation_id, staff_user_id
            )
            return dict(row) if row else None

    async def resolve_ticket(self, conversation_id: str, staff_user_id: str) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE conversations
                   SET ticket_status = 'RESOLVED',
                       assigned_to = NULL,
                       resolved_at = NOW(),
                       updated_at = NOW(),
                       version = version + 1
                   WHERE id = $1::uuid
                     AND assigned_to = $2::uuid
                     AND ticket_status = 'CLAIMED'
                     AND deleted_at IS NULL
                   RETURNING *""",
                conversation_id, staff_user_id
            )
            return dict(row) if row else None

    async def list_team_members(self, org_id: str) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT up.id AS user_id, up.nome, up.email, om.ruolo
                FROM organization_memberships om
                JOIN user_profiles up ON up.id = om.user_id
                WHERE om.organization_id = $1::uuid
                  AND om.ruolo IN ('owner', 'manager', 'staff')
                ORDER BY
                  CASE om.ruolo WHEN 'owner' THEN 0 WHEN 'manager' THEN 1 ELSE 2 END,
                  up.nome
            """, org_id)
            return [dict(r) for r in rows]

    async def assign_ticket(self, conversation_id: str, staff_user_id: str, expected_version: int) -> dict | None:
        """Assegna (o riassegna) un ticket a un membro del team. Funziona sia
        su PENDING_STAFF sia su CLAIMED (da qualcun altro): la riassegnazione
        non richiede prima un release. Optimistic lock su version contro la
        race con claim/release/resolve concorrenti."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE conversations
                   SET ticket_status = 'CLAIMED',
                       assigned_to = $2::uuid,
                       claimed_at = NOW(),
                       updated_at = NOW(),
                       version = version + 1
                   WHERE id = $1::uuid
                     AND version = $3
                     AND ticket_status IN ('PENDING_STAFF', 'CLAIMED')
                     AND deleted_at IS NULL
                   RETURNING *""",
                conversation_id, staff_user_id, expected_version
            )
            return dict(row) if row else None

    async def set_conversation_ai_active(self, conversation_id: str) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE conversations
                   SET ticket_status = 'AI_ACTIVE',
                       assigned_to = NULL,
                       updated_at = NOW(),
                       version = version + 1
                   WHERE id = $1::uuid AND deleted_at IS NULL
                   RETURNING *""",
                conversation_id
            )
            return dict(row) if row else None

    async def check_idempotency(self, org_id: str, idempotency_key: str) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM messages WHERE organization_id = $1::uuid AND idempotency_key = $2",
                org_id, idempotency_key
            )
            return dict(row) if row else None

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
