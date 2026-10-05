"""Test per il check CI del tenant scoping (solo AST, nessun DB)."""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

_SCRIPT_PATH = REPO_ROOT / "scripts" / "check_tenant_scoping.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("check_tenant_scoping", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_tenant_scoping = _load_script()
ALLOWLISTED_SQL_FINGERPRINTS = check_tenant_scoping.ALLOWLISTED_SQL_FINGERPRINTS
DEFAULT_TARGETS = check_tenant_scoping.DEFAULT_TARGETS
SYSTEM_SCOPE_ALLOWLIST = check_tenant_scoping.SYSTEM_SCOPE_ALLOWLIST
SYSTEM_SCOPE_SQL_FINGERPRINTS = check_tenant_scoping.SYSTEM_SCOPE_SQL_FINGERPRINTS
sql_fingerprint = check_tenant_scoping.sql_fingerprint
check_file = check_tenant_scoping.check_file
main = check_tenant_scoping.main

CLEAN_SOURCE = '''\
async def fetch_bookings(conn, org_id):
    return await conn.fetch(
        "SELECT * FROM bookings "
        "WHERE organization_id = $1",
        org_id,
    )


def health_probe(conn):
    return conn.fetchval("ping")
'''

BAD_SOURCE = '''\
async def fetch_booking_by_id(conn, booking_id):
    return await conn.fetchrow(
        "SELECT * FROM bookings WHERE id = $1",
        booking_id,
    )
'''


def _write_module(tmp_path: Path, code: str, name: str = "repo_mod.py") -> Path:
    path = tmp_path / name
    path.write_text(code, encoding="utf-8")
    return path


def test_clean_file_has_no_violations(tmp_path):
    path = _write_module(tmp_path, CLEAN_SOURCE)
    assert check_file(path) == []


def test_unscoped_select_on_tenant_table_is_flagged(tmp_path):
    path = _write_module(tmp_path, BAD_SOURCE)
    violations = check_file(path)
    assert len(violations) == 1
    label, fn_name, lineno, detail, sql = violations[0]
    assert label.endswith("repo_mod.py")
    assert fn_name == "fetch_booking_by_id"
    assert lineno == 1
    assert "bookings" in detail
    assert "bookings" in sql
    assert sql.startswith("SELECT * FROM bookings")


@pytest.mark.parametrize(
    "sql",
    [
        "TRUNCATE TABLE bookings",
        "ALTER TABLE bookings ADD COLUMN note text",
        "DROP TABLE bookings",
        "COPY bookings TO STDOUT",
        "LOCK TABLE bookings IN ACCESS EXCLUSIVE MODE",
    ],
)
def test_non_dml_operations_on_tenant_tables_are_not_ignored(tmp_path, sql):
    path = _write_module(
        tmp_path,
        f"async def unsafe(conn):\n    await conn.execute({sql!r})\n",
    )
    violations = check_file(path)
    assert len(violations) == 1
    assert "bookings" in violations[0][3]


def test_static_scanner_rejects_admin_operation_without_relation_extraction(tmp_path):
    path = _write_module(
        tmp_path,
        'async def unsafe(conn):\n'
        '    await conn.execute("GRANT SELECT ON TABLE bookings TO app_user")\n',
    )
    violations = check_file(path)
    assert len(violations) == 1
    assert violations[0][3] == "non-DML operation"


def test_parent_derived_query_requires_verified_parent_scope(tmp_path):
    unsafe = _write_module(
        tmp_path,
        'async def load(conn):\n'
        '    return await conn.fetch("SELECT * FROM message_delivery_attempts WHERE status = \'pending\'")\n',
        name="unsafe_parent.py",
    )
    safe = _write_module(
        tmp_path,
        'async def load(conn, org_id):\n'
        '    return await conn.fetch("SELECT a.* FROM message_delivery_attempts a JOIN messages m ON a.message_id = m.id WHERE m.organization_id = $1", org_id)\n',
        name="safe_parent.py",
    )
    assert len(check_file(unsafe)) == 1
    assert check_file(safe) == []


