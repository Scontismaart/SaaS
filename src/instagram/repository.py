import os
import uuid

from cryptography.fernet import Fernet

from src.core.db.scoping import TenantScopedRepository, system_scope


class InstagramRepository(TenantScopedRepository):
    """Accesso dati per il canale Instagram. Convive con WhatsAppRepository
    sullo stesso pool asyncpg: tabelle condivise (messages/conversations,
    identita' contatto = external id in contacts.phone_number) piu' la
    tabella dedicata instagram_accounts."""

    def __init__(self, pool):
        self.pool = pool

    @system_scope("tenant-resolution: lookup da webhook Meta (ig_user_id platform-unique)")
    async def get_org_by_instagram_user_id(self, ig_user_id: str):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT o.id as organization_id, o.name, o.business_profile,
                       ia.id as account_id, ia.ig_user_id
                FROM instagram_accounts ia
                JOIN organizations o ON o.id = ia.organization_id
                WHERE ia.ig_user_id = $1
            """, ig_user_id)
            return dict(row) if row else None

    async def get_instagram_account(self, org_id):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, organization_id, ig_user_id, access_token,
                       created_at, updated_at
                FROM instagram_accounts
                WHERE organization_id = $1
            """, org_id)
            return dict(row) if row else None

    @staticmethod
    def encrypt_token(plaintext: str) -> str:
        key = os.environ.get("ENCRYPTION_KEY")
        if not key:
            raise RuntimeError("ENCRYPTION_KEY not set")
        return Fernet(key.encode()).encrypt(plaintext.encode()).decode()

    async def save_instagram_account(self, org_id, ig_user_id: str, access_token: str):
        encrypted = self.encrypt_token(access_token)
        async with self.pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT id FROM instagram_accounts WHERE organization_id = $1", org_id
            )
            if existing:
                row = await conn.fetchrow("""
                    UPDATE instagram_accounts
                    SET ig_user_id = $2, access_token = $3, updated_at = NOW()
                    WHERE organization_id = $1
                    RETURNING *
                """, org_id, ig_user_id, encrypted)
            else:
                row = await conn.fetchrow("""
                    INSERT INTO instagram_accounts (id, organization_id, ig_user_id, access_token)
                    VALUES ($1, $2, $3, $4)
                    RETURNING *
                """, uuid.uuid4(), org_id, ig_user_id, encrypted)
            return dict(row)

    async def delete_instagram_account(self, org_id) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM instagram_accounts WHERE organization_id = $1", org_id
            )
            return result.endswith(" 1")
