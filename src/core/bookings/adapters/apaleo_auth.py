"""Client di autenticazione OAuth2 per Apaleo (Identity API).

Responsabilità:
1. Gestione del ciclo di vita dei token OAuth2 (ottenimento iniziale, caching in memoria, scadenza con buffer di sicurezza).
2. Supporto trasparente di entrambi i flow supportati da Apaleo:
   - Authorization Code / Refresh Token Flow (flow primario multi-tenant per app connesse e Apaleo Store).
   - Client Credentials Flow (flow M2M privato per integrazioni con singolo hotel).
3. Concorrenza coroutine-safe con pattern Double-Checked Locking su asyncio.Lock per evitare "token storms" (richieste duplicate contemporanee all'Identity server).
4. Gestione degli errori conformi a RFC 6749: invalid_grant, re-autenticazione richiesta, fallimenti di rete.
5. Zero Secrets Logging: client_secret, access_token e refresh_token non vengono mai esposti nei log o nelle rappresentazioni stringa.
6. Callback di persistenza cifrata (tenant-scoped) per salvare su DB i token aggiornati o ruotati.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import time
import uuid
from typing import Any, Awaitable, Callable

import httpx

logger = logging.getLogger(__name__)

APALEO_DEFAULT_TOKEN_URL = "https://identity.apaleo.com/connect/token"
APALEO_DEFAULT_AUTHORIZE_URL = "https://identity.apaleo.com/connect/authorize"
DEFAULT_CLOCK_SKEW_SECONDS = 60.0  # Buffer di sicurezza per prevenire scadenze in volo


class ApaleoAuthError(Exception):
    """Errore generico di autenticazione OAuth2 Apaleo."""
    pass


class ApaleoInvalidGrantError(ApaleoAuthError):
    """Sollevata quando il refresh token o l'authorization code non è valido, è scaduto o è stato revocato.

    Richiede che l'amministratore del tenant ripeta il flusso di autorizzazione interattivo (re-authentication).
    """
    pass


class ApaleoTokenRequestError(ApaleoAuthError):
    """Errore temporaneo o di trasporto durante la richiesta del token all'Identity server (5xx o network)."""
    pass


