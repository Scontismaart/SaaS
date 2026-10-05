"""Unit test delle primitive di tenant scoping (nessun DB richiesto).

Copre: estrazione tabelle dal SQL finale (copre anche SQL costruito
dinamicamente), check fail-closed assert_org_scoped, proxy ScopedConnection
su mock conn, mixin TenantScopedRepository e decorator system_scope."""
import uuid
from contextlib import asynccontextmanager

import pytest

from src.core.db.scoping import (
    INDIRECT_SCOPED_TABLES,
    TENANT_SCOPED_TABLES,
    MissingOrganizationIdError,
    ScopedConnection,
    TenantScopedRepository,
    TenantScopeViolation,
    assert_org_scoped,
    extract_tables,
    system_scope,
)

ORG_ID = uuid.uuid4()


class RecordingConn:
    """Stub asyncpg conn: registra le chiamate, non tocca nessun database."""

    def __init__(self):
        self.calls = []
        self.tx_sentinel = object()

    async def fetch(self, sql, *args, **kwargs):
        self.calls.append(("fetch", sql, args))
        return []

    async def fetchrow(self, sql, *args, **kwargs):
        self.calls.append(("fetchrow", sql, args))

    async def fetchval(self, sql, *args, **kwargs):
        self.calls.append(("fetchval", sql, args))

    async def execute(self, sql, *args, **kwargs):
        self.calls.append(("execute", sql, args))
        return "OK"

    async def executemany(self, sql, args_seq, *args, **kwargs):
        self.calls.append(("executemany", sql, list(args_seq)))

    def transaction(self):
        return self.tx_sentinel


class StubPool:
    """Dummy pool: acquire() e' un async context manager che ritorna il conn."""

    def __init__(self, conn):
        self.conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


class RepoWithStubPool(TenantScopedRepository):
    def __init__(self, pool):
        self.pool = pool


# ── Costanti ────────────────────────────────────────────────────


def test_tenant_scoped_tables_is_frozenset_with_bookings():
    assert isinstance(TENANT_SCOPED_TABLES, frozenset)
    assert "bookings" in TENANT_SCOPED_TABLES
    assert "messages" in TENANT_SCOPED_TABLES
    assert "organizations" not in TENANT_SCOPED_TABLES


def test_indirect_scoped_tables_excluded_from_direct_check():
    assert isinstance(INDIRECT_SCOPED_TABLES, frozenset)
    assert "message_delivery_attempts" in INDIRECT_SCOPED_TABLES
    assert "contact_consent_log" in INDIRECT_SCOPED_TABLES
    assert not (INDIRECT_SCOPED_TABLES & TENANT_SCOPED_TABLES)


# ── extract_tables ──────────────────────────────────────────────


def test_extract_tables_covers_from_join_into_update():
    sql = """
        INSERT INTO outbound_dedup (message_id)
        SELECT m.id FROM messages m
        JOIN conversations c ON c.id = m.conversation_id
        UPDATE contacts SET x = 1
    """
    assert extract_tables(sql) == {
        "outbound_dedup", "messages", "conversations", "contacts",
    }


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM public.bookings",
        'SELECT * FROM "bookings"',
        "DELETE FROM ONLY bookings WHERE id = $1",
    ],
)
def test_extract_tables_supports_schema_quotes_and_only(sql):
    assert extract_tables(sql) == {"bookings"}


# ── assert_org_scoped ───────────────────────────────────────────


def test_accepts_scoped_select():
    assert_org_scoped("SELECT * FROM bookings WHERE organization_id = $1")


def test_rejects_unscoped_select():
    with pytest.raises(TenantScopeViolation):
        assert_org_scoped("SELECT * FROM bookings WHERE id = $1")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM bookings WHERE id = $1 -- organization_id = $2",
        "SELECT organization_id FROM bookings WHERE id = $1",
        "SELECT * FROM bookings WHERE organization_id = $1 OR id = $2",
        "SELECT * FROM bookings WHERE (organization_id = $1 OR id = $2) AND active",
        "SELECT * FROM bookings WHERE organization_id = $1 AND id = $2 OR active",
    ],
)
def test_runtime_guard_rejects_comment_projection_and_or_escape(sql):
    with pytest.raises(TenantScopeViolation):
        assert_org_scoped(sql)


def test_runtime_guard_accepts_tenant_conjunct_with_other_or_conditions():
    assert_org_scoped(
        "SELECT * FROM bookings "
        "WHERE organization_id = $1 AND (status = $2 OR status = $3)"
    )


