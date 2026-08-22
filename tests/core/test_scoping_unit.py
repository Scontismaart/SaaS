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


# ── assert_org_scoped ───────────────────────────────────────────


def test_accepts_scoped_select():
    assert_org_scoped("SELECT * FROM bookings WHERE organization_id = $1")


def test_rejects_unscoped_select():
    with pytest.raises(TenantScopeViolation):
        assert_org_scoped("SELECT * FROM bookings WHERE id = $1")


def test_infra_and_root_tables_not_flagged():
    assert_org_scoped(
        "INSERT INTO webhook_idempotency (key) VALUES ($1)"
    )
    assert_org_scoped(
        "UPDATE organizations SET subscription_status = $1 WHERE id = $2"
    )


def test_indirect_tables_not_flagged_by_direct_check():
    assert_org_scoped(
        "SELECT * FROM message_delivery_attempts WHERE status = 'pending'"
    )


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
        "WHERE m.organization_id = $1"
    )
    assert_org_scoped(ok)


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
