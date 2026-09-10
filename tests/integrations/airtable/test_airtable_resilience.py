"""Unit test di resilienza per l'integrazione Airtable.

Policy ufficiale (https://airtable.com/developers/web/api/rate-limits):
- 5 request/sec per base (50 req/s per token PAT).
- Su 429: attendere 30 secondi prima di riprovare (o il valore dell'header Retry-After).

Casi coperti:
1. 429: ritentato automaticamente (con Retry-After e con default ufficiale 30s)
2. Backoff: esponenziale con jitter per 5xx/rette transienti, policy 429 rispettata
3. Retry exhaustion: 429/5xx persistenti -> errore dopo max_retries+1 tentativi
4. 5xx: ritentato con backoff, poi errore se persistente
5. Timeout: errori di rete transienti ritentati, AirtableNetworkError all'esaurimento
6. No-retry: 400/401/403/404/422 falliscono immediatamente (1 sola richiesta)
7. Concurrent requests: rate limiter per-base spazia le richieste concorrenti
8. Cache metadata: hit/miss, TTL, single-flight, invalidazione; record MAI cachati
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx
import pytest

from src.integrations.airtable.adapter import (
    DEFAULT_WAIT_SECONDS_ON_429,
    AirtableAdapter,
    AirtableRateLimiter,
    AirtableSchemaCache,
    compute_backoff_delay,
    compute_retry_delay,
    is_retryable_status,
)
from src.integrations.airtable.errors import (
    AirtableAuthError,
    AirtableError,
    AirtableNetworkError,
    AirtableNotFoundError,
    AirtableRateLimitError,
    AirtableServerError,
    AirtableValidationError,
)
from src.integrations.airtable.models import ListRecordsParams


# ── HELPERS ──────────────────────────────────────────────────────────────────


def make_adapter(handler, **kwargs) -> tuple[AirtableAdapter, list[httpx.Request]]:
    """Costruisce un adapter con MockTransport e config di retry veloce per i test."""
    requests_seen: list[httpx.Request] = []

    def wrapped_handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(wrapped_handler))
    defaults: dict[str, Any] = {
        "retry_backoff_base_seconds": 0.001,
        "retry_backoff_cap_seconds": 0.005,
        "wait_seconds_on_429": 0.001,
        "rate_limiter": AirtableRateLimiter(requests_per_second=1000.0),
        "schema_cache": AirtableSchemaCache(ttl_seconds=60.0),
    }
    defaults.update(kwargs)
    adapter = AirtableAdapter(token="pat_resilience_test", http_client=client, **defaults)
    return adapter, requests_seen


def schema_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "tables": [
                {
                    "id": "tbl001",
                    "name": "Clienti",
                    "primaryFieldId": "fld001",
                    "fields": [{"id": "fld001", "name": "Nome", "type": "singleLineText"}],
                }
            ]
        },
    )


def records_response(n: int = 1, offset: str | None = None) -> httpx.Response:
    body: dict[str, Any] = {
        "records": [
            {"id": f"rec{i}", "createdTime": "2026-09-08T10:00:00.000Z", "fields": {"Nome": f"R{i}"}}
            for i in range(n)
        ]
    }
    if offset:
        body["offset"] = offset
    return httpx.Response(200, json=body)


# ── 1. CLASSIFICAZIONE RETRY ─────────────────────────────────────────────────


def test_retryable_status_classification():
    """Retry SOLO per 429 e 5xx: mai per 400/401/403/404/422/validation."""
    assert is_retryable_status(429) is True
    assert is_retryable_status(500) is True
    assert is_retryable_status(502) is True
    assert is_retryable_status(503) is True
    assert is_retryable_status(400) is False
    assert is_retryable_status(401) is False
    assert is_retryable_status(403) is False
    assert is_retryable_status(404) is False
    assert is_retryable_status(422) is False


# ── 2. 429 E POLICY DI BACKOFF UFFICIALE ─────────────────────────────────────


@pytest.mark.asyncio
async def test_429_respects_retry_after_header():
    """429 con header Retry-After: il delay deve rispettare esattamente il valore dell'header."""
    resp = httpx.Response(429, headers={"Retry-After": "7"})
    assert compute_retry_delay(resp, wait_seconds_on_429=DEFAULT_WAIT_SECONDS_ON_429) == 7.0


