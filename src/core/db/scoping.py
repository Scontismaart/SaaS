"""Primitive di tenant scoping (Invariante #1: Tenant Isolation).

Unica tabella di verita' per le tabelle tenant-scoped: il check runtime
(ScopedConnection) e lo script CI condividono le stesse costanti.

Fail-closed ovunque:
- organizzazione mancante/non valida -> MissingOrganizationIdError/ValueError
- statement su tabella tenant-scoped senza "organization_id" nel testo SQL
  finale -> TenantScopeViolation (il runtime valuta la stringa FINALE,
  quindi copre anche il SQL costruito dinamicamente).

Le tabelle in INDIRECT_SCOPED_TABLES sono escluse dal check diretto:
non portano organization_id propria ma restano coperte da RLS e dal
filtro sulla tabella padre (es. message_delivery_attempts via messages).
"""
import re
import uuid
from contextlib import asynccontextmanager

TENANT_SCOPED_TABLES: frozenset[str] = frozenset({
    "whatsapp_accounts",
    "contacts",
    "conversations",
    "messages",
    "whatsapp_templates",
    "bookings",
    "booking_settings",
    "reviews",
    "documents",
    "document_chunks",
    "email_configs",
    "usage_events",
    "event_log",
    "faq_cache",
    "message_feedback",
    "instagram_accounts",
    "google_calendar_credentials",
    "google_business_credentials",
    "weekly_report_log",
    "onboarding_profiles",
    "audit_log",
    "organization_memberships",
    "outbound_dedup",
})

INDIRECT_SCOPED_TABLES: frozenset[str] = frozenset({
    "message_delivery_attempts",
    "contact_consent_log",
})

_TABLE_RE = re.compile(
    r"\b(?:from|join|into|update)\s+([a-zA-Z_][a-zA-Z0-9_]*)",
    re.IGNORECASE,
)


class MissingOrganizationIdError(TypeError):
    """organization_id e' obbligatorio: chiamato con None o senza argomento."""


class TenantScopeViolation(RuntimeError):
    """Statement su tabella tenant-scoped senza filtro organization_id."""


def extract_tables(sql: str) -> set[str]:
    """Nomi tabella toccati dal SQL finale (FROM/JOIN/INSERT INTO/UPDATE)."""
    return set(_TABLE_RE.findall(sql))


def assert_org_scoped(sql: str) -> None:
    """Fail-closed: rifiuta statement su tabelle tenant-scoped che non
    contengono esplicitamente 'organization_id' nel testo SQL."""
    touched = extract_tables(sql) & TENANT_SCOPED_TABLES
    if touched and "organization_id" not in sql:
        raise TenantScopeViolation(
            f"Query su tabelle tenant-scoped {sorted(touched)} "
            f"senza filtro organization_id: {sql[:120]!r}"
        )


class ScopedConnection:
    """Proxy fail-closed su una connessione asyncpg gia' vincolata a un org.

    Espone solo fetch/fetchrow/fetchval/execute/executemany (ognuno passa
    da assert_org_scoped PRIMA di delegare) e transaction(). Qualsiasi
    altro attributo e' rifiutato: niente scorciatoie fuori dal guard.
    """

    __slots__ = ("_conn", "_org")

    def __init__(self, conn, organization_id: uuid.UUID):
        self._conn = conn
        self._org = organization_id

    @property
    def organization_id(self) -> uuid.UUID:
        return self._org

    async def fetch(self, sql, *args, **kwargs):
        assert_org_scoped(sql)
        return await self._conn.fetch(sql, *args, **kwargs)

    async def fetchrow(self, sql, *args, **kwargs):
        assert_org_scoped(sql)
        return await self._conn.fetchrow(sql, *args, **kwargs)

    async def fetchval(self, sql, *args, **kwargs):
        assert_org_scoped(sql)
        return await self._conn.fetchval(sql, *args, **kwargs)

    async def execute(self, sql, *args, **kwargs):
        assert_org_scoped(sql)
        return await self._conn.execute(sql, *args, **kwargs)

    async def executemany(self, sql, args_seq, *args, **kwargs):
        assert_org_scoped(sql)
        return await self._conn.executemany(sql, args_seq, *args, **kwargs)

    def transaction(self):
        return self._conn.transaction()

    def __getattr__(self, name):
        raise AttributeError(
            f"ScopedConnection non espone {name!r}: usa fetch/fetchrow/"
            f"fetchval/execute/executemany/transaction (query senza passare "
            f"dal guard tenant-scope sono vietate)"
        )

    def __repr__(self) -> str:  # pragma: no cover - diagnostica
        return f"<ScopedConnection org={self._org}>"


class TenantScopedRepository:
    """Mixin per le classi repository: aggiunge scoped_conn(organization_id).

    Uso: `async with self.scoped_conn(org_id) as conn:` al posto di
    `async with self.pool.acquire() as conn:` — ogni statement delegato
    viene validato contro il filtro organization_id.
    """

    @asynccontextmanager
    async def scoped_conn(self, organization_id):
        if organization_id is None:
            raise MissingOrganizationIdError(
                "organization_id e' obbligatorio: nessuna connessione "
                "tenant-scoped senza org (fail-closed)"
            )
        org = uuid.UUID(str(organization_id))
        async with self.pool.acquire() as conn:
            yield ScopedConnection(conn, org)


def system_scope(reason: str):
    """Decorator per le eccezioni intenzionali cross-tenant (tenant
    resolution da webhook, worker globali, retention). Il motivo e'
    obbligatorio e finisce nell'attributo __system_scope__ letto dal
    check CI."""
    if not reason or not isinstance(reason, str):
        raise TypeError("system_scope richiede un motivo (str) obbligatorio")

    def decorator(fn):
        fn.__system_scope__ = reason
        return fn

    return decorator