def test_system_scope_decorator_alone_does_not_skip_function(tmp_path):
    source = (
        "from src.core.db.scoping import system_scope\n"
        "\n"
        "\n"
        '@system_scope("worker globale di retention")\n'
        "async def purge_old_messages(conn):\n"
        '    await conn.execute("DELETE FROM messages WHERE created_at < now()")\n'
    )
    path = _write_module(tmp_path, source)
    violations = check_file(path)
    assert len(violations) == 1
    assert violations[0][1] == "purge_old_messages"


def test_reviewed_system_scope_exception_applies_to_one_literal_only(tmp_path, monkeypatch):
    authorized_sql = "DELETE FROM messages WHERE created_at < now()"
    source = (
        "from src.core.db.scoping import system_scope\n"
        '@system_scope("worker globale di retention")\n'
        "async def purge_old_messages(conn):\n"
        f"    await conn.execute({authorized_sql!r})\n"
        '    await conn.execute("DELETE FROM messages WHERE status = \'failed\'")\n'
    )
    path = _write_module(tmp_path, source)
    key = f"{check_tenant_scoping._path_label(path)}::purge_old_messages"
    monkeypatch.setitem(SYSTEM_SCOPE_ALLOWLIST, key, "reviewed test worker")
    monkeypatch.setitem(
        SYSTEM_SCOPE_SQL_FINGERPRINTS,
        (key, sql_fingerprint(authorized_sql)),
        "exact reviewed query",
    )
    violations = check_file(path)
    assert len(violations) == 1
    assert "status" in violations[0][4]


def test_bare_system_scope_name_does_not_skip_function(tmp_path):
    source = (
        "@system_scope\n"
        "async def sweep_event_log(conn):\n"
        '    await conn.execute("DELETE FROM event_log")\n'
    )
    path = _write_module(tmp_path, source)
    assert len(check_file(path)) == 1


def test_attribute_form_system_scope_does_not_skip_function(tmp_path):
    source = (
        "from src.core.db import scoping as db\n"
        "\n"
        "\n"
        '@db.system_scope("worker globale di retention")\n'
        "async def purge_old_messages(conn):\n"
        '    await conn.execute("DELETE FROM messages WHERE created_at < now()")\n'
    )
    path = _write_module(tmp_path, source)
    assert len(check_file(path)) == 1


def test_query_allowlist_does_not_skip_other_literals_in_function(tmp_path, monkeypatch):
    authorized_sql = (
        "SELECT organization_id FROM organization_memberships "
        "WHERE auth_user_id = $1"
    )
    source = (
        "async def memberships(conn, user_id):\n"
        f"    await conn.fetch({authorized_sql!r}, user_id)\n"
        '    await conn.execute("DELETE FROM messages WHERE status = \'failed\'")\n'
    )
    path = _write_module(tmp_path, source)
    key = f"{check_tenant_scoping._path_label(path)}::memberships"
    monkeypatch.setitem(
        ALLOWLISTED_SQL_FINGERPRINTS,
        (key, sql_fingerprint(authorized_sql)),
        "verified principal membership query",
    )
    violations = check_file(path)
    assert len(violations) == 1
    assert violations[0][1] == "memberships"
    assert "messages" in violations[0][3]


def test_infra_and_root_tables_are_not_flagged(tmp_path):
    source = (
        "async def ping(conn):\n"
        '    return await conn.fetchval("SELECT 1")\n'
        "\n"
        "\n"
        "async def rename_org(conn, name, org_pk):\n"
        "    await conn.execute(\n"
        '        "UPDATE organizations SET name = $1 WHERE id = $2",\n'
        "        name,\n"
        "        org_pk,\n"
        "    )\n"
    )
    path = _write_module(tmp_path, source)
    assert check_file(path) == []


def test_dynamic_table_identifier_is_flagged(tmp_path):
    source = (
        "def load_rows(table):\n"
        '    return f"SELECT * FROM {table}"\n'
    )
    path = _write_module(tmp_path, source)
    violations = check_file(path)
    assert len(violations) == 1
    _, fn_name, lineno, detail, sql = violations[0]
    assert fn_name == "load_rows"
    assert lineno == 1
    assert detail == "dynamic table identifier"