def test_429_without_retry_after_uses_official_30s_default():
    """429 senza header: policy ufficiale Airtable = attendere 30 secondi."""
    resp = httpx.Response(429)
    assert compute_retry_delay(resp, wait_seconds_on_429=DEFAULT_WAIT_SECONDS_ON_429) == 30.0


def test_5xx_uses_exponential_backoff_not_30s():
    """5xx: backoff esponenziale con jitter, non l'attesa di 30s richiesta solo sul 429."""
    resp = httpx.Response(503)
    delay0 = compute_retry_delay(resp)
    assert 0.5 <= delay0 <= 0.5 * 1.25 + 1e-9

    # Backoff esponenziale cresce e rispetta il cap
    assert compute_backoff_delay(0, base_seconds=0.5, cap_seconds=8.0) >= 0.5
    assert compute_backoff_delay(3, base_seconds=0.5, cap_seconds=8.0) <= 8.0
    # Jitter: due chiamate non sono identiche (con probabilita' trascurabile di parieta')
    delays = {round(compute_backoff_delay(2), 9) for _ in range(20)}
    assert len(delays) > 1


@pytest.mark.asyncio
async def test_429_is_retried_and_then_succeeds():
    """429: prima risposta rate-limited, retry automatico, seconda risposta OK."""
    state = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["count"] += 1
        if state["count"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0.01"})
        return records_response()

    adapter, seen = make_adapter(handler)

    page = await adapter.list_records("appRes", "Clienti")
    assert len(page.records) == 1
    assert state["count"] == 2
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_429_backoff_respects_official_default_wait(monkeypatch):
    """429 senza Retry-After: il loop attende il default ufficiale (30s) prima del retry."""
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("src.integrations.airtable.adapter.asyncio.sleep", fake_sleep)

    state = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["count"] += 1
        if state["count"] == 1:
            return httpx.Response(429)
        return records_response()

    # Default ufficiale esplicito: su 429 senza Retry-After si attendono 30 secondi
    adapter, _ = make_adapter(handler, wait_seconds_on_429=DEFAULT_WAIT_SECONDS_ON_429)
    page = await adapter.list_records("appRes", "Clienti")

    assert page.records[0].id == "rec0"
    assert 30.0 in sleeps


# ── 3. RETRY EXHAUSTION ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_429_retry_exhaustion_raises_rate_limit_error():
    """429 persistente: dopo max_retries+1 tentativi solleva AirtableRateLimitError."""
    state = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["count"] += 1
        return httpx.Response(429, headers={"Retry-After": "0.001"})

    adapter, seen = make_adapter(handler, max_retries=2)

    with pytest.raises(AirtableRateLimitError):
        await adapter.get_record("appRes", "Clienti", "rec1")

    # 1 tentativo iniziale + 2 retry = 3 richieste totali
    assert state["count"] == 3
    assert len(seen) == 3


@pytest.mark.asyncio
async def test_5xx_retry_exhaustion_raises_server_error():
    """5xx persistente: esauriti i retry solleva AirtableServerError senza retry infiniti."""
    state = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["count"] += 1
        return httpx.Response(503, json={"error": {"message": "Service unavailable"}})

    adapter, _ = make_adapter(handler, max_retries=2)

    with pytest.raises(AirtableServerError):
        await adapter.list_records("appRes", "Clienti")

    assert state["count"] == 3


# ── 4. 5XX TRANSIENT ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_5xx_transient_is_retried_with_backoff():
    """5xx transiente (502 poi 200): recuperato automaticamente con backoff."""
    state = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["count"] += 1
        if state["count"] <= 2:
            return httpx.Response(502)
        return records_response(n=2)

    adapter, _ = make_adapter(handler)

    page = await adapter.list_records("appRes", "Clienti")
    assert len(page.records) == 2
    assert state["count"] == 3


# ── 5. TIMEOUT / ERRORI DI RETE ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_timeout_is_retried_then_succeeds():
    """Timeout transiente: ritentato e recuperato."""
    state = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["count"] += 1
        if state["count"] == 1:
            raise httpx.ConnectTimeout("connection timed out", request=request)
        return records_response()

    adapter, _ = make_adapter(handler)

    page = await adapter.list_records("appRes", "Clienti")
    assert state["count"] == 2
    assert page.records[0].id == "rec0"


@pytest.mark.asyncio
async def test_timeout_exhaustion_raises_network_error():
    """Timeout persistente: esauriti i retry solleva AirtableNetworkError."""
    state = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["count"] += 1
        raise httpx.ReadTimeout("read timed out", request=request)

    adapter, _ = make_adapter(handler, max_retries=2)

    with pytest.raises(AirtableNetworkError):
        await adapter.get_record("appRes", "Clienti", "rec1")

    assert state["count"] == 3


@pytest.mark.asyncio
async def test_connection_error_is_retried():
    """Errore di connessione transiente (RequestError): ritentato e recuperato."""
    state = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["count"] += 1
        if state["count"] == 1:
            raise httpx.ConnectError("connection reset", request=request)
        return records_response()

    adapter, _ = make_adapter(handler)

    page = await adapter.list_records("appRes", "Clienti")
    assert state["count"] == 2


# ── 6. NO RETRY SU ERRORI NON TRANSIENTI ─────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,expected_exception",
    [
        (400, AirtableError),
        (401, AirtableAuthError),
        (403, AirtableAuthError),
        (404, AirtableNotFoundError),
        (422, AirtableValidationError),
    ],
)
async def test_permanent_errors_fail_immediately_without_retry(status, expected_exception):
    """400/401/403/404/422: falliscono alla prima richiesta, ZERO retry."""
    state = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["count"] += 1
        return httpx.Response(status, json={"error": {"message": f"HTTP {status}"}})

    adapter, _ = make_adapter(handler, max_retries=2)

    with pytest.raises(expected_exception):
        await adapter.get_record("appRes", "Clienti", "rec1")

    assert state["count"] == 1