@pytest.mark.parametrize(
    "sql",
    [
        "WITH scoped AS (SELECT id FROM bookings WHERE organization_id = $1) "
        "SELECT * FROM bookings WHERE id IN (SELECT id FROM scoped)",
        "SELECT * FROM bookings b WHERE EXISTS ("
        "SELECT 1 FROM messages m WHERE m.organization_id = $1 AND m.conversation_id = b.id)",
        "UPDATE bookings SET stato = $2 WHERE organization_id = $1; "
        "DELETE FROM messages WHERE id = $3",
    ],
)
def test_runtime_guard_scope_does_not_cross_query_blocks_or_statements(sql):
    with pytest.raises(TenantScopeViolation):
        assert_org_scoped(sql)


def test_runtime_guard_requires_scope_for_each_tenant_join():
    with pytest.raises(TenantScopeViolation):
        assert_org_scoped(
            "SELECT b.id FROM bookings b JOIN messages m ON m.id = b.id "
            "WHERE b.organization_id = $1"
        )
    assert_org_scoped(
        "SELECT b.id FROM bookings b JOIN messages m ON m.id = b.id "
        "WHERE b.organization_id = $1 AND m.organization_id = $1"
    )


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT a.* FROM message_delivery_attempts a "
        "JOIN messages m ON a.message_id = m.id OR TRUE "
        "WHERE m.organization_id = $1",
        "SELECT log.* FROM contact_consent_log log "
        "JOIN contacts c ON c.id = log.contact_id OR TRUE "
        "WHERE c.organization_id = $1",
        "SELECT a.* FROM message_delivery_attempts a JOIN messages m ON TRUE "
        "WHERE (a.message_id = m.id OR TRUE) AND m.organization_id = $1",
        "SELECT log.* FROM contact_consent_log log JOIN contacts c ON TRUE "
        "WHERE (log.contact_id = c.id OR TRUE) AND c.organization_id = $1",
    ],
)
def test_runtime_guard_rejects_parent_relation_or_escape(sql):
    with pytest.raises(TenantScopeViolation):
        assert_org_scoped(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM message_delivery_attempts WHERE status = 'pending'",
        "SELECT a.* FROM message_delivery_attempts a JOIN messages m "
        "ON a.message_id = m.id WHERE a.status = 'pending'",
        "UPDATE message_delivery_attempts SET status = 'failed' WHERE id = $1",
        "UPDATE message_delivery_attempts a SET status = 'failed' "
        "FROM messages m WHERE a.message_id = m.id AND a.id = $1",
        "INSERT INTO message_delivery_attempts (id, message_id, next_retry_at) "
        "SELECT $1, m.id, $2 FROM messages m WHERE m.id = $3",
    ],
)
def test_runtime_guard_rejects_delivery_attempts_without_scoped_parent(sql):
    with pytest.raises(TenantScopeViolation):
        assert_org_scoped(sql)


def test_runtime_guard_requires_delivery_attempt_parent_relationship():
    assert_org_scoped(
        "SELECT a.* FROM message_delivery_attempts a "
        "JOIN messages m ON a.message_id = m.id "
        "WHERE m.organization_id = $1"
    )


def test_runtime_guard_requires_consent_log_parent_relationship():
    with pytest.raises(TenantScopeViolation):
        assert_org_scoped(
            "SELECT log.* FROM contact_consent_log log, contacts c "
            "WHERE c.organization_id = $1"
        )
    assert_org_scoped(
        "SELECT log.* FROM contact_consent_log log "
        "JOIN contacts c ON c.id = log.contact_id "
        "WHERE c.organization_id = $1"
    )


def test_scoped_runtime_rejects_truncate_even_with_tenant_relation():
    with pytest.raises(TenantScopeViolation, match="rifiuta DDL"):
        assert_org_scoped("TRUNCATE TABLE bookings", ORG_ID)
    assert extract_tables("TRUNCATE TABLE bookings") == {"bookings"}


@pytest.mark.parametrize(
    "sql",
    [
        "ALTER TABLE bookings ADD COLUMN note text",
        "DROP TABLE bookings",
        "COPY bookings TO STDOUT",
        "LOCK TABLE bookings IN ACCESS EXCLUSIVE MODE",
        "GRANT SELECT ON TABLE bookings TO app_user",
    ],
)
def test_scoped_runtime_rejects_non_dml_statements(sql):
    with pytest.raises(TenantScopeViolation, match="SQL non supportato"):
        assert_org_scoped(sql, ORG_ID)