def test_raw_concatenated_dynamic_table_prefix_is_flagged(tmp_path):
    source = (
        'def load_rows(conn, table):\n'
        '    sql = "SELECT * FROM " + table\n'
        '    return conn.fetch(sql)\n'
    )
    path = _write_module(tmp_path, source)
    violations = check_file(path)
    assert len(violations) == 1
    assert violations[0][3] == "dynamic table identifier"


@pytest.mark.parametrize(
    "expression",
    [
        '"SELECT * " + "FROM " + table',
        '"SELECT * " + "FROM {}".format(table)',
    ],
)
def test_dynamic_table_identifier_in_composed_fragments_is_flagged(tmp_path, expression):
    source = (
        "def load_rows(conn, table):\n"
        f"    sql = {expression}\n"
        "    return conn.fetch(sql)\n"
    )
    violations = check_file(_write_module(tmp_path, source))
    assert len(violations) == 1
    assert violations[0][3] == "dynamic table identifier"


def test_dynamic_table_identifier_in_local_string_fragments_is_flagged(tmp_path):
    source = (
        "def load_rows(conn, table):\n"
        '    select_part = "SELECT * "\n'
        '    from_part = "FROM "\n'
        "    sql = select_part + from_part + table\n"
        "    return conn.fetch(sql)\n"
    )
    violations = check_file(_write_module(tmp_path, source))
    assert len(violations) == 1
    assert violations[0][3] == "dynamic table identifier"


def test_reassigned_local_relation_fragment_is_not_treated_as_static(tmp_path):
    source = (
        "def load_rows(conn, table, dynamic_from):\n"
        '    from_part = "FROM "\n'
        "    from_part = dynamic_from\n"
        '    sql = "SELECT * " + from_part + table\n'
        "    return conn.fetch(sql)\n"
    )
    violations = check_file(_write_module(tmp_path, source))
    assert len(violations) == 1
    assert violations[0][3] == "dynamic table identifier"


@pytest.mark.parametrize(
    "source",
    [
        'MODULE_QUERY = "SELECT * FROM contacts"\n'
        "async def load(conn):\n    await conn.fetch(MODULE_QUERY)\n",
        "async def load(conn):\n"
        '    query = "SELECT * FROM contacts"\n'
        "    await conn.fetch(query)\n",
        "async def load(conn):\n"
        '    await conn.fetch(" ".join(["SELECT *", "FROM contacts"]))\n',
        "async def build_query():\n"
        '    return "SELECT * FROM contacts"\n'
        "async def load(conn):\n    await conn.fetch(build_query())\n",
    ],
)
def test_sql_sink_flags_module_local_join_and_helper_query_sources(tmp_path, source):
    violations = check_file(_write_module(tmp_path, source))
    assert violations
    assert any("contacts" in detail or "unresolved SQL sink" in detail for _, _, _, detail, _ in violations)


def test_sql_sink_keeps_resolved_scoped_module_and_join_queries(tmp_path):
    source = (
        'MODULE_QUERY = "SELECT * FROM contacts WHERE organization_id = $1"\n'
        "async def load(conn, org):\n"
        "    await conn.fetch(MODULE_QUERY, org)\n"
        "    await conn.fetch(\" \".join([\"SELECT * FROM contacts\", \"WHERE organization_id = $1\"]), org)\n"
    )
    assert check_file(_write_module(tmp_path, source)) == []


