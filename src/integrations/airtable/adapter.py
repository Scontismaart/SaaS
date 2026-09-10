"""Adapter di produzione per Airtable Web API v0.

Implementa l'interfaccia AirtablePort gestendo comunicazione HTTP asincrona,
sanitizzazione dei token (Invariante 10), normalizzazione degli errori,
e codifica sicura degli identificativi di Base e Tabella.

Resilienza (policy ufficiale https://airtable.com/developers/web/api/rate-limits):
- RATE LIMIT: 5 request/sec per base (e 50 req/s per token): ogni richiesta passa per un
  rate limiter condiviso per-base che spazia le chiamate invece di martellare l'API.
- RETRY: solo per 429 (rispettando la policy ufficiale: attendere 30 secondi, o il valore
  dell'header Retry-After se presente), errori di rete transienti e 5xx. MAI per 400, 401,
  403, 404, 422 o errori di validazione (falliscono immediatamente).
- BATCH: creazione/aggiornamento/eliminazione usano gli endpoint batch ufficiali
  (10 record/request) per ridurre il numero di API calls.
- PAGINATION: page size massimo (100) e stop non appena non ci sono altri record.
- CACHE: cache breve (TTL, single-flight) per metadata di base/tabelle/campi
  (get_base_schema); i record dinamici NON vengono mai cachati.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from urllib.parse import quote

import httpx

from src.integrations.airtable.errors import (
    AirtableAuthError,
    AirtableError,
    AirtableMalformedResponseError,
    AirtableNetworkError,
    AirtableNotFoundError,
    AirtableQuotaExhaustedError,
    AirtableRateLimitError,
    AirtableServerError,
    AirtableValidationError,
)
from src.integrations.airtable.models import (
    AirtableField,
    AirtableRecord,
    AirtableTable,
    BatchRecordItem,
    BatchUpdateRecordItem,
    CreateRecordRequest,
    DeleteRecordResult,
    ListRecordsParams,
    RecordPage,
    SchemaValidationResult,
    UpdateRecordRequest,
)
from src.integrations.airtable.port import AirtablePort

logger = logging.getLogger(__name__)

DEFAULT_AIRTABLE_BASE_URL = "https://api.airtable.com/v0"
DEFAULT_TIMEOUT_SECONDS = 8.0

# ── Costanti di resilienza (policy ufficiale Airtable) ──────────────────────

# Limite ufficiale Web API: 5 request/sec per base (50 req/s per token PAT).
DEFAULT_RATE_LIMIT_PER_SECOND = 5.0
# Policy ufficiale sul 429: "wait 30 seconds before subsequent requests will succeed".
DEFAULT_WAIT_SECONDS_ON_429 = 30.0
# Cache breve per metadata (base/tabelle/campi): 5 minuti.
DEFAULT_SCHEMA_CACHE_TTL_SECONDS = 300.0
# Retry: 1 tentativo iniziale + 2 retry (solo 429 / rete transiente / 5xx).
DEFAULT_MAX_RETRIES = 2
# Backoff esponenziale con jitter per 5xx e errori di rete transienti.
RETRY_BACKOFF_BASE_SECONDS = 0.5
RETRY_BACKOFF_CAP_SECONDS = 8.0


def is_retryable_status(status_code: int) -> bool:
    """Retry SOLO per 429 e 5xx. Mai per 400/401/403/404/422/validation errors."""
    return status_code == 429 or 500 <= status_code <= 599


def compute_backoff_delay(
    attempt: int,
    base_seconds: float = RETRY_BACKOFF_BASE_SECONDS,
    cap_seconds: float = RETRY_BACKOFF_CAP_SECONDS,
) -> float:
    """Backoff esponenziale con jitter per 5xx ed errori di rete transienti."""
    delay = base_seconds * (2 ** max(attempt, 0))
    delay += random.uniform(0, delay * 0.25)
    return min(delay, cap_seconds)


def compute_retry_delay(resp: httpx.Response, wait_seconds_on_429: float = DEFAULT_WAIT_SECONDS_ON_429) -> float:
    """Ritardo di attesa prima del retry secondo la policy ufficiale Airtable.

    - 429: rispetta l'header `Retry-After` se presente, altrimenti attende il default
      ufficiale di 30 secondi prima di riprovare.
    - 5xx: backoff esponenziale con jitter (l'attesa dei 30s è richiesta solo sul 429).
    """
    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return max(float(retry_after), 0.0)
            except ValueError:
                pass
        return wait_seconds_on_429
    return compute_backoff_delay(attempt=0)


class AirtableRateLimiter:
    """Rate limiter per-base conforme al limite ufficiale Airtable (5 request/sec per base).

    Garantisce che N richieste concorrenti verso la stessa Base vengano spaziate nel tempo
    invece di essere inviate tutte insieme (evita il 429 e protegge il limite di 50 req/s
    per token). Le chiavi diverse (basi diverse) non si bloccano a vicenda.
    """

    def __init__(self, requests_per_second: float = DEFAULT_RATE_LIMIT_PER_SECOND):
        self._interval = 1.0 / max(float(requests_per_second), 1e-6)
        self._schedule_lock = asyncio.Lock()
        self._next_slot: dict[str, float] = {}

    async def acquire(self, key: str) -> None:
        """Prenota lo slot temporale successivo per la chiave (base) indicata."""
        async with self._schedule_lock:
            now = time.monotonic()
            scheduled = max(now, self._next_slot.get(key, 0.0))
            self._next_slot[key] = scheduled + self._interval
            wait = scheduled - now
        if wait > 0:
            await asyncio.sleep(wait)


class AirtableSchemaCache:
    """Cache breve (TTL + single-flight) per metadata Airtable: base, tabelle e campi.

    Evita che 100 conversazioni simultanee eseguano tutte `GET /meta/bases/{id}/tables`
    prima di ogni operazione: la prima richiesta carica lo schema, le altre concurrenti
    attendono il single-flight e leggono dalla cache. Scadenza a TTL breve: i metadata
    cambiano raramente ma non vengono considerati eterni.

    I RECORD DINAMICI NON VENGONO MAI CACHATI (solo metadata strutturali).
    """

    def __init__(self, ttl_seconds: float = DEFAULT_SCHEMA_CACHE_TTL_SECONDS):
        self._ttl = float(ttl_seconds)
        self._entries: dict[tuple[str, str], tuple[float, Any]] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _key(token: str, base_id: str) -> tuple[str, str]:
        # La cache è keyed sul token (hash, mai il token in chiaro) + base: nessuna
        # condivisione di metadata tra credenziali/tenant diverse (Invariante 1 e 10).
        token_hash = hashlib.sha256(token.strip().encode("utf-8")).hexdigest()[:16]
        return (token_hash, base_id.strip())

    async def get_or_load(self, token: str, base_id: str, loader: Callable[[], Awaitable[Any]]) -> Any:
        key = self._key(token, base_id)
        entry = self._entries.get(key)
        if entry and entry[0] > time.monotonic():
            self.hits += 1
            return entry[1]

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            # Double-check dopo l'acquisizione (single-flight): una sola richiesta HTTP
            # anche con N chiamate concorrenti.
            entry = self._entries.get(key)
            if entry and entry[0] > time.monotonic():
                self.hits += 1
                return entry[1]
            self.misses += 1
            value = await loader()
            self._entries[key] = (time.monotonic() + self._ttl, value)
            return value

    def invalidate(self, token: str | None = None, base_id: str | None = None) -> int:
        """Invalida la cache (tutta, o solo per token/base). Restituisce il numero di entry rimosse."""
        if token is None and base_id is None:
            removed = len(self._entries)
            self._entries.clear()
            return removed
        removed = 0
        if token is not None and base_id is not None:
            key = self._key(token, base_id)
            if key in self._entries:
                del self._entries[key]
                removed = 1
            return removed
        # Invalidazione per prefisso (solo token o solo base)
        target_token_hash = hashlib.sha256(token.strip().encode("utf-8")).hexdigest()[:16] if token else None
        for key in list(self._entries.keys()):
            token_hash, key_base = key
            if (target_token_hash is None or token_hash == target_token_hash) and (
                base_id is None or key_base == base_id.strip()
            ):
                del self._entries[key]
                removed += 1
        return removed


# Istanze condivise a livello di processo: gli adapter vengono costruiti per-operazione,
# ma rate limit (per base) e cache metadata devono valere globalmente al processo.
_SHARED_RATE_LIMITER = AirtableRateLimiter(DEFAULT_RATE_LIMIT_PER_SECOND)
_SHARED_SCHEMA_CACHE = AirtableSchemaCache(DEFAULT_SCHEMA_CACHE_TTL_SECONDS)


def get_shared_rate_limiter() -> AirtableRateLimiter:
    """Restituisce il rate limiter condiviso (5 req/s per base, policy ufficiale)."""
    return _SHARED_RATE_LIMITER


def get_shared_schema_cache() -> AirtableSchemaCache:
    """Restituisce la cache condivisa per i metadata base/tabelle/campi."""
    return _SHARED_SCHEMA_CACHE


class AirtableAdapter(AirtablePort):
    """Adapter concreto per Airtable Web API v0 conforme ad AirtablePort."""

    def __init__(
        self,
        token: str,
        base_url: str = DEFAULT_AIRTABLE_BASE_URL,
        http_client: httpx.AsyncClient | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        default_base_id: str | None = None,  # legacy/deprecato: accettato per retrocompatibilità, non usato
        rate_limiter: AirtableRateLimiter | None = None,
        schema_cache: AirtableSchemaCache | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff_base_seconds: float = RETRY_BACKOFF_BASE_SECONDS,
        retry_backoff_cap_seconds: float = RETRY_BACKOFF_CAP_SECONDS,
        wait_seconds_on_429: float = DEFAULT_WAIT_SECONDS_ON_429,
        enable_rate_limiting: bool = True,
    ):
        if not token or not token.strip():
            raise ValueError("Il token di autenticazione Airtable (PAT) non può essere vuoto.")

        self._token = token.strip()
        self._base_url = base_url.rstrip("/")
        self._external_client = http_client
        self._timeout_seconds = timeout_seconds

        # ── Resilienza (rate limit, cache metadata, retry/backoff) ─────────────
        # Rate limiter e cache metadata sono OPT-IN: vanno cablati esplicitamente nei
        # punti di costruzione di produzione (es. AirtableConnectionService) con le
        # istanze condivise get_shared_rate_limiter() / get_shared_schema_cache(), così
        # il limite 5 req/s per base e la cache valgono a livello di processo senza
        # inquinare gli usi isolati (script, test) dello stesso adapter.
        if not enable_rate_limiting:
            self._rate_limiter: AirtableRateLimiter | None = None
        else:
            self._rate_limiter = rate_limiter
        self._schema_cache: AirtableSchemaCache | None = schema_cache
        self._max_retries = max(int(max_retries), 0)
        self._retry_backoff_base = float(retry_backoff_base_seconds)
        self._retry_backoff_cap = float(retry_backoff_cap_seconds)
        self._wait_seconds_on_429 = float(wait_seconds_on_429)

    def __repr__(self) -> str:
        # Invariante 10: Mai esporre token o segreti nel repr/log
        masked = f"{self._token[:4]}***" if len(self._token) > 4 else "***"
        return f"<AirtableAdapter base_url='{self._base_url}' token='{masked}'>"

    def _get_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _build_table_url(self, base_id: str, table_id_or_name: str) -> str:
        safe_base = quote(base_id.strip(), safe="")
        safe_table = quote(table_id_or_name.strip(), safe="")
        return f"{self._base_url}/{safe_base}/{safe_table}"

    def _handle_error_response(self, resp: httpx.Response) -> None:
        status = resp.status_code
        err_msg = ""
        err_type = None
        details: dict[str, Any] = {}

        try:
            body = resp.json()
            if isinstance(body, dict):
                error_obj = body.get("error")
                if isinstance(error_obj, dict):
                    err_msg = error_obj.get("message", "")
                    err_type = error_obj.get("type")
                    details = error_obj
                elif isinstance(error_obj, str):
                    err_msg = error_obj
                    details = {"error": error_obj}
                else:
                    details = body
        except Exception:
            err_msg = resp.text[:200]

        message = err_msg or f"Errore Airtable HTTP {status}"

        if status in (401, 403):
            raise AirtableAuthError(
                message=f"Autenticazione fallita su Airtable: {message}",
                status_code=status,
                error_type=err_type or "AUTHENTICATION_REQUIRED",
                details=details,
            )
        elif status == 404:
            raise AirtableNotFoundError(
                message=f"Risorsa Airtable non trovata: {message}",
                status_code=404,
                error_type=err_type or "NOT_FOUND",
                details=details,
            )
        elif status == 422:
            raise AirtableValidationError(
                message=f"Validazione fallita su Airtable: {message}",
                status_code=422,
                error_type=err_type or "INVALID_REQUEST",
                details=details,
            )
        elif status == 429:
            # Distinzione tra rate limit istantaneo (5 req/s) ed esaurimento quota mensile workspace
            err_lower = (message or "").lower()
            if any(k in err_lower for k in ("monthly", "quota", "plan limit", "limit reached", "billing")):
                logger.error("airtable_monthly_quota_exhausted: %s (Invariante 11: Escalation Umana)", message)
                raise AirtableQuotaExhaustedError(
                    message=f"Quota mensile chiamate API Airtable esaurita: {message}. Richiesto upgrade del piano o intervento umano.",
                    details=details,
                )

            retry_header = resp.headers.get("Retry-After")
            try:
                retry_after = float(retry_header) if retry_header else 30.0
            except ValueError:
                retry_after = 30.0
            raise AirtableRateLimitError(
                message=f"Limite di frequenza Airtable superato (5 req/s): {message}",
                retry_after=retry_after,
                details=details,
            )
        elif status >= 500:
            raise AirtableServerError(
                message=f"Errore interno server Airtable (HTTP {status}): {message}",
                status_code=status,
                error_type=err_type or "SERVER_ERROR",
                details=details,
            )
        else:
            raise AirtableError(
                message=message,
                status_code=status,
                error_type=err_type,
                details=details,
            )

    async def _sleep(self, delay: float) -> None:
        """Attesa tra i retry (separata per testabilità)."""
        if delay > 0:
            await asyncio.sleep(delay)

    def _backoff_delay(self, attempt: int) -> float:
        """Backoff esponenziale con jitter per 5xx ed errori di rete transienti."""
        return compute_backoff_delay(
            attempt,
            base_seconds=self._retry_backoff_base,
            cap_seconds=self._retry_backoff_cap,
        )

    async def _execute_request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        rate_limit_key: str | None = None,
    ) -> dict[str, Any]:
        headers = self._get_headers()
        timeout = httpx.Timeout(self._timeout_seconds)
        attempt = 0

        while True:
            # Rate limit ufficiale: 5 request/sec per base — le richieste concorrenti
            # vengono spaziate invece di martellare l'API (evita il 429 a monte).
            if rate_limit_key and self._rate_limiter is not None:
                await self._rate_limiter.acquire(rate_limit_key)

            try:
                if self._external_client:
                    resp = await self._external_client.request(
                        method=method,
                        url=url,
                        params=params,
                        json=json_data,
                        headers=headers,
                        timeout=timeout,
                    )
                else:
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        resp = await client.request(
                            method=method,
                            url=url,
                            params=params,
                            json=json_data,
                            headers=headers,
                        )
            except httpx.TimeoutException as exc:
                if attempt < self._max_retries:
                    await self._sleep(self._backoff_delay(attempt))
                    attempt += 1
                    continue
                raise AirtableNetworkError(f"Timeout durante la richiesta ad Airtable ({method} {url})") from exc
            except httpx.RequestError as exc:
                if attempt < self._max_retries:
                    await self._sleep(self._backoff_delay(attempt))
                    attempt += 1
                    continue
                raise AirtableNetworkError(f"Errore di rete durante la richiesta ad Airtable: {exc}") from exc

            if not resp.is_success:
                # Retry SOLO per 429 e 5xx secondo policy ufficiale; ogni altro status
                # (400/401/403/404/422/validation) fallisce immediatamente, senza retry.
                if is_retryable_status(resp.status_code) and attempt < self._max_retries:
                    await self._sleep(compute_retry_delay(resp, wait_seconds_on_429=self._wait_seconds_on_429))
                    attempt += 1
                    continue
                self._handle_error_response(resp)

            if not resp.content:
                return {}

            try:
                body = resp.json()
                if not isinstance(body, dict):
                    raise AirtableMalformedResponseError(
                        f"Risposta Airtable non conforme: atteso oggetto JSON dict, ricevuto {type(body).__name__}",
                        details={"raw_type": type(body).__name__},
                    )
                return body
            except (json.JSONDecodeError, ValueError) as exc:
                if isinstance(exc, AirtableMalformedResponseError):
                    raise
                raise AirtableMalformedResponseError(
                    f"Risposta Airtable non decodificabile come JSON valido: {exc}",
                    details={"status_code": resp.status_code},
                ) from exc

    # ── Implementazione AirtablePort ──────────────────────────────────────────

    async def list_records(
        self,
        base_id: str,
        table_id_or_name: str,
        params: ListRecordsParams | None = None,
    ) -> RecordPage:
        url = self._build_table_url(base_id, table_id_or_name)
        query_params: dict[str, Any] = {}
        # PAGINATION: page size massimo ufficiale (100) quando non specificato,
        # per ridurre il numero di round-trip.
        if params is not None and not params.page_size:
            params = params.model_copy(update={"page_size": 100})

        if params:
            if params.fields:
                query_params["fields[]"] = params.fields
            if params.filter_by_formula:
                query_params["filterByFormula"] = params.filter_by_formula
            if params.max_records is not None:
                query_params["maxRecords"] = params.max_records
            if params.page_size:
                query_params["pageSize"] = params.page_size
            if params.offset:
                query_params["offset"] = params.offset
            if params.view:
                query_params["view"] = params.view
            if params.cell_format:
                query_params["cellFormat"] = params.cell_format
            if params.time_zone:
                query_params["timeZone"] = params.time_zone
            if params.user_locale:
                query_params["userLocale"] = params.user_locale
            if params.sort:
                for idx, sort_item in enumerate(params.sort):
                    field_name = sort_item.get("field")
                    direction = sort_item.get("direction", "asc")
                    if field_name:
                        query_params[f"sort[{idx}][field]"] = field_name
                        query_params[f"sort[{idx}][direction]"] = direction

        raw = await self._execute_request("GET", url, params=query_params, rate_limit_key=base_id)
        raw_records = raw.get("records", [])

        records = [
            AirtableRecord(
                id=r["id"],
                created_time=r.get("createdTime"),
                fields=r.get("fields", {}),
            )
            for r in raw_records
            if "id" in r
        ]
        return RecordPage(records=records, offset=raw.get("offset"))

    async def list_all_records(
        self,
        base_id: str,
        table_id_or_name: str,
        params: ListRecordsParams | None = None,
        max_records: int | None = None,
    ) -> list[AirtableRecord]:
        """Recupera ricorsivamente tutte le pagine di record gestendo la paginazione internamente."""
        all_records: list[AirtableRecord] = []
        effective_params = params.model_copy() if params else ListRecordsParams()
        offset: str | None = effective_params.offset

        while True:
            effective_params.offset = offset
            if max_records is not None:
                remaining = max_records - len(all_records)
                if remaining <= 0:
                    break
                effective_params.page_size = min(remaining, 100)

            page = await self.list_records(base_id, table_id_or_name, params=effective_params)
            all_records.extend(page.records)

            if max_records is not None and len(all_records) >= max_records:
                all_records = all_records[:max_records]
                break

            if not page.has_more:
                break

            offset = page.offset

        return all_records

    async def iter_records(
        self,
        base_id: str,
        table_id_or_name: str,
        params: ListRecordsParams | None = None,
    ) -> AsyncIterator[AirtableRecord]:
        """Generatore asincrono per iterare i record pagina per pagina senza caricare tutto in memoria."""
        effective_params = params.model_copy() if params else ListRecordsParams()
        offset: str | None = effective_params.offset

        while True:
            effective_params.offset = offset
            page = await self.list_records(base_id, table_id_or_name, params=effective_params)
            for record in page.records:
                yield record

            if not page.has_more:
                break

            offset = page.offset

    async def get_record(
        self,
        base_id: str,
        table_id_or_name: str,
        record_id: str,
    ) -> AirtableRecord:
        base_url = self._build_table_url(base_id, table_id_or_name)
        safe_rec = quote(record_id.strip(), safe="")
        url = f"{base_url}/{safe_rec}"

        raw = await self._execute_request("GET", url, rate_limit_key=base_id)
        return AirtableRecord(
            id=raw["id"],
            created_time=raw.get("createdTime"),
            fields=raw.get("fields", {}),
        )

    async def create_record(
        self,
        base_id: str,
        table_id_or_name: str,
        request: CreateRecordRequest,
    ) -> AirtableRecord:
        url = self._build_table_url(base_id, table_id_or_name)
        payload = {
            "fields": request.fields,
            "typecast": request.typecast,
        }

        raw = await self._execute_request("POST", url, json_data=payload)
        return AirtableRecord(
            id=raw["id"],
            created_time=raw.get("createdTime"),
            fields=raw.get("fields", {}),
        )

    async def create_records(
        self,
        base_id: str,
        table_id_or_name: str,
        records: list[dict[str, Any]] | list[BatchRecordItem] | list[CreateRecordRequest],
        typecast: bool = False,
    ) -> list[AirtableRecord]:
        """Crea record in batch (sfruttando l'endpoint batch di Airtable fino a 10 record/request).
        Se records > 10, esegue il chunking automatico in blocchi da 10.
        """
        if not records:
            return []

        url = self._build_table_url(base_id, table_id_or_name)
        BATCH_SIZE = 10
        created_all: list[AirtableRecord] = []

        for i in range(0, len(records), BATCH_SIZE):
            chunk = records[i : i + BATCH_SIZE]
            chunk_payload = []
            for item in chunk:
                if isinstance(item, (BatchRecordItem, CreateRecordRequest)):
                    chunk_payload.append({"fields": item.fields})
                elif isinstance(item, dict):
                    fields = item.get("fields", item) if "fields" in item else item
                    chunk_payload.append({"fields": fields})
                else:
                    chunk_payload.append({"fields": getattr(item, "fields", {})})

            body = {"records": chunk_payload, "typecast": typecast}
            # BATCH: endpoint batch ufficiale (10 record/request) — una sola API call per chunk.
            raw = await self._execute_request("POST", url, json_data=body, rate_limit_key=base_id)
            for rec in raw.get("records", []):
                created_all.append(
                    AirtableRecord(
                        id=rec["id"],
                        created_time=rec.get("createdTime"),
                        fields=rec.get("fields", {}),
                    )
                )

        return created_all

    async def update_record(
        self,
        base_id: str,
        table_id_or_name: str,
        record_id: str,
        request: UpdateRecordRequest,
    ) -> AirtableRecord:
        base_url = self._build_table_url(base_id, table_id_or_name)
        safe_rec = quote(record_id.strip(), safe="")
        url = f"{base_url}/{safe_rec}"

        method = "PUT" if request.replace else "PATCH"
        payload = {
            "fields": request.fields,
            "typecast": request.typecast,
        }

        raw = await self._execute_request(method, url, json_data=payload, rate_limit_key=base_id)
        return AirtableRecord(
            id=raw["id"],
            created_time=raw.get("createdTime"),
            fields=raw.get("fields", {}),
        )

    async def update_records(
        self,
        base_id: str,
        table_id_or_name: str,
        records: list[dict[str, Any]] | list[BatchUpdateRecordItem],
        typecast: bool = False,
        replace: bool = False,
    ) -> list[AirtableRecord]:
        """Aggiorna record in batch (sfruttando l'endpoint batch di Airtable fino a 10 record/request).
        Se records > 10, esegue il chunking automatico in blocchi da 10.
        """
        if not records:
            return []

        url = self._build_table_url(base_id, table_id_or_name)
        method = "PUT" if replace else "PATCH"
        BATCH_SIZE = 10
        updated_all: list[AirtableRecord] = []

        for i in range(0, len(records), BATCH_SIZE):
            chunk = records[i : i + BATCH_SIZE]
            chunk_payload = []
            for item in chunk:
                if isinstance(item, BatchUpdateRecordItem):
                    chunk_payload.append({"id": item.id, "fields": item.fields})
                elif isinstance(item, dict):
                    chunk_payload.append({"id": item["id"], "fields": item.get("fields", {})})
                else:
                    chunk_payload.append({"id": getattr(item, "id"), "fields": getattr(item, "fields", {})})

            body = {"records": chunk_payload, "typecast": typecast}
            # BATCH: endpoint batch ufficiale (10 record/request) — una sola API call per chunk.
            raw = await self._execute_request(method, url, json_data=body, rate_limit_key=base_id)
            for rec in raw.get("records", []):
                updated_all.append(
                    AirtableRecord(
                        id=rec["id"],
                        created_time=rec.get("createdTime"),
                        fields=rec.get("fields", {}),
                    )
                )

        return updated_all

    async def delete_record(
        self,
        base_id: str,
        table_id_or_name: str,
        record_id: str,
    ) -> DeleteRecordResult:
        base_url = self._build_table_url(base_id, table_id_or_name)
        safe_rec = quote(record_id.strip(), safe="")
        url = f"{base_url}/{safe_rec}"

        raw = await self._execute_request("DELETE", url, rate_limit_key=base_id)
        return DeleteRecordResult(
            id=raw.get("id", record_id),
            deleted=bool(raw.get("deleted", True)),
        )

    async def delete_records(
        self,
        base_id: str,
        table_id_or_name: str,
        record_ids: list[str],
    ) -> list[DeleteRecordResult]:
        """Elimina record in batch (fino a 10 record/request con chunking automatico)."""
        if not record_ids:
            return []

        url = self._build_table_url(base_id, table_id_or_name)
        BATCH_SIZE = 10
        deleted_all: list[DeleteRecordResult] = []

        for i in range(0, len(record_ids), BATCH_SIZE):
            chunk_ids = record_ids[i : i + BATCH_SIZE]
            params = {"records[]": chunk_ids}
            # BATCH: endpoint batch ufficiale (10 record/request) — una sola API call per chunk.
            raw = await self._execute_request("DELETE", url, params=params, rate_limit_key=base_id)
            for rec in raw.get("records", []):
                deleted_all.append(
                    DeleteRecordResult(
                        id=rec.get("id", ""),
                        deleted=bool(rec.get("deleted", True)),
                    )
                )

        return deleted_all

    async def search_records(
        self,
        base_id: str,
        table_id_or_name: str,
        formula: str | None = None,
        max_records: int | None = None,
    ) -> list[AirtableRecord]:
        params = ListRecordsParams(
            filter_by_formula=formula,
            max_records=max_records,
            page_size=min(max_records or 100, 100),
        )
        return await self.list_all_records(base_id, table_id_or_name, params=params, max_records=max_records)


    async def get_base_schema(self, base_id: str) -> list[AirtableTable]:
        """Metadata base/tabelle/campi con cache breve (TTL + single-flight).

        Evita che 100 conversazioni simultanee eseguano tutte `GET /meta/bases/{id}/tables`
        prima di ogni operazione. I metadata cambiano raramente: TTL breve di default (5 min).
        I record dinamici NON passano mai da cache.
        """
        async def _load() -> list[AirtableTable]:
            return await self._fetch_base_schema_uncached(base_id)

        if self._schema_cache is None:
            return await _load()
        return await self._schema_cache.get_or_load(self._token, base_id, _load)

    async def invalidate_schema_cache(self, base_id: str | None = None) -> int:
        """Invalida la cache dei metadata (dopo modifiche strutturali o disconnessioni)."""
        if self._schema_cache is None:
            return 0
        return self._schema_cache.invalidate(token=self._token, base_id=base_id)

    async def _fetch_base_schema_uncached(self, base_id: str) -> list[AirtableTable]:
        safe_base = quote(base_id.strip(), safe="")
        url = f"{self._base_url}/meta/bases/{safe_base}/tables"
        raw = await self._execute_request("GET", url, rate_limit_key=base_id)
        raw_tables = raw.get("tables", [])

        tables: list[AirtableTable] = []
        for t in raw_tables:
            fields = [
                AirtableField(
                    id=f.get("id"),
                    name=f.get("name", ""),
                    type=f.get("type"),
                    description=f.get("description"),
                    options=f.get("options"),
                )
                for f in t.get("fields", [])
            ]
            tables.append(
                AirtableTable(
                    id=t["id"],
                    name=t.get("name", ""),
                    primary_field_id=t.get("primaryFieldId"),
                    fields=fields,
                    description=t.get("description"),
                )
            )
        return tables

    async def validate_table_schema(
        self,
        base_id: str,
        table_id_or_name: str,
        required_fields: list[str],
    ) -> SchemaValidationResult:
        try:
            tables = await self.get_base_schema(base_id)
        except AirtableAuthError as exc:
            return SchemaValidationResult(
                is_valid=False,
                error_message=(
                    f"Impossibile leggere lo schema della Base (verificare che il token possieda "
                    f"lo scope 'schema.bases:read'): {exc.message}"
                ),
            )
        except AirtableError as exc:
            return SchemaValidationResult(
                is_valid=False,
                error_message=f"Errore durante la lettura dello schema della Base: {exc.message}",
            )

        target_table: AirtableTable | None = None
        target_name_lower = table_id_or_name.strip().lower()
        for t in tables:
            if t.id.lower() == target_name_lower or t.name.lower() == target_name_lower:
                target_table = t
                break

        if not target_table:
            available_names = [f"'{t.name}' ({t.id})" for t in tables]
            return SchemaValidationResult(
                is_valid=False,
                error_message=(
                    f"Tabella '{table_id_or_name}' non trovata nella Base '{base_id}'. "
                    f"Tabelle disponibili: {', '.join(available_names)}"
                ),
            )

        available_field_names = [f.name for f in target_table.fields]
        available_field_names_lower = {f.name.lower() for f in target_table.fields}

        missing: list[str] = []
        for req in required_fields:
            if req.strip().lower() not in available_field_names_lower:
                missing.append(req)

        return SchemaValidationResult(
            is_valid=len(missing) == 0,
            table_id=target_table.id,
            table_name=target_table.name,
            missing_fields=missing,
            available_fields=available_field_names,
            error_message=(
                f"Campi mappati mancanti nella tabella '{target_table.name}': {', '.join(missing)}"
                if missing
                else None
            ),
        )