def test_runtime_guard_allows_consent_insert_select_from_scoped_contact():
    assert_org_scoped(
        "INSERT INTO contact_consent_log (id, contact_id, event_type) "
        "SELECT $1, c.id, $3 FROM contacts c "
        "WHERE c.id = $2::uuid AND c.organization_id = $4::uuid RETURNING *"
    )


def test_runtime_guard_rejects_upsert_that_can_update_another_tenant_row():
    unsafe = (
        "INSERT INTO bookings (id, organization_id, nome_cliente) "
        "VALUES ($1, $2, $3) ON CONFLICT (id) DO UPDATE "
        "SET nome_cliente = EXCLUDED.nome_cliente"
    )
    with pytest.raises(TenantScopeViolation):
        assert_org_scoped(unsafe, ORG_ID, (uuid.uuid4(), ORG_ID, "A"))

    constraint_target = (
        "INSERT INTO bookings (id, organization_id, nome_cliente) "
        "VALUES ($1, $2, $3) ON CONFLICT ON CONSTRAINT bookings_id_key "
        "DO UPDATE SET nome_cliente = EXCLUDED.nome_cliente"
    )
    with pytest.raises(TenantScopeViolation):
        assert_org_scoped(constraint_target, ORG_ID, (uuid.uuid4(), ORG_ID, "A"))

    or_escape = (
        "INSERT INTO bookings (id, organization_id, nome_cliente) "
        "VALUES ($1, $2, $3) ON CONFLICT (id) DO UPDATE "
        "SET nome_cliente = EXCLUDED.nome_cliente "
        "WHERE bookings.organization_id = EXCLUDED.organization_id OR TRUE"
    )
    with pytest.raises(TenantScopeViolation):
        assert_org_scoped(or_escape, ORG_ID, (uuid.uuid4(), ORG_ID, "A"))


def test_runtime_guard_allows_upsert_with_organization_in_conflict_key():
    sql = (
        "INSERT INTO conversations (id, organization_id, contact_id, canale) "
        "VALUES ($1, $2, $3, $4) "
        "ON CONFLICT (organization_id, contact_id) "
        "DO UPDATE SET last_message_at = NOW()"
    )
    assert_org_scoped(sql, ORG_ID, (uuid.uuid4(), str(ORG_ID), uuid.uuid4(), "whatsapp"))


@pytest.mark.parametrize(
    "condition",
    [
        "outbound_dedup.organization_id = EXCLUDED.organization_id",
        "EXCLUDED.organization_id = outbound_dedup.organization_id",
        "(outbound_dedup.organization_id = EXCLUDED.organization_id) AND TRUE",
    ],
)
def test_runtime_guard_accepts_conflict_update_guarded_by_org(condition):
    sql = (
        "INSERT INTO outbound_dedup (message_id, organization_id, response_text) "
        "VALUES ($1, $2, $3) ON CONFLICT (message_id) DO UPDATE "
        "SET response_text = EXCLUDED.response_text WHERE " + condition
    )
    assert_org_scoped(sql, ORG_ID, (uuid.uuid4(), ORG_ID, "reply"))


def test_runtime_guard_rejects_org_guard_under_or_in_conflict_update():
    sql = (
        "INSERT INTO outbound_dedup (message_id, organization_id, response_text) "
        "VALUES ($1, $2, $3) ON CONFLICT (message_id) DO UPDATE "
        "SET response_text = EXCLUDED.response_text WHERE "
        "outbound_dedup.organization_id = EXCLUDED.organization_id OR TRUE"
    )
    with pytest.raises(TenantScopeViolation):
        assert_org_scoped(sql, ORG_ID, (uuid.uuid4(), ORG_ID, "reply"))


def test_runtime_guard_rejects_direct_organization_id_mutation():
    sql = (
        "UPDATE bookings SET organization_id = $1, nome_cliente = $2 "
        "WHERE organization_id = $3 AND id = $4"
    )
    with pytest.raises(TenantScopeViolation):
        assert_org_scoped(sql, ORG_ID, (ORG_ID, "A", ORG_ID, uuid.uuid4()))


def test_sql_tokenizer_handles_unicode_identifier():
    assert extract_tables(
        "SELECT * FROM public.bookings café WHERE organization_id = $1"
    ) == {"bookings"}


