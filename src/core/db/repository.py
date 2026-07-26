import json
import uuid
import asyncpg
from datetime import datetime


class CoreRepository:
    def __init__(self, pool):
        self.pool = pool

    # ── Bookings ──────────────────────────────────────────────

    async def create_booking(self, organization_id, nome_cliente, data, ora, coperti,
                             telefono="", note="", stato="in_attesa", origine="Dashboard",
                             richiede_intervento=False, id_conversazione=None,
                             contact_id=None, richiede_deposito=False,
                             completata_at=None):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO bookings (id, organization_id, contact_id,
                                      nome_cliente, telefono, data, ora, coperti,
                                      note, stato, origine, richiede_intervento,
                                      id_conversazione, richiede_deposito, completata_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
                RETURNING *
            """, uuid.uuid4(), organization_id, contact_id,
            nome_cliente, telefono, data, ora, coperti,
            note, stato, origine, richiede_intervento,
            id_conversazione, richiede_deposito, completata_at)
            return dict(row)

    async def get_booking(self, organization_id, booking_id):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM bookings WHERE organization_id = $1 AND id = $2",
                organization_id, booking_id,
            )
            return dict(row) if row else None

    async def list_bookings(self, organization_id, data=None):
        async with self.pool.acquire() as conn:
            if data is not None:
                rows = await conn.fetch(
                    "SELECT * FROM bookings WHERE organization_id = $1 AND data = $2 ORDER BY ora",
                    organization_id, data,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM bookings WHERE organization_id = $1 ORDER BY data DESC, ora",
                    organization_id,
                )
            return [dict(r) for r in rows]

    async def update_booking_status(self, organization_id, booking_id, stato):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                UPDATE bookings SET stato = $3, updated_at = NOW()
                WHERE organization_id = $1 AND id = $2
                RETURNING *
            """, organization_id, booking_id, stato)
            return dict(row) if row else None

    async def update_booking_payment(self, organization_id, booking_id,
                                      payment_status, session_id=None):
        async with self.pool.acquire() as conn:
            if session_id:
                row = await conn.fetchrow("""
                    UPDATE bookings SET payment_status = $3, payment_link = $4,
                        payment_link_created_at = NOW(), updated_at = NOW()
                    WHERE organization_id = $1 AND id = $2
                    RETURNING *
                """, organization_id, booking_id, payment_status, session_id)
            else:
                row = await conn.fetchrow("""
                    UPDATE bookings SET payment_status = $3, updated_at = NOW()
                    WHERE organization_id = $1 AND id = $2
                    RETURNING *
                """, organization_id, booking_id, payment_status)
            return dict(row) if row else None

    async def list_bookings_by_stato(self, organization_id, stato):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM bookings WHERE organization_id = $1 AND stato = $2 ORDER BY data, ora",
                organization_id, stato,
            )
            return [dict(r) for r in rows]

    async def list_bookings_for_reminder(self, organization_id, target_date):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM bookings
                WHERE organization_id = $1 AND data = $2
                  AND stato = 'confermata' AND reminder_status = 'none'
                ORDER BY ora
            """, organization_id, target_date)
            return [dict(r) for r in rows]

    async def update_booking_reminder_status(self, organization_id, booking_id,
                                              reminder_status, responded_at=None):
        async with self.pool.acquire() as conn:
            if responded_at:
                row = await conn.fetchrow("""
                    UPDATE bookings SET reminder_status = $3,
                        reminder_responded_at = $4, updated_at = NOW()
                    WHERE organization_id = $1 AND id = $2
                    RETURNING *
                """, organization_id, booking_id, reminder_status, responded_at)
            else:
                row = await conn.fetchrow("""
                    UPDATE bookings SET reminder_status = $3, updated_at = NOW()
                    WHERE organization_id = $1 AND id = $2
                    RETURNING *
                """, organization_id, booking_id, reminder_status)
            return dict(row) if row else None

    async def list_bookings_da_verificare(self, organization_id, target_date):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM bookings
                WHERE organization_id = $1 AND data = $2
                  AND stato = 'confermata'
                  AND completata_at IS NULL AND no_show_at IS NULL
                ORDER BY ora
            """, organization_id, target_date)
            return [dict(r) for r in rows]

    async def upsert_booking_settings_config(self, organization_id, config):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO booking_settings (id, organization_id, config)
                VALUES ($1, $2, $3::jsonb)
                ON CONFLICT (organization_id) DO UPDATE
                    SET config = $3::jsonb, updated_at = NOW()
                RETURNING *
            """, uuid.uuid4(), organization_id, json.dumps(config))
            result = dict(row)
            if isinstance(result.get("config"), str):
                result["config"] = json.loads(result["config"])
            return result

    # ── Booking settings ─────────────────────────────────────

    async def get_booking_settings(self, organization_id):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM booking_settings WHERE organization_id = $1",
                organization_id,
            )
            if row is None:
                return None
            result = dict(row)
            if isinstance(result.get("fasce_orarie"), str):
                result["fasce_orarie"] = json.loads(result["fasce_orarie"])
            if isinstance(result.get("capienze_orarie"), str):
                result["capienze_orarie"] = json.loads(result["capienze_orarie"])
            return result

    # ── Reviews ───────────────────────────────────────────────

    async def create_review(self, organization_id, testo,
                             valutazione_stelle=None, fonte="manuale", autore="",
                             contact_id=None):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO reviews (id, organization_id, contact_id, testo,
                                     valutazione_stelle, fonte, autore)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING *
            """, uuid.uuid4(), organization_id, contact_id, testo,
            valutazione_stelle, fonte, autore)
            return dict(row)

    async def list_reviews(self, organization_id):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM reviews WHERE organization_id = $1 ORDER BY created_at DESC",
                organization_id,
            )
            return [dict(r) for r in rows]

    async def upsert_booking_settings(self, organization_id, fasce_orarie,
                                       capienze_orarie, slot_minutes=60):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO booking_settings (id, organization_id, slot_minutes,
                                              fasce_orarie, capienze_orarie)
                VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)
                ON CONFLICT (organization_id) DO UPDATE
                    SET slot_minutes = $3,
                        fasce_orarie = $4::jsonb,
                        capienze_orarie = $5::jsonb,
                        updated_at = NOW()
                RETURNING *
            """, uuid.uuid4(), organization_id, slot_minutes,
            json.dumps(fasce_orarie), json.dumps(capienze_orarie))
            result = dict(row)
            if isinstance(result.get("fasce_orarie"), str):
                result["fasce_orarie"] = json.loads(result["fasce_orarie"])
            if isinstance(result.get("capienze_orarie"), str):
                result["capienze_orarie"] = json.loads(result["capienze_orarie"])
            return result

    # ── Documents ────────────────────────────────────────────

    async def create_document(self, organization_id, nome, tipo="upload",
                               fonte="", caricato_il=None):
        async with self.pool.acquire() as conn:
            if caricato_il is None:
                row = await conn.fetchrow("""
                    INSERT INTO documents (id, organization_id, nome, tipo, fonte)
                    VALUES ($1, $2, $3, $4, $5)
                    RETURNING *
                """, uuid.uuid4(), organization_id, nome, tipo, fonte)
            else:
                row = await conn.fetchrow("""
                    INSERT INTO documents (id, organization_id, nome, tipo, fonte, caricato_il)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING *
                """, uuid.uuid4(), organization_id, nome, tipo, fonte, caricato_il)
            return dict(row)

    async def add_chunk(self, organization_id, document_id, chunk_index,
                         content, embedding, metadata=None):
        async with self.pool.acquire() as conn:
            vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
            row = await conn.fetchrow("""
                INSERT INTO document_chunks (id, organization_id, document_id,
                                             chunk_index, content, embedding, metadata)
                VALUES ($1, $2, $3, $4, $5, $6::vector, $7::jsonb)
                RETURNING *
            """, uuid.uuid4(), organization_id, document_id,
            chunk_index, content, vec_str,
            json.dumps(metadata or {}))
            result = dict(row)
            if isinstance(result.get("metadata"), str):
                result["metadata"] = json.loads(result["metadata"])
            return result

    async def search_similar(self, organization_id, embedding, k=5):
        async with self.pool.acquire() as conn:
            vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
            rows = await conn.fetch("""
                SELECT dc.id, dc.content, dc.metadata, dc.chunk_index,
                       dc.document_id, d.nome as document_name,
                       dc.embedding <=> $2::vector AS distance
                FROM document_chunks dc
                JOIN documents d ON d.id = dc.document_id
                WHERE dc.organization_id = $1
                ORDER BY dc.embedding <=> $2::vector
                LIMIT $3
            """, organization_id, vec_str, k)
            results = [dict(r) for r in rows]
            for r in results:
                if isinstance(r.get("metadata"), str):
                    r["metadata"] = json.loads(r["metadata"])
            return results

    async def list_documents(self, organization_id):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM documents WHERE organization_id = $1 ORDER BY created_at DESC",
                organization_id,
            )
            return [dict(r) for r in rows]

    # ── Email configs ─────────────────────────────────────────

    async def add_email_config(self, organization_id, indirizzo, is_active=True):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO email_configs (id, organization_id, indirizzo, is_active)
                VALUES ($1, $2, $3, $4)
                RETURNING *
            """, uuid.uuid4(), organization_id, indirizzo, is_active)
            return dict(row)

    async def list_email_configs(self, organization_id):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM email_configs WHERE organization_id = $1 ORDER BY created_at",
                organization_id,
            )
            return [dict(r) for r in rows]

    async def remove_email_config(self, organization_id, indirizzo):
        async with self.pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM email_configs
                WHERE organization_id = $1 AND indirizzo = $2
            """, organization_id, indirizzo)
            return result != "DELETE 0"

    # ── Usage events ──────────────────────────────────────────

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

    async def get_usage_by_month(self, organization_id, year, month):
        from datetime import date
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM usage_events
                WHERE organization_id = $1
                  AND billing_month = $2
                ORDER BY created_at
            """, organization_id, date(year, month, 1))
            return [dict(r) for r in rows]

    async def get_usage_summary(self, organization_id, year, month):
        from datetime import date
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT event_type, SUM(quantity)::int as total
                FROM usage_events
                WHERE organization_id = $1
                  AND billing_month = $2
                GROUP BY event_type
            """, organization_id, date(year, month, 1))
            return {r["event_type"]: r["total"] for r in rows}

    # ── Auth ──────────────────────────────────────────────────

    async def get_membership_by_auth(self, auth_user_id: str, organization_id: str) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT om.ruolo, om.organization_id, up.id as user_id
                FROM organization_memberships om
                JOIN user_profiles up ON up.id = om.user_id
                WHERE up.auth_user_id = $1 AND om.organization_id = $2::uuid
            """, auth_user_id, organization_id)
            return dict(row) if row else None

    # ── Billing ──────────────────────────────────────────────────

    async def get_organization_billing(self, organization_id: uuid.UUID | str) -> dict:
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT stripe_customer_id, subscription_id, subscription_status,
                       plan, messages_used_this_period, messages_limit,
                       users_limit, whatsapp_numbers_limit,
                       current_period_start, current_period_end,
                       trial_start, trial_end
                FROM organizations WHERE id = $1
            """, organization_id)
            if row is None:
                raise ValueError(f"Organization {organization_id} not found")
            return dict(row)

    async def update_organization_billing(
        self, organization_id: uuid.UUID | str, data: dict
    ) -> dict:
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)
        sets = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(data))
        values = list(data.values())
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""UPDATE organizations SET {sets}
                    WHERE id = $1
                    RETURNING stripe_customer_id, subscription_id, subscription_status,
                              plan, messages_used_this_period, messages_limit,
                              users_limit, whatsapp_numbers_limit,
                              current_period_start, current_period_end,
                              trial_start, trial_end""",
                organization_id,
                *values,
            )
            return dict(row)

    async def set_subscription_status(
        self, organization_id: uuid.UUID | str, status: str
    ) -> None:
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE organizations SET subscription_status = $1 WHERE id = $2",
                status,
                organization_id,
            )

    async def increment_message_usage(
        self, organization_id: uuid.UUID | str
    ) -> int:
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE organizations
                   SET messages_used_this_period = messages_used_this_period + 1
                   WHERE id = $1
                   RETURNING messages_used_this_period""",
                organization_id,
            )
            return row["messages_used_this_period"]

    async def reset_message_usage(
        self,
        organization_id: uuid.UUID | str,
        period_start: datetime,
        period_end: datetime,
    ) -> None:
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)
        async with self.pool.acquire() as conn:
            await conn.execute(
                """UPDATE organizations
                   SET messages_used_this_period = 0,
                       current_period_start = $1,
                       current_period_end = $2
                   WHERE id = $3""",
                period_start,
                period_end,
                organization_id,
            )

    async def process_stripe_event(
        self, event_id: str, organization_id: uuid.UUID | str
    ) -> bool:
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    "INSERT INTO processed_stripe_events (event_id, organization_id) VALUES ($1, $2)",
                    event_id,
                    organization_id,
                )
                return True
            except asyncpg.exceptions.UniqueViolationError:
                return False

    async def update_plan_limits(
        self, organization_id: uuid.UUID | str, plan_slug: str
    ) -> dict:
        from src.core.billing.plans import get_plan
        plan = get_plan(plan_slug)
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE organizations
                   SET plan = $1,
                       messages_limit = $2,
                       users_limit = $3,
                       whatsapp_numbers_limit = $4
                   WHERE id = $5
                   RETURNING stripe_customer_id, subscription_id, subscription_status,
                             plan, messages_used_this_period, messages_limit,
                             users_limit, whatsapp_numbers_limit,
                             current_period_start, current_period_end,
                             trial_start, trial_end""",
                plan_slug,
                plan.messages_limit,
                plan.users_limit,
                plan.whatsapp_numbers_limit,
                organization_id,
            )
            return dict(row)

    async def get_organization_by_stripe_customer(
        self, stripe_customer_id: str
    ) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, stripe_customer_id, subscription_status, plan, "
                "current_period_start "
                "FROM organizations WHERE stripe_customer_id = $1",
                stripe_customer_id,
            )
            if row is None:
                return None
            return dict(row)

    # ── GDPR ─────────────────────────────────────────────────────

    async def get_contacts_by_org(self, organization_id: uuid.UUID | str) -> list[dict]:
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM contacts WHERE organization_id = $1 AND deleted_at IS NULL ORDER BY created_at DESC",
                organization_id,
            )
            return [dict(r) for r in rows]

    async def get_conversations_by_org(self, organization_id: uuid.UUID | str) -> list[dict]:
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM conversations WHERE organization_id = $1 AND deleted_at IS NULL ORDER BY created_at DESC",
                organization_id,
            )
            return [dict(r) for r in rows]

    async def get_messages_by_org(self, organization_id: uuid.UUID | str) -> list[dict]:
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM messages WHERE organization_id = $1 AND deleted_at IS NULL ORDER BY created_at DESC",
                organization_id,
            )
            return [dict(r) for r in rows]

    async def get_organization_owners(self, org_id: str) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT up.id, up.email, up.nome
                   FROM user_profiles up
                   JOIN organization_memberships om ON om.user_id = up.id
                   WHERE om.organization_id = $1::uuid AND om.ruolo = 'owner'""",
                org_id
            )
            return [dict(r) for r in rows]

    async def delete_organization(self, organization_id: uuid.UUID | str) -> None:
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM audit_log WHERE organization_id = $1", organization_id)
            await conn.execute("DELETE FROM messages WHERE organization_id = $1", organization_id)
            await conn.execute("DELETE FROM conversations WHERE organization_id = $1", organization_id)
            await conn.execute("DELETE FROM contacts WHERE organization_id = $1", organization_id)
            await conn.execute("DELETE FROM bookings WHERE organization_id = $1", organization_id)
            await conn.execute("DELETE FROM reviews WHERE organization_id = $1", organization_id)
            await conn.execute("DELETE FROM email_configs WHERE organization_id = $1", organization_id)
            await conn.execute("DELETE FROM documents WHERE organization_id = $1", organization_id)
            await conn.execute("DELETE FROM organizations WHERE id = $1", organization_id)