def test_unresolved_sql_sink_fails_closed_but_http_fetcher_is_ignored(tmp_path):
    source = (
        "async def load(conn, payload_fetcher, query):\n"
        "    await conn.fetch(query)\n"
        "    await payload_fetcher.fetch(query)\n"
    )
    violations = check_file(_write_module(tmp_path, source))
    assert len(violations) == 1
    assert violations[0][3] == "unresolved SQL sink expression"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id FROM contacts WHERE NOT (organization_id = $1)",
        "SELECT id FROM contacts WHERE organization_id = $1 IS FALSE",
        "SELECT id FROM contacts WHERE CASE WHEN organization_id = $1 THEN FALSE ELSE TRUE END",
        "UPDATE contacts SET phone_number = '+390000000000' "
        "WHERE NOT (organization_id = $1)",
    ],
)
def test_scanner_rejects_negative_tenant_predicates(tmp_path, sql):
    source = f"async def load(conn, org):\n    await conn.fetch({sql!r}, org)\n"
    violations = check_file(_write_module(tmp_path, source))
    assert len(violations) == 1
    assert "contacts" in violations[0][3]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT m.id FROM contacts c, messages m WHERE c.organization_id = $1",
        "SELECT m.id FROM organizations o, messages m WHERE o.id = $1",
        "SELECT m.id FROM organizations o JOIN contacts c ON c.organization_id = $1, messages m WHERE c.organization_id = $1",
    ],
)
def test_scanner_rejects_uninventoried_comma_join(tmp_path, sql):
    source = f"async def load(conn, org):\n    await conn.fetch({sql!r}, org)\n"
    violations = check_file(_write_module(tmp_path, source))
    assert len(violations) == 1
    assert violations[0][3] in {"contacts", "unparseable SQL literal"}


@pytest.mark.parametrize("quoted_keyword", ["select", "update", "where"])
def test_scanner_rejects_comma_join_hidden_by_quoted_keyword(tmp_path, quoted_keyword):
    sql = (
        "SELECT m.id FROM organizations o JOIN ("
        f'SELECT id, organization_id, organization_id AS "{quoted_keyword}" FROM contacts '
        "WHERE organization_id = $1) c "
        "ON c.organization_id = $1 AND c.organization_id = o.id "
        f'AND c."{quoted_keyword}" = o.id, messages m '
        "WHERE c.organization_id = $1"
    )
    source = f"async def load(conn, org):\n    await conn.fetch({sql!r}, org)\n"
    violations = check_file(_write_module(tmp_path, source))
    assert violations


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT \"C\".id, \"C\".organization_id FROM contacts c JOIN contacts \"C\" ON TRUE WHERE c.organization_id = $1",
        "SELECT c.id, c.organization_id FROM organizations o RIGHT JOIN contacts c ON c.organization_id = $1",
        "SELECT c.id, c.organization_id FROM organizations o RIGHT OUTER JOIN contacts c ON c.organization_id = $1",
        "SELECT c.id, c.organization_id FROM organizations o FULL JOIN contacts c ON o.id = c.organization_id AND c.organization_id = $1",
        "SELECT l.id, c.organization_id FROM contact_consent_log l LEFT JOIN contacts c ON l.contact_id = c.id AND c.organization_id = $1",
        "SELECT c.id, c.organization_id FROM contacts c LEFT JOIN organizations o ON c.organization_id = $1",
    ],
)
def test_scanner_final_microfix_rejects_alias_collision_and_preserved_outer_rows(tmp_path, sql):
    source = f"async def load(conn, org):\n    await conn.fetch({sql!r}, org)\n"
    assert check_file(_write_module(tmp_path, source))


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT \"C\".id, \"C\".organization_id FROM contacts \"C\" WHERE \"C\".organization_id = $1",
        "SELECT c.id, c.organization_id FROM contacts c WHERE c.organization_id = $1",
        "SELECT \"c\".id, \"c\".organization_id FROM contacts C WHERE \"c\".organization_id = $1",
        "SELECT \"where\".id, \"where\".organization_id FROM contacts \"where\" WHERE \"where\".organization_id = $1",
        "SELECT \"C\"\"alias\".id, \"C\"\"alias\".organization_id FROM contacts \"C\"\"alias\" WHERE \"C\"\"alias\".organization_id = $1",
        "SELECT c.id, c.organization_id FROM organizations o INNER JOIN contacts c ON c.organization_id = $1",
        "SELECT c.id, c.organization_id FROM organizations o LEFT JOIN contacts c ON o.id = c.organization_id WHERE c.organization_id = $1",
        "SELECT c.id, c.organization_id FROM organizations o RIGHT OUTER JOIN contacts c ON o.id = c.organization_id WHERE c.organization_id = $1",
        "SELECT c.id, c.organization_id FROM organizations o LEFT JOIN contacts c ON o.id = c.organization_id AND c.organization_id = $1 WHERE c.id IS NOT NULL",
        "SELECT l.id, c.organization_id FROM contact_consent_log l INNER JOIN contacts c ON l.contact_id = c.id AND c.organization_id = $1",
        "SELECT l.id, c.organization_id FROM contact_consent_log l LEFT JOIN contacts c ON TRUE WHERE l.contact_id = c.id AND c.organization_id = $1",
    ],
)
def test_scanner_final_microfix_accepts_exact_alias_and_effective_join_scope(tmp_path, sql):
    source = f"async def load(conn, org):\n    await conn.fetch({sql!r}, org)\n"
    assert check_file(_write_module(tmp_path, source)) == []