# ── 7. CONCURRENT REQUESTS / RATE LIMITER ────────────────────────────────────


@pytest.mark.asyncio
async def test_rate_limiter_spaces_concurrent_requests_same_base():
    """Rate limiter per-base: N richieste concorrenti sulla stessa base vengono spaziate (5 req/s ufficiali)."""
    # Intervallo 50ms: superiore alla risoluzione del timer di sistema (Windows ~15ms)
    limiter = AirtableRateLimiter(requests_per_second=20.0)
    completion_times: list[float] = []

    async def worker():
        await limiter.acquire("appSameBase")
        completion_times.append(time.monotonic())

    start = time.monotonic()
    await asyncio.gather(*(worker() for _ in range(5)))
    elapsed = time.monotonic() - start

    completion_times.sort()
    assert len(completion_times) == 5
    # 5 richieste a 20 req/s: servono almeno 4 intervalli di spaziatura (~200ms)
    min_expected = 4 * 0.05 * 0.8  # tolleranza 20% per lo scheduling
    assert elapsed >= min_expected
    # Le richieste non partono tutte insieme: gap minimo superiore al jitter del timer
    gaps = [b - a for a, b in zip(completion_times, completion_times[1:])]
    assert min(gaps) >= 0.025


@pytest.mark.asyncio
async def test_rate_limiter_different_bases_are_independent():
    """Basi diverse non si bloccano a vicenda (il limite ufficiale è per base)."""
    limiter = AirtableRateLimiter(requests_per_second=5.0)  # interval = 200ms

    start = time.monotonic()
    await asyncio.gather(
        limiter.acquire("appBaseA"),
        limiter.acquire("appBaseB"),
        limiter.acquire("appBaseC"),
    )
    elapsed = time.monotonic() - start

    # Se le basi si bloccassero a vicenda servirebbero ~400ms; per base indipendente quasi zero.
    assert elapsed < 0.15


