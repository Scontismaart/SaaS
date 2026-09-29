"""Read-only post-restore gate for Melpis Supabase Auth objects and advisors."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import ssl
import sys
from urllib.error import URLError
from urllib.parse import quote, unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import asyncpg


EXPECTED_FUNCTIONS = {
    "sync_auth_user_profile": "search_path=public, pg_temp",
    "rls_auto_enable": "search_path=pg_catalog",
}
ALLOWED_SECURITY_ADVISORS = {"auth_leaked_password_protection"}
MAIN_PROJECT_REF = "qfxwqfavnuufdfpkhxtj"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise RuntimeError("Supabase advisor endpoint redirected")


def _normalized_dsn(raw: str, project_ref: str) -> str:
    if not re.fullmatch(r"[a-z0-9]{20}", project_ref):
        raise ValueError("invalid project ref")
    if project_ref == MAIN_PROJECT_REF:
        raise ValueError("the restore verifier only accepts non-production projects")
    # The pooler URL can contain reserved characters in a locally injected
    # password. Encode only the credential segment before parsing the target.
    scheme, rest = raw.split("://", 1)
    credentials, location = rest.rsplit("@", 1)
    username, password = credentials.split(":", 1)
    dsn = (
        f"{scheme}://{quote(unquote(username), safe='')}:"
        f"{quote(unquote(password), safe='')}@{location}"
    )
    parsed = urlsplit(dsn)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError("expected a PostgreSQL URL")
    direct = parsed.hostname == f"db.{project_ref}.supabase.co"
    pooler = (
        bool(parsed.hostname)
        and parsed.hostname.endswith(".pooler.supabase.com")
        and bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\." + project_ref, parsed.username or ""))
    )
    if not (direct or pooler):
        raise ValueError("database URL does not match the requested project")
    return dsn


async def verify_catalog(dsn: str, ca_file: str | None = None) -> None:
    conn = await asyncpg.connect(
        dsn=dsn, ssl=ssl.create_default_context(cafile=ca_file), timeout=20
    )
    try:
        async with conn.transaction(readonly=True):
            trigger = await conn.fetchrow(
                """SELECT t.tgenabled::text AS tgenabled, t.tgtype,
                          t.tgqual IS NULL AS unconditional,
                          t.tgnargs = 0 AS no_arguments,
                          t.tgconstraint = 0 AND NOT t.tgdeferrable
                             AND NOT t.tginitdeferred AS immediate,
                          t.tgfoid = to_regprocedure('public.sync_auth_user_profile()')
                             AS expected_function
                   FROM pg_trigger t
                   WHERE t.tgrelid = 'auth.users'::regclass
                     AND t.tgname = 'trg_sync_auth_user'
                     AND NOT t.tgisinternal"""
            )
            if not trigger or trigger["tgenabled"] != "O" or trigger["tgtype"] != 5 or not all(
                trigger[key] for key in ("unconditional", "no_arguments", "immediate", "expected_function")
            ):
                raise RuntimeError("trg_sync_auth_user is missing or differs from migration 002")

            rows = await conn.fetch(
                """SELECT p.proname, pg_get_userbyid(p.proowner) AS owner,
                          p.prosecdef, p.proconfig,
                          has_function_privilege('anon', p.oid, 'EXECUTE') AS anon_execute,
                          has_function_privilege('authenticated', p.oid, 'EXECUTE') AS authenticated_execute,
                          has_function_privilege('service_role', p.oid, 'EXECUTE') AS service_execute,
                          ARRAY(
                            SELECT (CASE WHEN a.grantee = 0 THEN 'PUBLIC'
                                         ELSE pg_get_userbyid(a.grantee) END)
                                   || ':' || a.privilege_type
                                   || ':' || pg_get_userbyid(a.grantor)
                                   || ':' || a.is_grantable::text
                            FROM aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) a
                            ORDER BY 1
                          ) AS grants
                   FROM pg_proc p
                   JOIN pg_namespace n ON n.oid = p.pronamespace
                   WHERE n.nspname = 'public'
                     AND p.proname = ANY($1::text[])
                     AND p.pronargs = 0""",
                list(EXPECTED_FUNCTIONS),
            )
            if {row["proname"] for row in rows} != set(EXPECTED_FUNCTIONS):
                raise RuntimeError("a required function is missing")
            for row in rows:
                expected_path = EXPECTED_FUNCTIONS[row["proname"]]
                if (
                    row["owner"] != "postgres"
                    or not row["prosecdef"]
                    or row["proconfig"] != [expected_path]
                    or row["anon_execute"]
                    or row["authenticated_execute"]
                    or not row["service_execute"]
                    or set(row["grants"]) != {
                        "postgres:EXECUTE:postgres:false",
                        "service_role:EXECUTE:postgres:false",
                    }
                ):
                    raise RuntimeError(f"{row['proname']} owner, search_path or EXECUTE ACL differs from main")
    finally:
        await conn.close()


def verify_advisors(project_ref: str, token: str) -> None:
    request = Request(
        f"https://api.supabase.com/v1/projects/{project_ref}/advisors/security",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with build_opener(_NoRedirect).open(request, timeout=30) as response:
        payload = json.load(response)
    lints = payload.get("lints") if isinstance(payload, dict) else payload
    if not isinstance(lints, list) or any(not isinstance(item, dict) or not isinstance(item.get("name"), str) for item in lints):
        raise RuntimeError("unrecognized Security Advisor response")
    unexpected = {item["name"] for item in lints} - ALLOWED_SECURITY_ADVISORS
    if unexpected:
        raise RuntimeError("Security Advisor findings need review: " + ", ".join(sorted(unexpected)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-ref", required=True)
    args = parser.parse_args()
    db_url = os.environ.get("RESTORE_VERIFY_DATABASE_URL")
    token = os.environ.get("SUPABASE_ACCESS_TOKEN")
    if not db_url or not token:
        print("RESTORE_VERIFY_DATABASE_URL and SUPABASE_ACCESS_TOKEN are required", file=sys.stderr)
        return 1
    try:
        dsn = _normalized_dsn(db_url, args.project_ref)
        asyncio.run(verify_catalog(dsn, os.environ.get("RESTORE_VERIFY_PGSSLROOTCERT")))
        print("RESTORE TRIGGER + FUNCTION ACL: PASS")
        verify_advisors(args.project_ref, token)
        print("RESTORE SECURITY ADVISOR: PASS")
    except (ValueError, RuntimeError) as exc:
        print(f"RESTORE FIDELITY: FAIL ({exc})", file=sys.stderr)
        return 1
    except (asyncpg.PostgresError, OSError, URLError, json.JSONDecodeError) as exc:
        # Library exceptions may contain connection URLs or request headers.
        print(f"RESTORE FIDELITY: FAIL ({type(exc).__name__})", file=sys.stderr)
        return 1
    print("RESTORE FIDELITY: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