def test_scanner_accepts_quoted_keyword_alias_without_comma_join(tmp_path):
    sql = 'SELECT c.id AS "select" FROM contacts c WHERE c.organization_id = $1'
    source = f"async def load(conn, org):\n    await conn.fetch({sql!r}, org)\n"
    assert check_file(_write_module(tmp_path, source)) == []


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT l.id FROM contact_consent_log l JOIN contacts c "
        "ON NOT (l.contact_id = c.id) WHERE c.organization_id = $1",
        "SELECT l.id FROM contact_consent_log l JOIN contacts c "
        "ON l.contact_id <> c.id WHERE c.organization_id = $1",
    ],
)
def test_scanner_rejects_negated_parent_relations(tmp_path, sql):
    source = f"async def load(conn, org):\n    await conn.fetch({sql!r}, org)\n"
    violations = check_file(_write_module(tmp_path, source))
    assert violations
    assert any("contact_consent_log" in item[3] for item in violations)


@pytest.mark.parametrize(
    "expression",
    [
        '"SELECT * FROM bookings WHERE organization_id = $1 " + suffix',
        'f"SELECT * FROM bookings WHERE organization_id = $1 {suffix}"',
        '"SELECT * FROM bookings WHERE organization_id = $1 {}".format(suffix)',
        '"SELECT * FROM bookings WHERE organization_id = $1 %s" % suffix',
    ],
)
def test_unknown_sql_suffix_cannot_bypass_static_scope(tmp_path, expression):
    source = (
        "async def load_rows(conn, org_id, suffix):\n"
        f"    sql = {expression}\n"
        "    return await conn.fetch(sql, org_id)\n"
    )
    violations = check_file(_write_module(tmp_path, source))
    assert len(violations) == 1
    assert "dynamic SQL interpolation" in violations[0][3]
    assert "bookings" in violations[0][3]


def test_unknown_control_flow_assignment_invalidates_local_fragment(tmp_path):
    source = (
        "def load_rows(conn, table, dynamic_from, condition):\n"
        '    from_part = "FROM "\n'
        "    if condition:\n"
        "        from_part = dynamic_from\n"
        '    sql = "SELECT * " + from_part + table\n'
        "    return conn.fetch(sql)\n"
    )
    violations = check_file(_write_module(tmp_path, source))
    assert len(violations) == 1
    assert violations[0][3] == "dynamic table identifier"


def test_static_composed_query_is_still_analyzed_as_sql(tmp_path):
    source = (
        "async def load_rows(conn, org_id):\n"
        '    sql = "SELECT * " + "FROM bookings WHERE organization_id = $1"\n'
        "    return await conn.fetch(sql, org_id)\n"
    )
    assert check_file(_write_module(tmp_path, source)) == []


@pytest.mark.parametrize(
    "statement",
    [
        'sql = "SELECT * FROM {} WHERE organization_id = $1".format(table)',
        'sql = "SELECT * FROM %s WHERE organization_id = $1" % table',
        'sql = f"SELECT * FROM public.{table} WHERE organization_id = $1"',
    ],
)
def test_formatted_and_percent_dynamic_table_identifiers_are_flagged(tmp_path, statement):
    source = f"def load_rows(conn, table):\n    {statement}\n    return conn.fetch(sql)\n"
    violations = check_file(_write_module(tmp_path, source))
    assert len(violations) == 1
    assert violations[0][3] == "dynamic table identifier"