@pytest.mark.asyncio
async def test_concurrent_list_records_all_succeed():
    """20 conversazioni concorrenti sulla stessa base: tutte servite, spaziate dal limiter."""
    request_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        request_count["n"] += 1
        return records_response()

    adapter, _ = make_adapter(handler, rate_limiter=AirtableRateLimiter(requests_per_second=200.0))

    results = await asyncio.gather(
        *(adapter.list_records("appConc", "Clienti") for _ in range(20))
    )

    assert len(results) == 20
    assert request_count["n"] == 20
    assert all(len(r.records) == 1 for r in results)


# ── 8. CACHE METADATA (HIT/MISS, SINGLE-FLIGHT, TTL) ─────────────────────────


@pytest.mark.asyncio
async def test_schema_cache_hit_after_first_load():
    """Cache hit: la seconda get_base_schema NON genera una seconda richiesta HTTP."""
    state = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["count"] += 1
        return schema_response()

    adapter, seen = make_adapter(handler)

    tables1 = await adapter.get_base_schema("appCache")
    tables2 = await adapter.get_base_schema("appCache")

    assert state["count"] == 1
    assert len(seen) == 1
    assert tables1 == tables2
    assert adapter._schema_cache.hits == 1
    assert adapter._schema_cache.misses == 1


@pytest.mark.asyncio
async def test_schema_cache_single_flight_concurrent():
    """Single-flight: 15 get_base_schema concorrenti generano UNA SOLA richiesta HTTP."""
    state = {"count": 0}

    async def slow_handler(request: httpx.Request) -> httpx.Response:
        state["count"] += 1
        await asyncio.sleep(0.01)  # simula latenza: le concurrenti devono attendere, non rifare
        return schema_response()

    adapter, seen = make_adapter(slow_handler)

    results = await asyncio.gather(*(adapter.get_base_schema("appFlight") for _ in range(15)))

    assert len(results) == 15
    assert all(len(tables) == 1 for tables in results)
    assert state["count"] == 1
    assert len(seen) == 1
    assert adapter._schema_cache.misses == 1


@pytest.mark.asyncio
async def test_schema_cache_miss_after_invalidation():
    """Invalidazione: dopo invalidate la prossima lettura ricarica da Airtable."""
    state = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["count"] += 1
        return schema_response()

    adapter, _ = make_adapter(handler)

    await adapter.get_base_schema("appInv")
    await adapter.get_base_schema("appInv")
    assert state["count"] == 1

    removed = await adapter.invalidate_schema_cache("appInv")
    assert removed == 1

    await adapter.get_base_schema("appInv")
    assert state["count"] == 2


@pytest.mark.asyncio
async def test_schema_cache_is_token_scoped():
    """Invariante 1 & 10: la cache è scoped sul token (hash): token diversi non condividono entry."""
    state = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["count"] += 1
        return schema_response()

    cache = AirtableSchemaCache(ttl_seconds=60.0)
    adapter_a, _ = make_adapter(handler, schema_cache=cache)
    adapter_b, _ = make_adapter(handler, schema_cache=cache)
    # Token diversi (suffisso per distinguere i PAT)
    adapter_b._token = "pat_other_tenant_token"

    await adapter_a.get_base_schema("appShared")
    await adapter_b.get_base_schema("appShared")

    # Due token diversi = due caricamenti: nessun leak di metadata tra tenant
    assert state["count"] == 2
    assert cache.misses == 2


