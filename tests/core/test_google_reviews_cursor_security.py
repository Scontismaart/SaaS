from pathlib import Path

import asyncpg
import pytest


_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION_056 = _ROOT / "src/core/db/migrations/056_google_reviews_cursor.sql"


async def test_google_business_credentials_are_server_only_and_tenant_scoped(
    pg_pool, sample_org, other_org
):
    """Direct Supabase client roles cannot read or mutate either tenant's row.

    Owner/manager are application roles carried by authenticated JWTs, not SQL
    roles. Their feature access remains through the authenticated FastAPI routes
    and the privileged server-side DATABASE_URL pool.
    """
    org_a = sample_org["id"]
    org_b = other_org["id"]

    async with pg_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO public.google_business_credentials
                   (organization_id, access_token, refresh_token, token_expiry,
                    account_name, location_name)
               VALUES
                   ($1, 'encrypted-a', 'encrypted-a-refresh', NOW() + INTERVAL '1 day',
                    'accounts/a', 'accounts/a/locations/1'),
                   ($2, 'encrypted-b', 'encrypted-b-refresh', NOW() + INTERVAL '1 day',
                    'accounts/b', 'accounts/b/locations/2')""",
            org_a,
            org_b,
        )

        table = await conn.fetchrow(
            """SELECT c.relrowsecurity,
                      pg_get_userbyid(c.relowner) AS owner,
                      has_table_privilege('anon', c.oid, 'SELECT') AS anon_select,
                      has_table_privilege('anon', c.oid, 'INSERT') AS anon_insert,
                      has_table_privilege('anon', c.oid, 'UPDATE') AS anon_update,
                      has_table_privilege('anon', c.oid, 'DELETE') AS anon_delete,
                      has_table_privilege('anon', c.oid, 'TRUNCATE') AS anon_truncate,
                      has_table_privilege('anon', c.oid, 'REFERENCES') AS anon_references,
                      has_table_privilege('anon', c.oid, 'TRIGGER') AS anon_trigger,
                      has_table_privilege('authenticated', c.oid, 'SELECT') AS auth_select,
                      has_table_privilege('authenticated', c.oid, 'INSERT') AS auth_insert,
                      has_table_privilege('authenticated', c.oid, 'UPDATE') AS auth_update,
                      has_table_privilege('authenticated', c.oid, 'DELETE') AS auth_delete,
                      has_table_privilege('authenticated', c.oid, 'TRUNCATE') AS auth_truncate,
                      has_table_privilege('authenticated', c.oid, 'REFERENCES') AS auth_references,
                      has_table_privilege('authenticated', c.oid, 'TRIGGER') AS auth_trigger,
                      has_table_privilege(current_user, c.oid, 'SELECT') AS backend_select,
                      has_table_privilege(current_user, c.oid, 'UPDATE') AS backend_update
                 FROM pg_class c
                 JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relname = 'google_business_credentials'"""
        )
        assert table is not None
        assert table["relrowsecurity"] is True
        assert all(
            table[key] is False
            for key in (
                "anon_select", "anon_insert", "anon_update", "anon_delete",
                "anon_truncate", "anon_references", "anon_trigger",
                "auth_select", "auth_insert", "auth_update", "auth_delete",
                "auth_truncate", "auth_references", "auth_trigger",
            )
        )
        assert table["backend_select"] is True
        assert table["backend_update"] is True

        columns = await conn.fetch(
            """SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'google_business_credentials'"""
        )
        for role_name in ("anon", "authenticated"):
            for column in columns:
                for privilege in ("SELECT", "INSERT", "UPDATE", "REFERENCES"):
                    assert await conn.fetchval(
                        "SELECT has_column_privilege($1, $2, $3, $4)",
                        role_name,
                        "public.google_business_credentials",
                        column["column_name"],
                        privilege,
                    ) is False

        policies = await conn.fetch(
            """SELECT policyname, permissive, roles, cmd, qual, with_check
                 FROM pg_policies
                WHERE schemaname = 'public'
                  AND tablename = 'google_business_credentials'"""
        )
        assert not any(p["policyname"] == "google_business_credentials_org_member" for p in policies)
        deny_policy = next(
            p for p in policies
            if p["policyname"] == "google_business_credentials_server_only"
        )
        assert deny_policy["permissive"] == "RESTRICTIVE"
        assert set(deny_policy["roles"]) == {"anon", "authenticated"}
        assert deny_policy["cmd"] == "ALL"
        assert deny_policy["qual"] == "false"
        assert deny_policy["with_check"] == "false"

        # Simulate direct PostgREST SQL as an authenticated tenant user. The
        # stronger ACL denial applies to both own and cross-tenant rows.
        # Supabase grants schema usage to API roles; the local fixture does not.
        await conn.execute("GRANT USAGE ON SCHEMA public TO authenticated")
        await conn.execute("SET ROLE authenticated")
        try:
            for target_org in (org_a, org_b):
                with pytest.raises(asyncpg.InsufficientPrivilegeError):
                    await conn.fetchrow(
                        """SELECT review_page_token
                             FROM public.google_business_credentials
                            WHERE organization_id = $1""",
                        target_org,
                    )
                with pytest.raises(asyncpg.InsufficientPrivilegeError):
                    await conn.execute(
                        """UPDATE public.google_business_credentials
                              SET review_page_token = 'client-forged'
                            WHERE organization_id = $1""",
                        target_org,
                    )
        finally:
            await conn.execute("RESET ROLE")

        # The authorized server-side pool still reads and updates tenant-scoped
        # cursor state, and an update for A leaves B's row unchanged.
        await conn.execute(
            """UPDATE public.google_business_credentials
                  SET review_page_token = 'server-cursor-a',
                      review_page_account_name = 'accounts/a',
                      review_page_location_name = 'accounts/a/locations/1'
                WHERE organization_id = $1""",
            org_a,
        )
        rows = await conn.fetch(
            """SELECT organization_id, review_page_token
                 FROM public.google_business_credentials
                WHERE organization_id = ANY($1::uuid[])""",
            [org_a, org_b],
        )
        cursors = {row["organization_id"]: row["review_page_token"] for row in rows}
        assert cursors == {org_a: "server-cursor-a", org_b: None}


async def test_restrictive_server_only_policy_blocks_accidental_future_grant(
    pg_pool, sample_org
):
    """The restrictive deny still blocks rows if a later permissive policy appears."""
    async with pg_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO public.google_business_credentials
                   (organization_id, access_token, refresh_token, token_expiry,
                    account_name, location_name)
               VALUES ($1, 'encrypted-a', 'encrypted-a-refresh', NOW() + INTERVAL '1 day',
                       'accounts/a', 'accounts/a/locations/1')""",
            sample_org["id"],
        )

        # Simulate a future accidental client grant and permissive policy. The
        # restrictive server-only policy must continue to deny reads and writes.
        tx = conn.transaction()
        await tx.start()
        try:
            await conn.execute("GRANT USAGE ON SCHEMA public TO authenticated")
            await conn.execute(
                "GRANT SELECT, UPDATE ON public.google_business_credentials TO authenticated"
            )
            await conn.execute(
                """CREATE POLICY test_future_permissive_access
                     ON public.google_business_credentials
                     AS PERMISSIVE FOR ALL TO authenticated
                     USING (true) WITH CHECK (true)"""
            )
            await conn.execute("SET LOCAL ROLE authenticated")
            visible = await conn.fetch(
                "SELECT organization_id FROM public.google_business_credentials"
            )
            changed = await conn.fetch(
                """UPDATE public.google_business_credentials
                      SET review_page_token = 'client-forged'
                    RETURNING organization_id"""
            )
            assert visible == []
            assert changed == []
        finally:
            await tx.rollback()


async def test_google_business_cursor_security_migration_is_idempotent(pg_pool):
    """The local fixture applies every migration once; this proves a safe rerun."""
    async with pg_pool.acquire() as conn:
        await conn.execute(_MIGRATION_056.read_text(encoding="utf-8"))
        columns = await conn.fetch(
            """SELECT column_name, data_type, is_nullable, column_default
                 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'google_business_credentials'
                  AND column_name = ANY($1::text[])""",
            [
                "review_page_token",
                "review_page_account_name",
                "review_page_location_name",
            ],
        )
        assert {row["column_name"] for row in columns} == {
            "review_page_token",
            "review_page_account_name",
            "review_page_location_name",
        }
        assert all(row["data_type"] == "text" for row in columns)
        assert all(row["is_nullable"] == "YES" for row in columns)
        assert all(row["column_default"] is None for row in columns)

        policies = await conn.fetch(
            """SELECT policyname FROM pg_policies
                WHERE schemaname = 'public'
                  AND tablename = 'google_business_credentials'"""
        )
        assert [row["policyname"] for row in policies] == [
            "google_business_credentials_server_only"
        ]