def test_infra_and_root_tables_not_flagged():
    assert_org_scoped(
        "INSERT INTO webhook_idempotency (key) VALUES ($1)"
    )
    assert_org_scoped(
        "UPDATE organizations SET subscription_status = $1 WHERE id = $2"
    )


def test_parent_derived_table_requires_parent_relationship():
    with pytest.raises(TenantScopeViolation):
        assert_org_scoped("SELECT * FROM contact_consent_log WHERE event_type = 'opt_out'")


def test_dynamic_sql_rejected_at_runtime():
    var_tabella = "bookings"
    sql = "SELECT * FROM " + var_tabella + " WHERE id = $1"
    with pytest.raises(TenantScopeViolation):
        assert_org_scoped(sql)


def test_join_on_scoped_table_requires_filter_in_sql_text():
    sql = "SELECT * FROM messages m JOIN conversations c ON c.id = $1"
    with pytest.raises(TenantScopeViolation):
        assert_org_scoped(sql)
    ok = (
        "SELECT * FROM messages m "
        "JOIN conversations c ON c.id = m.conversation_id "
        "WHERE m.organization_id = $1 AND c.organization_id = $1"
    )
    assert_org_scoped(ok)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM contacts WHERE NOT organization_id = $1",
        "SELECT * FROM contacts WHERE organization_id = $1 IS FALSE",
        "SELECT * FROM contacts WHERE CASE WHEN organization_id = $1 THEN false ELSE true END",
        "UPDATE contacts SET marketing_opt_out = TRUE WHERE NOT organization_id = $1",
        "UPDATE contacts SET marketing_opt_out = TRUE WHERE CASE WHEN organization_id = $1 THEN false ELSE true END",
    ],
)
def test_runtime_guard_rejects_negative_or_wrapped_tenant_predicates(sql):
    with pytest.raises(TenantScopeViolation):
        assert_org_scoped(sql, ORG_ID, (ORG_ID,))


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM contacts WHERE organization_id = $1",
        "SELECT * FROM contacts WHERE ($1::uuid = contacts.organization_id) AND active = TRUE",
        "UPDATE contacts SET marketing_opt_out = TRUE WHERE contacts.organization_id = $1",
    ],
)
def test_runtime_guard_keeps_positive_tenant_predicates(sql):
    assert_org_scoped(sql, ORG_ID, (ORG_ID,))


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT m.id FROM contacts c, messages m WHERE c.organization_id = $1",
        "SELECT m.id FROM organizations o, messages m WHERE o.id = $1",
        "SELECT m.id FROM organizations o JOIN contacts c ON c.organization_id = $1, messages m WHERE c.organization_id = $1",
    ],
)
def test_runtime_guard_rejects_comma_join_with_uninventoried_relation(sql):
    with pytest.raises(TenantScopeViolation):
        assert_org_scoped(sql, ORG_ID, (ORG_ID,))


@pytest.mark.parametrize("quoted_keyword", ["select", "update", "where"])
def test_runtime_guard_rejects_comma_join_after_quoted_keyword(quoted_keyword):
    sql = (
        "SELECT m.id FROM organizations o JOIN ("
        f'SELECT id, organization_id, organization_id AS "{quoted_keyword}" FROM contacts '
        "WHERE organization_id = $1) c "
        "ON c.organization_id = $1 AND c.organization_id = o.id "
        f'AND c."{quoted_keyword}" = o.id, messages m '
        "WHERE c.organization_id = $1"
    )
    with pytest.raises(TenantScopeViolation):
        assert_org_scoped(sql, ORG_ID, (ORG_ID,))


def test_runtime_guard_accepts_quoted_keyword_alias_without_comma_join():
    assert_org_scoped(
        'SELECT c.id AS "select" FROM contacts c WHERE c.organization_id = $1',
        ORG_ID,
        (ORG_ID,),
    )


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
def test_runtime_final_microfix_rejects_alias_collision_and_preserved_outer_rows(sql):
    with pytest.raises(TenantScopeViolation):
        assert_org_scoped(sql, ORG_ID, (ORG_ID,))


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
def test_runtime_final_microfix_accepts_exact_alias_and_effective_join_scope(sql):
    assert_org_scoped(sql, ORG_ID, (ORG_ID,))