def test_static_scanner_rejects_unscoped_upsert_conflict_target(tmp_path):
    source = (
        "async def upsert(conn, org_id, booking_id):\n"
        '    await conn.execute("INSERT INTO bookings (id, organization_id) '
        'VALUES ($1, $2) ON CONFLICT (id) DO UPDATE SET id = EXCLUDED.id", '
        "booking_id, org_id)\n"
    )
    violations = check_file(_write_module(tmp_path, source))
    assert len(violations) == 1
    assert "bookings" in violations[0][3]


def test_static_scanner_rejects_organization_id_mutation(tmp_path):
    source = (
        "async def move_booking(conn, new_org, old_org, booking_id):\n"
        '    await conn.execute("UPDATE bookings SET organization_id = $1 '
        'WHERE organization_id = $2 AND id = $3", new_org, old_org, booking_id)\n'
    )
    violations = check_file(_write_module(tmp_path, source))
    assert len(violations) == 1
    assert "bookings" in violations[0][3]


def test_static_scanner_still_accepts_organization_scoped_upsert(tmp_path):
    sql = (
        "INSERT INTO conversations (id, organization_id, contact_id, canale) "
        "VALUES ($1, $2, $3, $4) ON CONFLICT (organization_id, contact_id) "
        "DO UPDATE SET last_message_at = NOW()"
    )
    source = f"async def upsert(conn, org_id, row):\n    await conn.execute({sql!r}, row, org_id)\n"
    assert check_file(_write_module(tmp_path, source)) == []


def test_static_scanner_accepts_global_conflict_key_with_org_guard(tmp_path):
    sql = (
        "INSERT INTO outbound_dedup (message_id, organization_id, response_text) "
        "VALUES ($1, $2, $3) ON CONFLICT (message_id) DO UPDATE "
        "SET response_text = EXCLUDED.response_text WHERE "
        "outbound_dedup.organization_id = EXCLUDED.organization_id"
    )
    source = f"async def upsert(conn, message, org, response):\n    await conn.execute({sql!r}, message, org, response)\n"
    assert check_file(_write_module(tmp_path, source)) == []


def test_static_scanner_rejects_org_guard_hidden_by_or(tmp_path):
    sql = (
        "INSERT INTO outbound_dedup (message_id, organization_id, response_text) "
        "VALUES ($1, $2, $3) ON CONFLICT (message_id) DO UPDATE "
        "SET response_text = EXCLUDED.response_text WHERE "
        "outbound_dedup.organization_id = EXCLUDED.organization_id OR TRUE"
    )
    source = f"async def upsert(conn, message, org, response):\n    await conn.execute({sql!r}, message, org, response)\n"
    assert len(check_file(_write_module(tmp_path, source))) == 1


def test_docstring_with_sql_words_is_not_a_query_literal(tmp_path):
    source = (
        'def explain(conn):\n'
        '    """This method updates documentation about SQL and DELETE syntax."""\n'
        '    return None\n'
    )
    assert check_file(_write_module(tmp_path, source)) == []


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id FROM bookings WHERE id = $1 -- organization_id = $2",
        "SELECT id FROM bookings WHERE note = 'organization_id = $1'",
        "SELECT organization_id FROM bookings WHERE id = $1",
        "SELECT * FROM bookings WHERE organization_id IS NOT NULL",
        "SELECT * FROM bookings WHERE organization_id = $1 OR TRUE",
        "SELECT * FROM bookings WHERE organization_id = $1 OR $2 IS NULL",
        "SELECT * FROM bookings WHERE organization_id = $1 OR id = $2",
        "SELECT * FROM bookings WHERE organization_id = $1 AND id = $2 OR active",
        "SELECT * FROM bookings WHERE (organization_id = $1 OR id = $2) AND active",
    ],
)
def test_comment_projection_and_obvious_non_scope_do_not_satisfy_guard(tmp_path, sql):
    source = f"async def load(conn):\n    return await conn.fetch({sql!r})\n"
    path = _write_module(tmp_path, source)
    assert len(check_file(path)) == 1


def test_insert_requires_organization_id_in_target_columns(tmp_path):
    scoped = _write_module(
        tmp_path,
        'async def create(conn, org_id):\n'
        '    await conn.execute("INSERT INTO bookings (id, organization_id) VALUES ($1, $2)", org_id)\n',
        name="scoped_insert.py",
    )
    unscoped = _write_module(
        tmp_path,
        'async def create(conn):\n'
        '    await conn.execute("INSERT INTO bookings (id) VALUES ($1) -- organization_id in comment")\n',
        name="unscoped_insert.py",
    )
    assert check_file(scoped) == []
    assert len(check_file(unscoped)) == 1


