"""Audit DB round 2: dettaglio policy, funzioni definer, migrazioni, ruolo app."""
import asyncio
import json

import asyncpg


def db_url() -> str:
    for line in open(".env", encoding="utf-8"):
        if line.strip().startswith("DATABASE_URL"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("DATABASE_URL non trovato")


async def main():
    conn = await asyncpg.connect(db_url(), ssl="require", statement_cache_size=0, timeout=30)
    out = {}

    # A. Espressioni USING/WITH CHECK di tutte le policy (anti-injection pattern)
    out["policy_expr"] = await conn.fetch("""
        SELECT tablename, policyname, cmd, roles::text AS roles,
               left(qual, 220) AS using_expr, left(with_check, 220) AS with_check_expr
        FROM pg_policies WHERE schemaname = 'public'
        ORDER BY tablename, policyname
    """)

    # B. Security definer: tipo di ritorno (trigger = non invocabile direttamente)
    out["definer_functions"] = await conn.fetch("""
        SELECT p.proname,
               t.typname AS return_type,
               p.prosecdef,
               p.proacl::text AS acl,
               left(p.prosrc, 300) AS body_head
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        JOIN pg_type t ON t.oid = p.prorettype
        WHERE n.nspname = 'public' AND p.prosecdef
        ORDER BY p.proname
    """)

    # C. Migration 044: colonna descrizione su onboarding_profiles
    out["onboarding_profiles_cols"] = await conn.fetch("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name='onboarding_profiles'
        ORDER BY ordinal_position
    """)

    # D. Chi è l'utente di connessione dell'app e che privilegi ha
    out["current_user_info"] = await conn.fetch("""
        SELECT current_user,
               (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) AS super,
               (SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user) AS bypassrls,
               (SELECT rolcreaterole FROM pg_roles WHERE rolname = current_user) AS createrole
    """)

    # E. Funzioni security definer con EXECUTE a PUBLIC (lint advisor)
    out["definer_exec_public"] = await conn.fetch("""
        SELECT p.proname, t.typname AS return_type
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        JOIN pg_type t ON t.oid = p.prorettype
        WHERE n.nspname = 'public' AND p.prosecdef
          AND p.proacl::text LIKE '%=X/postgres%'
    """)

    # F. Tabelle senza colonna organization_id (scope check rapido)
    out["tabelle_senza_org_colonna"] = await conn.fetch("""
        SELECT c.relname AS tabella
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r'
          AND NOT EXISTS (
            SELECT 1 FROM information_schema.columns col
            WHERE col.table_schema='public' AND col.table_name = c.relname
              AND col.column_name IN ('organization_id','org_id'))
        ORDER BY c.relname
    """)

    await conn.close()
    print(json.dumps(out, indent=1, default=str, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