def test_runtime_guard_keeps_fully_scoped_explicit_join():
    assert_org_scoped(
        "SELECT m.id FROM contacts c JOIN messages m ON m.organization_id = c.organization_id "
        "WHERE c.organization_id = $1 AND m.organization_id = $1",
        ORG_ID,
        (ORG_ID, ORG_ID, ORG_ID),
    )


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT l.id FROM contact_consent_log l JOIN contacts c ON NOT l.contact_id = c.id WHERE c.organization_id = $1",
        "SELECT l.id FROM contact_consent_log l JOIN messages m ON m.id = l.contact_id WHERE m.organization_id = $1",
        "SELECT l.id FROM contact_consent_log l JOIN contacts c ON c.id = gen_random_uuid() WHERE c.organization_id = $1",
        "SELECT a.id FROM message_delivery_attempts a JOIN messages m ON a.message_id <> m.id WHERE m.organization_id = $1",
    ],
)
def test_runtime_guard_rejects_negated_wrong_or_disconnected_parent_relation(sql):
    with pytest.raises(TenantScopeViolation):
        assert_org_scoped(sql, ORG_ID, (ORG_ID,))


def test_runtime_guard_rejects_upsert_that_changes_organization_ownership():
    sql = (
        "INSERT INTO contacts(id, organization_id, phone_number) VALUES($4, $1, $3) "
        "ON CONFLICT(organization_id, phone_number) "
        "DO UPDATE SET organization_id = $2 RETURNING organization_id"
    )
    with pytest.raises(TenantScopeViolation):
        assert_org_scoped(sql, ORG_ID, (ORG_ID, uuid.uuid4(), "phone", uuid.uuid4()))


def test_runtime_guard_allows_upsert_that_preserves_organization_ownership():
    sql = (
        "INSERT INTO contacts(id, organization_id, phone_number) VALUES($3, $1, $2) "
        "ON CONFLICT(organization_id, phone_number) "
        "DO UPDATE SET marketing_opt_out = EXCLUDED.marketing_opt_out RETURNING id"
    )
    assert_org_scoped(sql, ORG_ID, (ORG_ID, "phone", uuid.uuid4()))


# ── scoped_conn ─────────────────────────────────────────────────


async def test_scoped_conn_none_raises_missing_org():
    conn = RecordingConn()
    repo = RepoWithStubPool(StubPool(conn))
    with pytest.raises(MissingOrganizationIdError):
        async with repo.scoped_conn(None):
            pass
    assert conn.calls == []


async def test_scoped_conn_invalid_uuid_fails_closed():
    conn = RecordingConn()
    repo = RepoWithStubPool(StubPool(conn))
    with pytest.raises(ValueError):
        async with repo.scoped_conn("not-a-uuid"):
            pass
    assert conn.calls == []


async def test_scoped_conn_yields_proxy_bound_to_org():
    conn = RecordingConn()
    repo = RepoWithStubPool(StubPool(conn))
    async with repo.scoped_conn(ORG_ID) as scoped:
        assert isinstance(scoped, ScopedConnection)
        rows = await scoped.fetch(
            "SELECT * FROM messages WHERE organization_id = $1", ORG_ID
        )
    assert rows == []
    assert len(conn.calls) == 1
    method, sql, _ = conn.calls[0]
    assert method == "fetch"
    assert "organization_id" in sql


async def test_scoped_connection_rejects_mismatched_org_bind():
    conn = RecordingConn()
    scoped = ScopedConnection(conn, ORG_ID)
    with pytest.raises(TenantScopeViolation, match="non corrisponde"):
        await scoped.fetch(
            "SELECT * FROM messages WHERE organization_id = $1", uuid.uuid4()
        )
    assert conn.calls == []


async def test_scoped_connection_rejects_truncate_before_delegating():
    conn = RecordingConn()
    scoped = ScopedConnection(conn, ORG_ID)
    with pytest.raises(TenantScopeViolation, match="rifiuta DDL"):
        await scoped.execute("TRUNCATE TABLE bookings")
    assert conn.calls == []


async def test_scoped_connection_checks_nonfirst_string_uuid_bind():
    conn = RecordingConn()
    scoped = ScopedConnection(conn, ORG_ID)
    await scoped.execute(
        "UPDATE bookings SET stato = $1 WHERE id = $2 AND organization_id = $3::uuid",
        "ok", uuid.uuid4(), str(ORG_ID),
    )
    assert len(conn.calls) == 1