def test_tenant_conjunct_allows_unrelated_parenthesized_or(tmp_path):
    source = (
        "async def load(conn, org_id, status_a, status_b):\n"
        '    return await conn.fetch("SELECT * FROM bookings WHERE organization_id = $1 AND (status = $2 OR status = $3)", org_id, status_a, status_b)\n'
    )
    path = _write_module(tmp_path, source)
    assert check_file(path) == []


def test_default_targets_cover_every_python_source_module():
    expected = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "src").rglob("*.py")
    }
    assert set(DEFAULT_TARGETS) == expected


@pytest.mark.parametrize(
    "literal",
    [
        '"reservations/update"',
        '"Missing waba_id for template status update"',
        '"update onboarding_profiles orari failed: %s"',
    ],
)
def test_non_sql_text_with_sql_words_is_ignored(tmp_path, literal):
    path = _write_module(
        tmp_path,
        f"def message():\n    return {literal}\n",
    )
    assert check_file(path) == []


def test_joinedstr_only_static_parts_count(tmp_path):
    source = (
        "async def count_open(conn, org_id):\n"
        "    return await conn.fetchval(\n"
        '        "SELECT count(*) FROM conversations WHERE organization_id = $1", org_id\n'
        "    )\n"
        "\n"
        "\n"
        "async def count_all(conn, limit):\n"
        "    return await conn.fetchval(\n"
        '        f"SELECT count(*) FROM conversations LIMIT {limit}"\n'
        "    )\n"
    )
    path = _write_module(tmp_path, source)
    violations = check_file(path)
    assert len(violations) == 1
    _, fn_name, _, detail, sql = violations[0]
    assert fn_name == "count_all"
    assert "conversations" in detail
    assert detail != "dynamic table identifier"
    assert "conversations" in sql


def test_fstring_interpolation_is_not_a_bound_tenant_filter(tmp_path):
    source = (
        "async def count_open(conn, org_id):\n"
        "    return await conn.fetchval(\n"
        '        f"SELECT count(*) FROM conversations WHERE organization_id = {org_id}"\n'
        "    )\n"
    )
    path = _write_module(tmp_path, source)
    violations = check_file(path)
    assert len(violations) == 1
    assert violations[0][1] == "count_open"


def test_nested_function_reported_once_with_innermost_name(tmp_path):
    source = (
        "def weekly_cleanup():\n"
        "    async def run(conn):\n"
        '        await conn.execute("DELETE FROM faq_cache WHERE stale")\n'
        "\n"
        "    return run\n"
    )
    path = _write_module(tmp_path, source)
    violations = check_file(path)
    assert len(violations) == 1
    _, fn_name, _, detail, _sql = violations[0]
    assert fn_name == "run"
    assert "faq_cache" in detail


def test_main_returns_1_for_bad_file_and_0_for_clean(tmp_path):
    bad = _write_module(tmp_path, BAD_SOURCE, name="bad.py")
    clean = _write_module(tmp_path, CLEAN_SOURCE, name="clean.py")
    assert main(["check_tenant_scoping.py", str(bad)]) == 1
    assert main(["check_tenant_scoping.py", str(clean)]) == 0


def test_e2e_subprocess_bad_file_exits_1(tmp_path):
    bad = _write_module(tmp_path, BAD_SOURCE)
    proc = subprocess.run(
        [sys.executable, "scripts/check_tenant_scoping.py", str(bad)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 1
    assert "VIOLAZIONI" in proc.stdout
    assert "repo_mod.py" in proc.stdout


def test_e2e_subprocess_clean_file_exits_0(tmp_path):
    clean = _write_module(tmp_path, CLEAN_SOURCE)
    proc = subprocess.run(
        [sys.executable, "scripts/check_tenant_scoping.py", str(clean)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0
    assert "TENANT SCOPING CHECK: OK" in proc.stdout