class ApaleoOAuthClient:
    """Gestore tenant-scoped del ciclo di vita dei token OAuth2 per Apaleo."""

    def __init__(
        self,
        organization_id: uuid.UUID | str,
        client_id: str,
        client_secret: str,
        refresh_token: str | None = None,
        initial_access_token: str | None = None,
        initial_expires_at: float | None = None,
        token_url: str = APALEO_DEFAULT_TOKEN_URL,
        clock_skew_seconds: float = DEFAULT_CLOCK_SKEW_SECONDS,
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
        on_token_refreshed: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ):
        if not organization_id:
            raise ValueError("organization_id obbligatorio per ApaleoOAuthClient")
        if not client_id or not client_id.strip():
            raise ValueError("client_id obbligatorio per ApaleoOAuthClient")
        if not client_secret or not client_secret.strip():
            raise ValueError("client_secret obbligatorio per ApaleoOAuthClient")

        self.organization_id = str(organization_id)
        self._client_id = client_id.strip()
        self._client_secret = client_secret.strip()
        self._token_url = token_url
        self._clock_skew_seconds = float(clock_skew_seconds)
        self._timeout = float(timeout_seconds)

        # Stato del token
        self._access_token: str | None = initial_access_token
        self._expires_at: float | None = initial_expires_at
        self._refresh_token: str | None = refresh_token.strip() if refresh_token else None
        self._is_invalidated: bool = False

        # Concorrenza: Lock per prevenire token storm concorrenti
        self._lock = asyncio.Lock()

        # Callback per persistenza cifrata at-rest delle credenziali aggiornate
        self._on_token_refreshed = on_token_refreshed

        # Gestione client HTTP (esterno o interno)
        self._client = client
        self._owns_client = False
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
            self._owns_client = True

    @property
    def grant_type(self) -> str:
        """Indica il tipo di grant che verrà utilizzato per ottenere o rinnovare il token."""
        return "refresh_token" if self._refresh_token else "client_credentials"

    @property
    def has_refresh_token(self) -> bool:
        """Indica se l'istanza dispone di un refresh token per il rinnovo delegato."""
        return bool(self._refresh_token)

    def is_token_valid(self) -> bool:
        """Verifica se l'access token corrente è presente e non prossimo alla scadenza."""
        if not self._access_token or self._expires_at is None:
            return False
        # Considera scaduto se siamo all'interno del buffer di clock skew
        return time.time() < (self._expires_at - self._clock_skew_seconds)

    def _get_basic_auth_header(self) -> str:
        """Genera l'header di autenticazione HTTP Basic per il token endpoint senza loggare credenziali."""
        raw = f"{self._client_id}:{self._client_secret}"
        encoded = base64.b64encode(raw.encode()).decode()
        return f"Basic {encoded}"

    async def get_access_token(self, force_refresh: bool = False) -> str:
        """Restituisce un access token valido, rinnovandolo preventivamente se necessario.

        Implementa il pattern Double-Checked Locking:
        1. Fast-path: se il token è valido e non è forzato il refresh, ritorna subito senza acquisire il lock.
        2. Slow-path: acquisisce il lock, riverifica la validità (per evitare che coroutine concorrenti
           ripetano la richiesta HTTP dopo che la prima ha completato il refresh), e se ancora necessario
           effettua la chiamata all'Identity server di Apaleo.
        """
        # Fast path lock-free
        if not force_refresh and self.is_token_valid():
            return self._access_token  # type: ignore[return-value]

        async with self._lock:
            # Double-check all'interno del blocco atomico
            if not force_refresh and self.is_token_valid():
                return self._access_token  # type: ignore[return-value]

            if self._is_invalidated:
                raise ApaleoInvalidGrantError(
                    f"Autenticazione Apaleo revocata o non valida per org {self.organization_id}. "
                    "Richiede nuova autorizzazione del tenant."
                )

            return await self._fetch_token_locked()

    async def _fetch_token_locked(self) -> str:
        """Esegue la chiamata HTTP all'endpoint token sotto protezione del lock."""
        headers = {
            "Authorization": self._get_basic_auth_header(),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

        if self._refresh_token:
            # Flow A: Refresh Token (Authorization Code Grant con offline_access)
            payload = {
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
            }
            operation = "refresh_token"
        else:
            # Flow B: Client Credentials (M2M per singolo hotel)
            payload = {
                "grant_type": "client_credentials",
            }
            operation = "client_credentials"

        logger.info(
            "Richiesta OAuth token ad Apaleo per org %s (flow=%s)",
            self.organization_id,
            operation,
        )

        try:
            start_t = time.perf_counter()
            response = await self._client.post(
                self._token_url,
                data=payload,
                headers=headers,
            )
            duration_ms = int((time.perf_counter() - start_t) * 1000)
        except httpx.TimeoutException as exc:
            logger.error(
                "Timeout (%ds) durante richiesta OAuth Apaleo per org %s: %s",
                self._timeout,
                self.organization_id,
                exc,
            )
            raise ApaleoTokenRequestError(f"Timeout connessione verso Apaleo Identity: {exc}") from exc
        except httpx.RequestError as exc:
            logger.error(
                "Errore di rete durante richiesta OAuth Apaleo per org %s: %s",
                self.organization_id,
                exc,
            )
            raise ApaleoTokenRequestError(f"Errore di connessione verso Apaleo Identity: {exc}") from exc

        return await self._handle_token_response(response, operation, duration_ms)

    async def _handle_token_response(
        self,
        response: httpx.Response,
        operation: str,
        duration_ms: int,
    ) -> str:
        """Analizza la risposta del token endpoint e gestisce gli errori standard RFC 6749."""
        status = response.status_code

        if status == 200:
            try:
                data = response.json()
            except Exception as exc:
                logger.error(
                    "Risposta Apaleo Identity non parsabile come JSON per org %s: %s",
                    self.organization_id,
                    exc,
                )
                raise ApaleoTokenRequestError("Risposta del server token Apaleo non valida") from exc

            new_access_token = data.get("access_token")
            expires_in = data.get("expires_in")
            new_refresh_token = data.get("refresh_token")

            if not new_access_token or not expires_in:
                logger.error("Token response incompleta da Apaleo per org %s", self.organization_id)
                raise ApaleoAuthError("Risposta token Apaleo priva di access_token o expires_in")

            now = time.time()
            self._access_token = str(new_access_token)
            self._expires_at = now + float(expires_in)
            self._is_invalidated = False

            # Se il server ha ruotato il refresh token, aggiorniamo il riferimento
            rotated = False
            if new_refresh_token:
                if new_refresh_token != self._refresh_token:
                    rotated = True
                    self._refresh_token = str(new_refresh_token)

            logger.info(
                "OAuth token Apaleo ottenuto con successo per org %s (flow=%s, expires_in=%ds, latency=%dms, refresh_rotated=%s)",
                self.organization_id,
                operation,
                expires_in,
                duration_ms,
                rotated,
            )

            # Invoca la callback di persistenza se registrata
            if self._on_token_refreshed:
                try:
                    update_envelope = {
                        "access_token": self._access_token,
                        "expires_at": self._expires_at,
                    }
                    if self._refresh_token:
                        update_envelope["refresh_token"] = self._refresh_token
                    await self._on_token_refreshed(update_envelope)
                except Exception as exc:
                    logger.warning(
                        "Callback on_token_refreshed fallita per org %s: %s",
                        self.organization_id,
                        exc,
                    )

            return self._access_token

        # Gestione errori OAuth 2.0
        error_code = "unknown_error"
        error_desc = response.text
        try:
            err_json = response.json()
            error_code = err_json.get("error", error_code)
            error_desc = err_json.get("error_description", error_desc)
        except Exception:
            pass

        logger.warning(
            "Apaleo Identity token endpoint errore HTTP %d (code=%s) per org %s",
            status,
            error_code,
            self.organization_id,
        )

        if status == 400 and error_code in ("invalid_grant", "unauthorized_client"):
            # Il refresh token è scaduto, è stato revocato dall'hotel o il client è stato disattivato
            self._is_invalidated = True
            self._access_token = None
            self._expires_at = None
            raise ApaleoInvalidGrantError(
                f"Grant OAuth Apaleo non valido o revocato (code={error_code}): {error_desc}. "
                "È richiesta una nuova autorizzazione da parte del tenant."
            )

        if status in (401, 403):
            raise ApaleoAuthError(
                f"Autenticazione client fallita verso Apaleo (HTTP {status}): {error_code} - {error_desc}"
            )

        if status >= 500:
            raise ApaleoTokenRequestError(
                f"Apaleo Identity server error (HTTP {status}): {error_code}"
            )

        raise ApaleoAuthError(f"Errore inatteso token Apaleo (HTTP {status}): {error_code} - {error_desc}")

    async def exchange_authorization_code(
        self,
        code: str,
        redirect_uri: str,
    ) -> dict[str, Any]:
        """Scambia un authorization code iniziale con access token e refresh token (Setup flow)."""
        if not code or not code.strip():
            raise ValueError("code obbligatorio per lo scambio authorization_code")
        if not redirect_uri or not redirect_uri.strip():
            raise ValueError("redirect_uri obbligatorio per lo scambio authorization_code")

        async with self._lock:
            headers = {
                "Authorization": self._get_basic_auth_header(),
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            }
            payload = {
                "grant_type": "authorization_code",
                "code": code.strip(),
                "redirect_uri": redirect_uri.strip(),
            }

            try:
                res = await self._client.post(self._token_url, data=payload, headers=headers)
            except Exception as exc:
                raise ApaleoTokenRequestError(f"Errore di rete nello scambio authorization_code: {exc}") from exc

            if res.status_code != 200:
                err_text = res.text
                try:
                    err_json = res.json()
                    err_text = f"{err_json.get('error')}: {err_json.get('error_description')}"
                except Exception:
                    pass
                raise ApaleoAuthError(f"Scambio authorization_code fallito (HTTP {res.status_code}): {err_text}")

            data = res.json()
            new_access_token = data.get("access_token")
            expires_in = data.get("expires_in")
            new_refresh_token = data.get("refresh_token")

            now = time.time()
            self._access_token = str(new_access_token)
            self._expires_at = now + float(expires_in)
            if new_refresh_token:
                self._refresh_token = str(new_refresh_token)
            self._is_invalidated = False

            if self._on_token_refreshed:
                try:
                    await self._on_token_refreshed({
                        "access_token": self._access_token,
                        "expires_at": self._expires_at,
                        "refresh_token": self._refresh_token,
                    })
                except Exception as exc:
                    logger.warning("Callback on_token_refreshed fallita dopo code exchange: %s", exc)

            return {
                "access_token": self._access_token,
                "expires_in": expires_in,
                "token_type": data.get("token_type", "Bearer"),
                "refresh_token": self._refresh_token,
                "scope": data.get("scope"),
            }

    async def close(self) -> None:
        """Chiude il client HTTP se è stato istanziato internamente."""
        if self._owns_client and self._client:
            await self._client.aclose()

    def __repr__(self) -> str:
        """Rappresentazione stringa sicura che maschera segreti e token."""
        return (
            f"<ApaleoOAuthClient org_id='{self.organization_id}' "
            f"client_id='{self._client_id}' "
            f"flow='{self.grant_type}' "
            f"has_refresh_token={bool(self._refresh_token)} "
            f"is_valid={self.is_token_valid()}>"
        )

    def __str__(self) -> str:
        return self.__repr__()
