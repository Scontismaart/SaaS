import uuid
from src.core.db.scoping import TenantScopedRepository


class ContactRepository(TenantScopedRepository):
    """Repository specializzato per il dominio Contatti, Preferenze e Consensi GDPR."""

    def __init__(self, pool):
        self.pool = pool

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

    async def get_contact_prefs(self, org_id, phone):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM contacts
                WHERE organization_id = $1 AND phone_number = $2 AND deleted_at IS NULL
            """, org_id, phone)
            return dict(row) if row else None

    async def record_consent_event(self, contact_id, event_type, method,
                                     triggering_message_id=None, matched_text=None, *,
                                     organization_id):
        async with self.scoped_conn(organization_id) as conn:
            row = await conn.fetchrow("""
                INSERT INTO contact_consent_log (id, contact_id, event_type, method,
                                                  triggering_message_id, matched_text)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING *
            """, uuid.uuid4(), contact_id, event_type, method, triggering_message_id, matched_text)
            new_status = "granted" if event_type == "opt_in" else "withdrawn"
            await conn.execute("""
                UPDATE contacts SET consent_status = $1, consent_updated_at = NOW()
                WHERE id = $2 AND organization_id = $3::uuid
            """, new_status, contact_id, organization_id)
            return dict(row)

    async def get_contact_consent(self, contact_id, organization_id) -> str | None:
        async with self.scoped_conn(organization_id) as conn:
            row = await conn.fetchrow(
                "SELECT consent_status FROM contacts WHERE id = $1 AND organization_id = $2::uuid AND deleted_at IS NULL",
                contact_id, organization_id,
            )
            return row["consent_status"] if row else None

    async def mark_ai_disclosure_sent(self, contact_id: uuid.UUID, organization_id) -> bool:
        """Atomicamente segna il contatto come destinatario della disclosure AI.
        Ritorna True solo per il chiamante che vince la race (primo UPDATE);
        False se la disclosure era gia' stata segnata o il contatto non esiste."""
        async with self.scoped_conn(organization_id) as conn:
            row = await conn.fetchrow(
                """UPDATE contacts SET ai_disclosure_sent_at = NOW()
                   WHERE id = $1::uuid AND organization_id = $2::uuid AND ai_disclosure_sent_at IS NULL
                   RETURNING id""",
                contact_id, organization_id,
            )
            return row is not None

    async def get_contacts_by_org(self, organization_id: uuid.UUID | str) -> list[dict]:
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM contacts WHERE organization_id = $1 AND deleted_at IS NULL ORDER BY created_at DESC",
                organization_id,
            )
            return [dict(r) for r in rows]