async def test_scoped_connection_checks_insert_organization_bind():
    conn = RecordingConn()
    scoped = ScopedConnection(conn, ORG_ID)
    await scoped.execute(
        "INSERT INTO bookings (id, organization_id) VALUES ($1, $2::uuid)",
        uuid.uuid4(), str(ORG_ID),
    )
    with pytest.raises(TenantScopeViolation, match="non corrisponde"):
        await scoped.execute(
            "INSERT INTO bookings (id, organization_id) VALUES ($1, $2::uuid)",
            uuid.uuid4(), uuid.uuid4(),
        )
    assert len(conn.calls) == 1
    with pytest.raises(TenantScopeViolation, match="non corrisponde"):
        await scoped.fetch(
            "SELECT * FROM messages WHERE id = $1 AND organization_id = $2::uuid",
            uuid.uuid4(), uuid.uuid4(),
        )
    assert len(conn.calls) == 1


# ── ScopedConnection ────────────────────────────────────────────


@pytest.mark.parametrize("method,sql,args", [
    ("fetch", "SELECT * FROM bookings WHERE organization_id = $1", (ORG_ID,)),
    ("fetchrow", "SELECT * FROM contacts WHERE organization_id = $1", (ORG_ID,)),
    ("fetchval", "SELECT COUNT(*) FROM reviews WHERE organization_id = $1", (ORG_ID,)),
    ("execute", "UPDATE bookings SET stato = $1 WHERE organization_id = $2", ("ok", ORG_ID)),
])
async def test_scoped_connection_delegates_scoped_queries(method, sql, args):
    conn = RecordingConn()
    scoped = ScopedConnection(conn, ORG_ID)
    await getattr(scoped, method)(sql, *args)
    assert conn.calls[0][0] == method
    assert conn.calls[0][1] == sql


async def test_scoped_connection_executemany_delegates():
    conn = RecordingConn()
    scoped = ScopedConnection(conn, ORG_ID)
    params = [(ORG_ID,), (ORG_ID,)]
    await scoped.executemany(
        "DELETE FROM email_configs WHERE organization_id = $1", params
    )
    method, sql, recorded_args = conn.calls[0]
    assert method == "executemany"
    assert "organization_id" in sql
    assert recorded_args == [(ORG_ID,), (ORG_ID,)]


@pytest.mark.parametrize("method,sql", [
    ("fetch", "SELECT * FROM messages WHERE id = $1"),
    ("fetchrow", "SELECT * FROM conversations WHERE id = $1"),
    ("fetchval", "SELECT COUNT(*) FROM faq_cache"),
    ("execute", "UPDATE whatsapp_templates SET status = 'APPROVED' WHERE name = $1"),
    ("executemany", "DELETE FROM usage_events"),
])
async def test_scoped_connection_rejects_unfiltered_queries(method, sql):
    conn = RecordingConn()
    scoped = ScopedConnection(conn, ORG_ID)
    coro = getattr(scoped, method)(sql, *(["x"] if method != "executemany" else [()]))
    with pytest.raises(TenantScopeViolation):
        await coro
    assert conn.calls == [], "il conn sottostante non deve mai vedere la query"


async def test_scoped_connection_transaction_delegates():
    conn = RecordingConn()
    scoped = ScopedConnection(conn, ORG_ID)
    assert scoped.transaction() is conn.tx_sentinel


async def test_scoped_connection_getattr_refuses_other_attributes():
    conn = RecordingConn()
    scoped = ScopedConnection(conn, ORG_ID)
    with pytest.raises(AttributeError):
        _ = scoped.cursor
    with pytest.raises(AttributeError):
        _ = scoped.copy_records_to_table


# ── system_scope ────────────────────────────────────────────────


def test_system_scope_sets_attribute_with_reason():
    @system_scope("tenant-resolution: lookup da webhook Meta")
    async def lookup():
        return None

    assert lookup.__system_scope__ == "tenant-resolution: lookup da webhook Meta"


def test_system_scope_reason_is_required():
    with pytest.raises(TypeError):
        system_scope()


# ── Mixin sulle tre classi repository ───────────────────────────


def test_all_three_repositories_inherit_the_mixin():
    from src.core.db.repository import CoreRepository
    from src.instagram.repository import InstagramRepository
    from src.whatsapp.repository import Repository

    for cls in (Repository, CoreRepository, InstagramRepository):
        assert issubclass(cls, TenantScopedRepository), cls.__name__
