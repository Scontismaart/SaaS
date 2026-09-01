"""Applica le migration 044 e 045 sul DB Supabase e verifica l'esito (idempotenti)."""
import asyncio
import sys

import asyncpg


def db_url() -> str:
    for line in open(".env", encoding="utf-8"):
        if line.strip().startswith("DATABASE_URL"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("DATABASE_URL non trovato")


async def apply_and_verify():
    conn = await asyncpg.connect(db_url(), ssl="require", statement_cache_size=0)

    # ── Migration 044 ──────────────────────────────────────────
    await conn.execute("ALTER TABLE onboarding_profiles ADD COLUMN IF NOT EXISTS descrizione TEXT NOT NULL DEFAULT '';")
    col = await conn.fetchval("""
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='public' AND table_name='onboarding_profiles' AND column_name='descrizione'
    """)
    print("044 descrizione colonna presente:", bool(col))

    # ── Migration 045 ──────────────────────────────────────────
    await conn.execute("REVOKE TRUNCATE ON ALL TABLES IN SCHEMA public FROM anon, authenticated;")
    await conn.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE TRUNCATE ON TABLES FROM anon, authenticated;")
    await conn.execute("DROP POLICY IF EXISTS outbound_dedup_deny_all ON outbound_dedup;")
    await conn.execute("""
        CREATE POLICY outbound_dedup_deny_all ON outbound_dedup
            FOR ALL TO anon, authenticated
            USING (false) WITH CHECK (false)
    """)

    # ── Verifiche ──────────────────────────────────────────────
    trunc = await conn.fetch("""
        SELECT grantee, table_name FROM information_schema.role_table_grants
        WHERE table_schema='public' AND privilege_type='TRUNCATE'
          AND grantee IN ('anon','authenticated') LIMIT 5
    """)
    print("045 grant TRUNCATE residui anon/authenticated:", len(trunc))

    pol = await conn.fetchrow("""
        SELECT policyname, cmd, roles::text AS roles
        FROM pg_policies
        WHERE schemaname='public' AND tablename='outbound_dedup'
    """)
    print("045 policy outbound_dedup:", dict(pol) if pol else "ASSENTE")

    # smoke: il default '' è effettivamente applicato alle righe esistenti
    n = await conn.fetchval("SELECT count(*) FROM onboarding_profiles WHERE descrizione = ''")
    tot = await conn.fetchval("SELECT count(*) FROM onboarding_profiles")
    print(f"righe onboarding_profiles con default '': {n}/{tot}")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(apply_and_verify())
