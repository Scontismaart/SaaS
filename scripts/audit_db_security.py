"""Audit di sicurezza read-only sul DB Supabase del progetto.

Replica i controlli degli advisor Supabase (security lint) più i check
RLS-specifici del workspace: tabelle senza RLS nello schema esposto,
policy permissive, security definer in public, views senza security_invoker,
grants anomali, stato delle migrazioni del progetto.
"""
import asyncio
import json
import os
import sys

import asyncpg


def db_url() -> str:
    for line in open(".env", encoding="utf-8"):
        if line.strip().startswith("DATABASE_URL"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("DATABASE_URL non trovato in .env")


async def main():
    conn = await asyncpg.connect(
        db_url(), ssl="require", statement_cache_size=0, timeout=30,
    )

    out = {}

    # 1. Tabelle in schema public: RLS abilitata?
    out["tabelle_public_senza_rls"] = await conn.fetch("""
        SELECT c.relname AS tabella, c.relrowsecurity AS rls
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r'
        ORDER BY c.relname
    """)

    # 2. Policy per tabella: comandi, ruoli, permissivita'
    out["policy"] = await conn.fetch("""
        SELECT schemaname, tablename, policyname, permissive, roles, cmd, qual IS NOT NULL AS ha_using, with_check IS NOT NULL AS ha_with_check
        FROM pg_policies
        WHERE schemaname = 'public'
        ORDER BY tablename, policyname
    """)

    # 3. Policy che usano auth.role() (deprecata) o true sempre
    out["policy_rischiose"] = await conn.fetch("""
        SELECT tablename, policyname, cmd, roles::text AS roles, qual, with_check
        FROM pg_policies
        WHERE schemaname = 'public'
          AND (qual = 'true' OR with_check = 'true'
               OR qual LIKE '%auth.role()%' OR with_check LIKE '%auth.role()%')
    """)

    # 4. Tabelle public con RLS ma ZERO policy
    out["tabelle_rls_senza_policy"] = await conn.fetch("""
        SELECT c.relname
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relrowsecurity
          AND NOT EXISTS (
            SELECT 1 FROM pg_policies p
            WHERE p.schemaname = 'public' AND p.tablename = c.relname)
        ORDER BY c.relname
    """)

    # 5. Security definer / security invoker nello schema public
    out["function_security_definer_public"] = await conn.fetch("""
        SELECT p.proname, p.prosecdef, p.proconfig, p.proacl::text
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public' AND p.prokind = 'f'
        ORDER BY p.proname
    """)

    # 6. Views materializzate/normali in public: security_invoker?
    out["views_reloptions"] = await conn.fetch("""
        SELECT c.relname, c.relkind, c.reloptions::text
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('v','m')
    """)

    # 7. Grants su tabelle public ad anon/authenticated
    out["grants_public_tables"] = await conn.fetch("""
        SELECT grantee, table_name, privilege_type
        FROM information_schema.role_table_grants
        WHERE table_schema = 'public'
          AND grantee IN ('anon', 'authenticated', 'PUBLIC')
        ORDER BY table_name, grantee
    """)

    # 8. Stato migrazioni progetto: colonne/valori chiave
    try:
        out["migration_044"] = await conn.fetch("""
            SELECT column_name, data_type, column_default
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name='onboarding_profiles'
            ORDER BY ordinal_position
        """)
    except Exception as e:
        out["migration_044"] = str(e)

    # 9. search_path mutable nelle funzioni (lint advisor)
    out["funzioni_senza_search_path_fixed"] = await conn.fetch("""
        SELECT n.nspname, p.proname, p.proconfig
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname NOT IN ('pg_catalog','information_schema')
          AND (p.proconfig IS NULL OR NOT array_to_string(p.proconfig,',') LIKE '%search_path%')
          AND p.prokind = 'f'
        LIMIT 40
    """)

    # 10. Extension + ruoli bypassrls
    out["bypassrls_roles"] = await conn.fetch("""
        SELECT rolname, rolsuper, rolbypassrls FROM pg_roles
        WHERE rolsuper OR rolbypassrls
    """)

    await conn.close()
    print(json.dumps(out, indent=1, default=str, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
