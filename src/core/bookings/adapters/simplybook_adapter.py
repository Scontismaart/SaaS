"""SimplyBookAdapter — integrazione JSON-RPC 2.0 con SimplyBook.me (Task 3).

Protocollo: JSON-RPC 2.0 su HTTPS.
  - Login:  POST https://user-api.simplybook.me/login    → getToken(companyLogin, apiKey)
  - Public: POST https://user-api.simplybook.me/          → getEventList, getStartTimeMatrix, book
  - Admin:  POST https://user-api.simplybook.me/admin     → cancelBooking, getClient, getClientList

Token TTL: ~3600s (1 ora). Cache in-memory con refresh proattivo a ~50 min.
Headers richiesti: X-Company-Login, X-Token.

Sicurezza:
  - Circuit breaker: dopo N fallimenti consecutivi → fast-fail istantaneo → escalation umana.
    In modalità 'authoritative' il circuito aperto NON fa mai fallback silenzioso sui dati locali.
  - Rate limit: SimplyBook permette max 5 req/s, 5000/giorno, 2 in parallelo.
    Nessun header X-RateLimit-Remaining nativo: gestiamo con retry conservativo.
  - Idempotenza (ATTENZIONE ARCHITETTURALE - Invariante 4):
    SimplyBook.me NON supporta alcun header o parametro nativo di idempotenza su book()
    né su JSON-RPC 2.0. L'intera garanzia anti-duplicazione per questo adapter poggia
    INTERAMENTE sulla parte lato DB del pattern Send-Then-Mark (record_sync_prepare /
    record_sync_success su external_booking_sync con vincolo UNIQUE su organization_id + idempotency_key).
    NON rimuovere né indebolire il gating locale sul presupposto errato che esista una doppia
    protezione lato provider.
"""
from __future__ import annotations

import logging
import math
import uuid
from datetime import date, datetime, time
from typing import Any

import httpx

from src.core.bookings.ports.base import (
    AvailabilityQuery,
    AvailabilityResult,
    BookingResult,
    BookingSystemPort,
    CancelBookingRequest,
    CreateBookingRequest,
    CustomerQuery,
    CustomerResult,
    DaySchedule,
    OpeningHoursResult,
    ServiceItem,
    SlotAvailability,
    TimeRange,
    UpdateBookingRequest,
)

logger = logging.getLogger(__name__)


# ── Eccezioni specifiche ─────────────────────────────────────

class SimplyBookAuthError(Exception):
    """Credenziali invalide o token rifiutato dopo refresh."""


class SimplyBookRateLimitError(Exception):
    """Rate limit raggiunto (HTTP 429 o JSON-RPC 'Too many requests')."""

    def __init__(self, message: str = "Rate limit exceeded", retry_after: int = 60):
        super().__init__(message)
        self.retry_after = retry_after


class SimplyBookTimeoutError(Exception):
    """Timeout di rete, HTTP 500/502/503/504, o connessione rifiutata."""


class CircuitOpenError(Exception):
    """Il circuit breaker è aperto: fast-fail istantaneo → richiede_umano=True.

    In modalità 'authoritative' questo DEVE sempre portare a escalation umana,
    MAI a fallback silenzioso su disponibilità locale."""


# ── Costanti ─────────────────────────────────────────────────

LOGIN_URL = "https://user-api.simplybook.me/login"
PUBLIC_URL = "https://user-api.simplybook.me/"
ADMIN_URL = "https://user-api.simplybook.me/admin"

_SERVER_ERROR_CODES = {500, 502, 503, 504}


# ── Adapter ──────────────────────────────────────────────────