@pytest.mark.asyncio
async def test_records_are_never_cached():
    """I record dinamici NON vengono cachati: ogni list_records è una richiesta reale."""
    state = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["count"] += 1
        return records_response()

    adapter, _ = make_adapter(handler)

    await adapter.list_records("appDyn", "Clienti")
    await adapter.list_records("appDyn", "Clienti")

    assert state["count"] == 2


@pytest.mark.asyncio
async def test_schema_cache_ttl_expiry():
    """TTL: entry scaduta -> miss e ricaricamento."""
    cache = AirtableSchemaCache(ttl_seconds=0.01)
    loads = {"n": 0}

    async def loader() -> str:
        loads["n"] += 1
        return f"schema_v{loads['n']}"

    token = "pat_ttl_test"
    v1 = await cache.get_or_load(token, "appTtl", loader)
    v2 = await cache.get_or_load(token, "appTtl", loader)  # hit
    assert v1 == v2
    assert loads["n"] == 1

    await asyncio.sleep(0.02)  # scade il TTL
    v3 = await cache.get_or_load(token, "appTtl", loader)
    assert v3 == "schema_v2"
    assert loads["n"] == 2


# ── 9. BATCH E PAGINATION (riduzione API calls) ──────────────────────────────


@pytest.mark.asyncio
async def test_batch_create_uses_official_batch_endpoint():
    """BATCH: 25 record -> 3 richieste HTTP (10+10+5) invece di 25 chiamate singole."""
    batches: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        batches.append(len(body["records"]))
        return httpx.Response(
            200,
            json={"records": [{"id": f"rec_{i}_{b}", "fields": {}} for i, b in enumerate(range(batches[-1]))]},
        )

    adapter, _ = make_adapter(handler)
    records = [{"fields": {"Nome": f"N{i}"}} for i in range(25)]

    created = await adapter.create_records("appBatch", "Clienti", records)

    assert len(created) == 25
    assert batches == [10, 10, 5]


@pytest.mark.asyncio
async def test_pagination_stops_without_extra_requests():
    """PAGINATION: nessuna richiesta oltre l'ultima pagina (niente round-trip inutili)."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert "offset" not in str(request.url)  # prima pagina senza offset
        return httpx.Response(
            200,
            json={"records": [{"id": "rec1", "fields": {"Nome": "A"}}]},  # nessun offset => fine
        )

    adapter, seen = make_adapter(handler)
    records = await adapter.list_all_records("appPag", "Clienti")

    assert len(records) == 1
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_list_records_default_page_size_is_max_official():
    """PAGINATION: page size di default = 100 (massimo ufficiale) per ridurre le chiamate."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert "pageSize=100" in str(request.url)
        return records_response()

    adapter, _ = make_adapter(handler)
    await adapter.list_records("appPag", "Clienti", params=ListRecordsParams())


# ── 10. RATE LIMIT APPLICATO ANCHE AL FETCHER WEBHOOK ────────────────────────


@pytest.mark.asyncio
async def test_webhook_payload_fetcher_uses_rate_limiter_and_retries():
    """Il fetch dei payload webhook passa per il rate limiter condiviso e ritenta sui 429."""
    from src.integrations.airtable.webhook_service import AirtableWebhookPayloadFetcher

    class FakeConnectionRepo:
        async def get_connection(self, organization_id, base_id):
            return {"token": "pat_webhook_fetcher"}

    state = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["count"] += 1
        if state["count"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0.001"})
        return httpx.Response(200, json={"payloads": [{"cursor": 2}], "mightHaveMore": False})

    limiter = AirtableRateLimiter(requests_per_second=1000.0)
    fetcher = AirtableWebhookPayloadFetcher(
        connection_repo=FakeConnectionRepo(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        rate_limiter=limiter,
        wait_seconds_on_429=0.001,
    )

    import uuid as _uuid

    page = await fetcher.fetch(_uuid.uuid4(), "appFetch", "achFetch", 1)

    assert state["count"] == 2
    assert page["payloads"][0]["cursor"] == 2
    assert "appFetch" in limiter._next_slot  # la richiesta è passata dal rate limiter per-base