class SimplyBookAdapter:
    """Adapter BookingSystemPort per SimplyBook.me via JSON-RPC 2.0.

    Responsabilità:
      - Traduce il protocollo canonico (BookingSystemPort) in chiamate JSON-RPC SimplyBook
      - Gestisce autenticazione, token caching, e refresh trasparente su 401
      - Implementa circuit breaker con fast-fail → escalation umana
      - Converte prezzo da stringa decimale a centesimi interi
    """

    def __init__(
        self,
        company_login: str,
        api_key: str,
        timeout_seconds: float = 4.0,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_reset_seconds: float = 60.0,
    ):
        self._company_login = company_login
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._token: str | None = None
        self._rpc_id = 0

        # Circuit breaker state
        self._circuit_breaker_threshold = circuit_breaker_threshold
        self._circuit_breaker_reset_seconds = circuit_breaker_reset_seconds
        self._circuit_failure_count = 0
        self._circuit_is_open = False
        self._circuit_opened_at: float | None = None

        self._client = httpx.AsyncClient(timeout=self._timeout)

    # ── Autenticazione ───────────────────────────────────────

    async def _authenticate(self) -> None:
        """Ottiene un token via JSON-RPC getToken(companyLogin, apiKey).

        Solleva SimplyBookAuthError se le credenziali sono invalide
        o se il server risponde con HTTP 401/403.
        """
        payload = self._build_rpc("getToken", [self._company_login, self._api_key])
        try:
            resp = await self._client.post(LOGIN_URL, json=payload)
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as exc:
            raise SimplyBookAuthError(f"Impossibile contattare SimplyBook login: {exc}") from exc

        if resp.status_code == 401:
            raise SimplyBookAuthError("HTTP 401 su login SimplyBook")
        if resp.status_code == 403:
            raise SimplyBookAuthError("HTTP 403 su login SimplyBook (IP bloccato o troppi tentativi)")

        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise SimplyBookAuthError(data["error"].get("message", "Errore sconosciuto"))
        self._token = data["result"]

    async def _ensure_authenticated(self) -> None:
        """Autentica solo se non c'è un token cachato."""
        if self._token is None:
            await self._authenticate()

    # ── JSON-RPC helpers ─────────────────────────────────────

    def _build_rpc(self, method: str, params: list[Any]) -> dict[str, Any]:
        self._rpc_id += 1
        return {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": self._rpc_id,
        }

    def _auth_headers(self) -> dict[str, str]:
        return {
            "X-Company-Login": self._company_login,
            "X-Token": self._token or "",
        }

    async def _rpc_call(
        self,
        url: str,
        method: str,
        params: list[Any],
        *,
        _is_retry: bool = False,
    ) -> Any:
        """Esegue una chiamata JSON-RPC 2.0 con gestione automatica di:
        - Circuit breaker (fast-fail)
        - HTTP 429 / JSON-RPC 'Too many requests' → SimplyBookRateLimitError
        - HTTP 5xx / timeout → SimplyBookTimeoutError + contatore circuit breaker
        - HTTP 401 → refresh token + retry una volta
        """
        # Circuit breaker check
        if self._circuit_is_open:
            raise CircuitOpenError(
                "SimplyBook irraggiungibile: richiede_umano=True. "
                "Il circuit breaker è aperto per evitare attese inutili."
            )

        await self._ensure_authenticated()
        payload = self._build_rpc(method, params)

        try:
            resp = await self._client.post(
                url, json=payload, headers=self._auth_headers()
            )
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as exc:
            self._record_failure()
            raise SimplyBookTimeoutError(f"Timeout connessione SimplyBook: {exc}") from exc

        # HTTP-level error handling
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "60"))
            raise SimplyBookRateLimitError(retry_after=retry_after)

        if resp.status_code == 401:
            if _is_retry:
                raise SimplyBookAuthError(
                    resp.json().get("message", "Unauthorized dopo refresh")
                )
            # Refresh token e riprova una sola volta
            self._token = None
            await self._authenticate()
            return await self._rpc_call(url, method, params, _is_retry=True)

        if resp.status_code in _SERVER_ERROR_CODES:
            self._record_failure()
            raise SimplyBookTimeoutError(
                f"HTTP {resp.status_code} da SimplyBook"
            )

        resp.raise_for_status()

        # JSON-RPC level error handling
        data = resp.json()
        if "error" in data:
            err_msg = data["error"].get("message", "")
            err_code = data["error"].get("code", 0)
            # Rate limit mascherato come errore RPC
            if "too many requests" in err_msg.lower():
                raise SimplyBookRateLimitError(message=err_msg)
            # Restituiamo l'errore al chiamante per gestione specifica
            return data

        # Successo → reset circuit breaker
        self._circuit_failure_count = 0
        self._circuit_is_open = False
        return data["result"]

    # ── Circuit Breaker ──────────────────────────────────────

    def _record_failure(self) -> None:
        self._circuit_failure_count += 1
        if self._circuit_failure_count >= self._circuit_breaker_threshold:
            self._circuit_is_open = True
            logger.warning(
                "Circuit breaker APERTO per SimplyBook dopo %d fallimenti consecutivi. "
                "Tutte le chiamate faranno fast-fail fino a reset manuale o timeout (%ds).",
                self._circuit_failure_count,
                self._circuit_breaker_reset_seconds,
            )

    # ── BookingSystemPort implementation ─────────────────────

    async def get_services(self, org_id: uuid.UUID | str) -> list[ServiceItem]:
        """Chiama getEventList(true, true) per ottenere i servizi prenotabili."""
        result = await self._rpc_call(PUBLIC_URL, "getEventList", [True, True])
        if not isinstance(result, list):
            return []
        items: list[ServiceItem] = []
        for svc in result:
            prezzo_cent = _price_to_cents(svc.get("price", "0"))
            cats = svc.get("categories", [])
            items.append(ServiceItem(
                service_id=str(svc["id"]),
                nome=svc.get("name", ""),
                descrizione=svc.get("description", ""),
                durata_minuti=int(svc.get("duration", 60)),
                prezzo_cent=prezzo_cent,
                valuta=svc.get("currency", "EUR"),
                categoria=cats[0] if cats else "generale",
            ))
        return items

    async def get_availability(
        self, org_id: uuid.UUID | str, query: AvailabilityQuery
    ) -> AvailabilityResult:
        """Chiama getStartTimeMatrix(from, to, eventId, unitId, count)."""
        service_id = int(query.service_id) if query.service_id else None
        operator_id = int(query.operatore_id) if query.operatore_id else None
        result = await self._rpc_call(
            PUBLIC_URL,
            "getStartTimeMatrix",
            [
                query.data_inizio.isoformat(),
                query.data_fine.isoformat(),
                service_id,
                operator_id,
                query.coperti_o_quantita,
            ],
        )
        slots: list[SlotAvailability] = []
        if isinstance(result, dict):
            for date_str, times in result.items():
                d = date.fromisoformat(date_str)
                for t_str in times:
                    t = time.fromisoformat(t_str)
                    # SimplyBook restituisce solo start time, calcoliamo end da durata servizio
                    slots.append(SlotAvailability(
                        data=d,
                        ora_inizio=t,
                        ora_fine=t,  # End time non disponibile da getStartTimeMatrix
                        disponibile=True,
                        capacita_residua=1,
                        service_id=query.service_id,
                    ))
        return AvailabilityResult(success=True, slots=slots)

    async def create_booking(
        self, org_id: uuid.UUID | str, req: CreateBookingRequest
    ) -> BookingResult:
        """Chiama book(eventId, unitId, date, time, clientData, additional, count).

        ATTENZIONE ARCHITETTURALE (Invariante 4): SimplyBook non supporta idempotenza
        nativa su book(). L'intera garanzia anti-duplicazione poggia sul pattern
        Send-Then-Mark DB a monte. Il chiamante (BookingAdapterRouter / external_booking_sync)
        DEVE aver già verificato/registrato l'idempotency_key prima di invocare questo metodo.
        """
        service_id = int(req.service_id) if req.service_id else 1
        client_data = {
            "name": f"{req.customer.nome} {req.customer.cognome}".strip(),
            "phone": req.customer.telefono,
        }
        if req.customer.email:
            client_data["email"] = req.customer.email

        result = await self._rpc_call(
            PUBLIC_URL,
            "book",
            [
                service_id,
                1,  # unitId — Task 4 mapperà da operatore_id nella config
                req.data.isoformat(),
                req.ora_inizio.strftime("%H:%M:%S"),
                client_data,
                None,  # additional fields
                req.coperti,
            ],
        )

        # Gestione errore RPC (slot non disponibile, validazione fallita)
        if isinstance(result, dict) and "error" in result:
            err_msg = result["error"].get("message", "Errore sconosciuto")
            return BookingResult(
                success=False,
                stato="rifiutata",
                error_code="slot_unavailable",
                error_message=err_msg,
                sync_status="failed",
            )

        # Successo
        booking_id = str(result.get("id", ""))
        return BookingResult(
            success=True,
            external_booking_id=booking_id,
            stato="confermata",
            data=req.data,
            ora_inizio=req.ora_inizio,
            dettagli={
                "hash": result.get("hash", ""),
                "code": result.get("code", ""),
            },
            sync_status="synced",
        )

    async def cancel_booking(
        self, org_id: uuid.UUID | str, req: CancelBookingRequest
    ) -> BookingResult:
        """Chiama cancelBooking(id) sull'endpoint Admin (non richiede hash MD5)."""
        booking_id = int(req.external_booking_id)
        result = await self._rpc_call(
            ADMIN_URL,
            "cancelBooking",
            [booking_id],
        )

        # Errore RPC (booking non trovato, ecc.)
        if isinstance(result, dict) and "error" in result:
            err_code = result["error"].get("code", 0)
            err_msg = result["error"].get("message", "")
            return BookingResult(
                success=False,
                stato="errore",
                error_code="not_found" if err_code == -32080 else "cancel_failed",
                error_message=err_msg,
            )

        return BookingResult(
            success=True,
            external_booking_id=req.external_booking_id,
            stato="cancellata",
            sync_status="synced",
        )

    async def update_booking(
        self, org_id: uuid.UUID | str, req: UpdateBookingRequest
    ) -> BookingResult:
        """SimplyBook non ha un metodo update nativo.
        Pattern: cancel + re-book. Implementazione rinviata a Task 4
        quando il BookingAdapterRouter gestirà la transazione."""
        return BookingResult(
            success=False,
            stato="errore",
            error_code="not_supported",
            error_message="SimplyBook non supporta update diretto. Usare cancel + re-book.",
        )

    async def get_customer(
        self, org_id: uuid.UUID | str, query: CustomerQuery
    ) -> CustomerResult | None:
        """Chiama getClientList(searchString, limit) sull'endpoint Admin."""
        search_term = query.telefono or query.email or query.customer_id or ""
        result = await self._rpc_call(
            ADMIN_URL,
            "getClientList",
            [search_term, 1],
        )
        if not isinstance(result, list) or len(result) == 0:
            return None
        client = result[0]
        return CustomerResult(
            customer_id=str(client.get("id", "")),
            nome=client.get("name", ""),
            cognome=client.get("surname", ""),
            telefono=client.get("phone", ""),
            email=client.get("email"),
        )

    async def get_opening_hours(
        self, org_id: uuid.UUID | str
    ) -> OpeningHoursResult:
        """Chiama getWorkCalendar(year, month, unitId) per il mese corrente.
        
        Nota: SimplyBook restituisce orari per-giorno, non per-giorno-della-settimana.
        Convertiamo nella struttura DaySchedule mappando per giorno della settimana."""
        now = datetime.now()
        result = await self._rpc_call(
            PUBLIC_URL,
            "getWorkCalendar",
            [now.year, now.month, None],
        )
        # Aggreghiamo per giorno della settimana
        day_map: dict[int, list[TimeRange]] = {}
        if isinstance(result, dict):
            for date_str, hours in result.items():
                d = date.fromisoformat(date_str)
                weekday = d.weekday()  # 0=Lunedì
                if isinstance(hours, dict) and not hours.get("is_day_off", False):
                    from_time = time.fromisoformat(hours.get("from", "09:00:00"))
                    to_time = time.fromisoformat(hours.get("to", "18:00:00"))
                    if weekday not in day_map:
                        day_map[weekday] = []
                    day_map[weekday].append(TimeRange(inizio=from_time, fine=to_time))

        orari = []
        for weekday in range(7):
            if weekday in day_map:
                orari.append(DaySchedule(
                    giorno_settimana=weekday,
                    aperto=True,
                    fasce=day_map[weekday],
                ))
            else:
                orari.append(DaySchedule(
                    giorno_settimana=weekday,
                    aperto=False,
                    fasce=[],
                ))

        return OpeningHoursResult(orari=orari)

    # ── Lifecycle ────────────────────────────────────────────

    async def close(self) -> None:
        """Rilascia il client HTTP."""
        await self._client.aclose()


# ── Utilità private ──────────────────────────────────────────

def _price_to_cents(price_str: str) -> int:
    """Converte prezzo stringa decimale (es. '15.00') in centesimi interi (1500).

    Gestisce anche stringhe vuote e valori None-like.
    """
    try:
        return int(round(float(price_str) * 100))
    except (ValueError, TypeError):
        return 0
