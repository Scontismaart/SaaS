"""Servizio applicativo per la gestione dei Webhook Airtable.

Implementa il meccanismo ufficiale descritto nella documentazione Airtable Webhooks API
(https://airtable.com/developers/web/api/webhooks-overview):

- NOTIFICA "THIN PING": Airtable invia un POST contenente SOLO `base.id`, `webhook.id` e
  `timestamp`. La notifica NON contiene tipi di evento, record o tabelle: i cambiamenti
  devono essere recuperati a parte da `GET /v0/bases/{baseId}/webhooks/{webhookId}/payloads`
  usando un cursore monotono per webhook.

- AUTENTICAZIONE UFFICIALE: header `X-Airtable-Content-MAC` = `hmac-sha256=` + HMAC-SHA256
  (esadecimale) del body grezzo, calcolato con la chiave `macSecretBase64` (fornita UNA sola
  volta alla creazione del webhook) DECODIFICATA da Base64. Verifica in tempo costante.

- RISPOSTA UFFICIALE: 200 o 204 con body vuoto, entro pochi istanti, senza elaborazione
  pesante nella request HTTP.

Conforme a:
- Invariante 1 (Tenant Isolation): Identifica il tenant unicamente dal webhook_id registrato
  nel DB (server-side), senza fidarsi di organization_id o base_id inviati nel payload HTTP.
- Invariante 3 (Webhook Latency): Acknowledgment rapido (HTTP 200, body vuoto); elaborazione
  pesante (fetch payloads, trasformazione) solo in background.
- Invariante 4 (Idempotency Everywhere): Deduplicazione atomica su
  (organization_id, webhook_id, external_event_id), dove external_event_id deriva dal campo
  `timestamp` della notifica (l'unico identificatore che il payload ufficiale garantisce;
  i retry di Airtable re-inviano un body identico). Fallback: hash del body grezzo.
- Invariante 5 (No Direct Privileged Actions): Filtro deterministico sui payload: vengono
  elaborati solo i cambiamenti relativi a tabelle mappate e attive per il tenant; tutto il
  resto viene ignorato in fail-safe (nessuna sincronizzazione automatica di ogni modifica).
- Invariante 9 (Osservabilità): Tracciamento con org_id, base_id, webhook_id ed
  external_event_id senza leak di PII o segreti.
- Invariante 10 (Sicurezza Segreti): Verifica crittografica costante (hmac.compare_digest)
  della firma X-Airtable-Content-MAC; segreto MAC cifrato a riposo nel repository.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import uuid
from typing import Any
from urllib.parse import quote

import httpx

from src.integrations.airtable.adapter import (
    DEFAULT_WAIT_SECONDS_ON_429,
    compute_backoff_delay,
    compute_retry_delay,
    get_shared_rate_limiter,
    is_retryable_status,
)
from src.integrations.airtable.errors import (
    AirtableAuthError,
    AirtableError,
    AirtableMalformedWebhookError,
    AirtableNetworkError,
    AirtableNotFoundError,
    AirtableRateLimitError,
    AirtableServerError,
    AirtableUnknownIntegrationError,
    AirtableWebhookAuthError,
    AirtableWebhookOwnershipError,
    AirtableWebhookProcessingError,
)
from src.integrations.airtable.models import (
    AirtableWebhookEvent,
    AirtableWebhookSubscription,
)
from src.integrations.airtable.repository import (
    AirtableMappingRepository,
    AirtableWebhookRepository,
)

logger = logging.getLogger(__name__)

# Tipo evento persistito per le notifiche ping: il payload ufficiale non espone tipi di
# evento (la classificazione avviene a livello di payload recuperato, non di notifica).
NOTIFICATION_PING_EVENT_TYPE = "notification_ping"

# Sicurezza pagination: limite massimo di pagine di payload recuperate per singolo evento
# (rate limit ufficiale: 5 req/s per base; payload residui con mightHaveMore vengono
# recuperati dagli eventi successivi grazie al cursore avanzato).
MAX_PAYLOAD_PAGES_PER_EVENT = 10


def _decode_mac_secret(secret_str: str) -> bytes:
    """Decodifica il secret MAC Airtable.

    Airtable fornisce il segreto come Base64 (`macSecretBase64`) alla creazione del webhook:
    la chiave HMAC è la decodifica Base64, NON la stringa codificata.
    In caso di stringa non decodificabile in Base64, usa l'encoding UTF-8 (fail-safe).
    """
    clean = secret_str.strip()
    try:
        decoded = base64.b64decode(clean, validate=True)
        if len(decoded) > 0:
            return decoded
    except Exception:
        pass
    return clean.encode("utf-8")


class AirtableWebhookPayloadFetcher:
    """Client ufficiale per il recupero dei payload di un webhook Airtable.

    Implementa `GET /v0/bases/{baseId}/webhooks/{webhookId}/payloads` con cursore,
    secondo il modello thin-ping della Webhooks API: la notifica ricevuta NON contiene
    i cambiamenti; essi vanno richiesti con questo endpoint usando il cursore
    salvato per il webhook e paginando finché `mightHaveMore` è true.

    Il Personal Access Token del tenant viene risolto dalla connessione Airtable
    registrata (mai da payload o query string).
    """

    def __init__(
        self,
        connection_repo: Any,
        base_url: str = "https://api.airtable.com/v0",
        http_client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 8.0,
        rate_limiter: Any = None,
        max_retries: int = 2,
        wait_seconds_on_429: float = DEFAULT_WAIT_SECONDS_ON_429,
        retry_backoff_base_seconds: float = 0.5,
        retry_backoff_cap_seconds: float = 8.0,
    ):
        self._connection_repo = connection_repo
        self._base_url = base_url.rstrip("/")
        self._external_client = http_client
        self._timeout_seconds = timeout_seconds
        # Rate limit condiviso per base (policy ufficiale: 5 req/s per base):
        # il fetch dei payload conta verso lo stesso limite della Web API.
        self._rate_limiter = rate_limiter if rate_limiter is not None else get_shared_rate_limiter()
        self._max_retries = max(int(max_retries), 0)
        self._wait_seconds_on_429 = float(wait_seconds_on_429)
        self._retry_backoff_base = float(retry_backoff_base_seconds)
        self._retry_backoff_cap = float(retry_backoff_cap_seconds)

    def __repr__(self) -> str:
        # Invariante 10: mai esporre token o segreti nel repr/log.
        return f"<AirtableWebhookPayloadFetcher base_url='{self._base_url}'>"

    async def fetch(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
        webhook_id: str,
        cursor: int,
    ) -> dict[str, Any]:
        """Recupera una pagina di payload dal cursore indicato (chiamata ufficiale Airtable)."""
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)

        connection = await self._connection_repo.get_connection(organization_id, base_id)
        token = (connection or {}).get("token", "")
        if not token:
            raise AirtableNotFoundError(
                message=f"Nessuna connessione Airtable attiva per la Base {base_id}: "
                        "impossibile recuperare i payload del webhook.",
                status_code=404,
            )

        url = f"{self._base_url}/{quote(base_id, safe='')}/webhooks/{quote(webhook_id, safe='')}/payloads"
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        params = {"cursor": int(cursor)}

        # Resilienza: rate limit per base + retry solo per 429 (policy ufficiale 30s),
        # errori di rete transienti e 5xx. Nessun retry per 4xx diversi da 429.
        attempt = 0
        while True:
            if self._rate_limiter is not None:
                await self._rate_limiter.acquire(base_id.strip())
            try:
                if self._external_client is not None:
                    resp = await self._external_client.get(url, headers=headers, params=params)
                else:
                    async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                        resp = await client.get(url, headers=headers, params=params)
            except httpx.HTTPError as exc:
                if attempt < self._max_retries:
                    await asyncio.sleep(
                        compute_backoff_delay(attempt, self._retry_backoff_base, self._retry_backoff_cap)
                    )
                    attempt += 1
                    continue
                raise AirtableNetworkError(
                    message=f"Errore di rete durante il recupero dei payload webhook Airtable: {exc}",
                ) from exc

            if not resp.is_success and is_retryable_status(resp.status_code) and attempt < self._max_retries:
                await asyncio.sleep(compute_retry_delay(resp, wait_seconds_on_429=self._wait_seconds_on_429))
                attempt += 1
                continue

            self._raise_for_response(resp)
            break

        try:
            data = resp.json()
        except Exception as exc:
            raise AirtableError(
                message="Risposta non decodificabile dall'endpoint payloads di Airtable.",
                status_code=resp.status_code,
            ) from exc
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _raise_for_response(resp: httpx.Response) -> None:
        """Normalizza gli errori HTTP di Airtable in eccezioni di dominio."""
        if 200 <= resp.status_code < 300:
            return
        try:
            body = resp.json()
            error_obj = body.get("error") if isinstance(body, dict) else None
            if isinstance(error_obj, dict):
                message = str(error_obj.get("message", "")) or f"Errore Airtable HTTP {resp.status_code}"
            elif isinstance(error_obj, str):
                message = error_obj
            else:
                message = f"Errore Airtable HTTP {resp.status_code}"
        except Exception:
            message = f"Errore Airtable HTTP {resp.status_code}"

        if resp.status_code in (401, 403):
            raise AirtableAuthError(message=message, status_code=resp.status_code)
        if resp.status_code == 404:
            raise AirtableNotFoundError(message=message, status_code=404)
        if resp.status_code == 429:
            raise AirtableRateLimitError(message=message)
        if resp.status_code >= 500:
            raise AirtableServerError(message=message, status_code=resp.status_code)
        raise AirtableError(message=message, status_code=resp.status_code)


class AirtableWebhookService:
    """Service applicativo per validazione, autenticazione, persistenza ed elaborazione webhook Airtable."""

    def __init__(
        self,
        repo: AirtableWebhookRepository,
        mapping_repo: AirtableMappingRepository | None = None,
        payload_fetcher: AirtableWebhookPayloadFetcher | None = None,
    ):
        self.repo = repo
        self.mapping_repo = mapping_repo
        self.payload_fetcher = payload_fetcher

    @staticmethod
    def verify_signature(raw_body: bytes, header_mac: str | None, secret: str) -> bool:
        """Verifica la firma HMAC-SHA256 ufficiale inviata da Airtable nell'header X-Airtable-Content-MAC.

        Schema ufficiale (https://airtable.com/developers/web/api/webhooks-overview):
        `hmac-sha256=` + HMAC-SHA256 esadecimale del body grezzo, con chiave pari alla
        decodifica Base64 di `macSecretBase64`. Il confronto avviene in tempo costante.
        """
        if not header_mac or not secret or not isinstance(raw_body, (bytes, bytearray)):
            return False

        clean_mac = header_mac.strip()
        lowered = clean_mac.lower()
        if lowered.startswith("hmac-sha256="):
            clean_mac = clean_mac[len("hmac-sha256="):].strip()
        elif lowered.startswith("sha256="):
            clean_mac = clean_mac[len("sha256="):].strip()

        secret_bytes = _decode_mac_secret(secret)
        computed_digest = hmac.new(secret_bytes, raw_body, hashlib.sha256).hexdigest()

        return hmac.compare_digest(computed_digest.lower(), clean_mac.lower())

    @staticmethod
    def _extract_external_event_id(payload: dict[str, Any], raw_body: bytes) -> str:
        """Determina l'identificativo esterno dell'evento secondo le garanzie REALI del payload ufficiale.

        La notifica Airtable contiene esclusivamente `base.id`, `webhook.id` e `timestamp`:
        non esistono campi `external_event_id` o `cursor` nella notifica. Il solo
        `timestamp` NON basta (due ping distinti nello stesso millisecondo
        colliderebbero e il secondo verrebbe scartato come duplicato): l'ID e'
        quindi composito `ts:{timestamp}:hash:{sha256(body)[:16]}`. Retry ufficiali
        (body identico) restano deduplicati; eventi diversi restano distinti.
        In assenza di timestamp si usa l'hash del body grezzo (deterministico).
        """
        body_hash = hashlib.sha256(raw_body).hexdigest()
        timestamp = payload.get("timestamp")
        if timestamp and isinstance(timestamp, (str, int, float)):
            return f"ts:{str(timestamp).strip()}:hash:{body_hash[:16]}"
        return f"hash:{body_hash[:24]}"

    async def handle_incoming_notification(
        self,
        raw_body: bytes,
        header_mac: str | None,
    ) -> tuple[AirtableWebhookEvent | None, AirtableWebhookSubscription, bool]:
        """Elabora l'acknowledgment rapido e la persistenza del webhook.

        Flusso (conforme al meccanismo ufficiale Airtable):
        1. Validazione integrità strutturale e parsing JSON del payload grezzo.
        2. Risoluzione sicura dell'integrazione e del tenant a partire dal webhook_id
           registrato nel database (mai dal payload).
        3. Verifica crittografica della firma HMAC ufficiale (X-Airtable-Content-MAC).
        4. Risoluzione dell'identificativo esterno dell'evento (timestamp, fallback hash).
        5. Persistenza atomica idempotente dell'evento (Invariante 4).

        Restituisce:
            (event, subscription, is_duplicate)
        """
        if not raw_body:
            raise AirtableMalformedWebhookError("Payload webhook non valido: il body della richiesta e' vuoto.")

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except Exception:
            raise AirtableMalformedWebhookError("Payload webhook non valido: formato JSON non decodificabile.")

        if not isinstance(payload, dict):
            raise AirtableMalformedWebhookError("Payload webhook non valido: deve essere un oggetto JSON.")

        # Identificativi canonici della notifica ufficiale: base.id e webhook.id
        base_obj = payload.get("base")
        webhook_obj = payload.get("webhook")

        base_id = (base_obj.get("id") if isinstance(base_obj, dict) else payload.get("base_id"))
        webhook_id = (webhook_obj.get("id") if isinstance(webhook_obj, dict) else payload.get("webhook_id"))

        if not base_id or not webhook_id or not isinstance(base_id, str) or not isinstance(webhook_id, str):
            raise AirtableMalformedWebhookError(
                "Payload webhook non valido: 'base.id' e 'webhook.id' sono identificativi obbligatori."
            )

        clean_base = base_id.strip()
        clean_webhook = webhook_id.strip()

        # Identificazione server-side del tenant (Invariante 1): il payload viene usato
        # solo per trovare la sottoscrizione registrata; la corrispondenza base_id è obbligatoria.
        sub = await self.repo.get_subscription_by_webhook_id(clean_webhook)
        if not sub or sub.base_id != clean_base or not sub.is_active:
            raise AirtableUnknownIntegrationError(webhook_id=clean_webhook, base_id=clean_base)

        # Verifica autenticazione e integrità crittografica HMAC ufficiale (Invariante 10)
        if not header_mac:
            raise AirtableWebhookAuthError("Autenticazione webhook fallita: header X-Airtable-Content-MAC assente.")

        if not self.verify_signature(raw_body, header_mac, sub.mac_secret):
            raise AirtableWebhookAuthError("Autenticazione webhook fallita: firma X-Airtable-Content-MAC non valida.")

        # Identificativo esterno secondo le garanzie reali del payload ufficiale (Invariante 4)
        ext_id = self._extract_external_event_id(payload, raw_body)

        event, is_duplicate = await self.repo.record_event_idempotent(
            organization_id=sub.organization_id,
            base_id=sub.base_id,
            webhook_id=sub.webhook_id,
            external_event_id=ext_id,
            event_type=NOTIFICATION_PING_EVENT_TYPE,
            payload=payload,
        )
        if event is None:
            # Fail-closed: MAI rispondere 200 con evento perso. Il 500 fa
            # ritentare Airtable invece di perdere la notifica.
            raise AirtableWebhookProcessingError(
                "Persistenza evento webhook fallita: evento non trovato dopo upsert idempotente."
            )

        return event, sub, is_duplicate

    async def _resolve_mapping_for_table(
        self,
        organization_id: uuid.UUID,
        base_id: str,
        table_id: str,
        table_name_hint: str | None = None,
    ):
        """Risolve il mapping attivo per una tabella del tenant (per ID o, se noto, per nome)."""
        if not self.mapping_repo:
            return None
        mapping = await self.mapping_repo.get_mapping_by_table(
            organization_id=organization_id,
            base_id=base_id,
            table_id_or_name=table_id,
        )
        if mapping and mapping.is_active:
            return mapping
        if table_name_hint:
            mapping = await self.mapping_repo.get_mapping_by_table(
                organization_id=organization_id,
                base_id=base_id,
                table_id_or_name=table_name_hint,
            )
            if mapping and mapping.is_active:
                return mapping
        return None

    async def _process_payload_entry(
        self,
        organization_id: uuid.UUID,
        base_id: str,
        entry: dict[str, Any],
    ) -> dict[str, Any]:
        """Elabora un singolo payload del webhook: filtra le tabelle rilevanti per il tenant.

        Restituisce un riepilogo con record trasformati e tabelle ignorate. Nessuna
        sincronizzazione automatica di modifiche fuori scope: solo tabelle mappate e attive.
        """
        changed_tables = entry.get("changedTablesById") or {}
        created_tables = entry.get("createdTablesById") or {}
        destroyed_tables = entry.get("destroyedTableIds") or []

        records_processed = 0
        relevant_tables = 0
        ignored_tables = 0

        for table_id, changes in changed_tables.items():
            if not isinstance(changes, dict):
                continue
            table_name_hint = changes.get("name") or (created_tables.get(table_id) or {}).get("name")
            mapping = await self._resolve_mapping_for_table(organization_id, base_id, str(table_id), table_name_hint)
            if not mapping:
                ignored_tables += 1
                logger.info(
                    "Payload webhook Airtable: tabella '%s' non mappata per il tenant (org=%s): ignorata.",
                    table_id, organization_id,
                )
                continue

            relevant_tables += 1
            records_by_id = {**(changes.get("createdRecordsById") or {}), **(changes.get("updatedRecordsById") or {})}
            for record in records_by_id.values():
                fields = record.get("fields") if isinstance(record, dict) else None
                if isinstance(fields, dict):
                    mapping.transform_from_airtable(fields)
                    records_processed += 1
            # I record distrutti non richiedono trasformazione ma appartengono al cambiamento.
            records_processed += len(changes.get("destroyedRecordIds") or [])

        for table_id, table_model in created_tables.items():
            if not isinstance(table_model, dict):
                continue
            mapping = await self._resolve_mapping_for_table(organization_id, base_id, str(table_id), table_model.get("name"))
            if not mapping:
                ignored_tables += 1
                continue
            relevant_tables += 1
            for record in (table_model.get("createdRecordsById") or {}).values():
                fields = record.get("fields") if isinstance(record, dict) else None
                if isinstance(fields, dict):
                    mapping.transform_from_airtable(fields)
                    records_processed += 1

        for table_id in destroyed_tables:
            mapping = await self._resolve_mapping_for_table(organization_id, base_id, str(table_id))
            if not mapping:
                ignored_tables += 1
                continue
            relevant_tables += 1

        return {
            "records_processed": records_processed,
            "relevant_tables": relevant_tables,
            "ignored_tables": ignored_tables,
        }

    async def process_event_async(
        self,
        event_id: uuid.UUID | str,
        organization_id: uuid.UUID | str,
        base_id: str,
        webhook_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Elaborazione asincrona in background dell'evento (fuori dalla request HTTP).

        Modello ufficiale Airtable (thin ping):
        1. Recupera i cambiamenti da `GET /v0/bases/{baseId}/webhooks/{webhookId}/payloads`
           partendo dal cursore salvato per il webhook, paginando finché `mightHaveMore`.
        2. Filtra i payload: solo cambiamenti su tabelle mappate e attive per il tenant.
        3. Trasforma i record verso il modello interno (mapping campi).
        4. Avanza il cursore persistito (stato interno) e completa l'evento.

        Aggiorna lo stato nel DB ('completed', 'ignored', 'failed') in modo deterministico.
        """
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)
        if isinstance(event_id, str):
            event_id = uuid.UUID(event_id)

        sub = await self.repo.get_subscription(organization_id, base_id)
        if not sub or not sub.is_active:
            raise AirtableUnknownIntegrationError(webhook_id=webhook_id, base_id=base_id)

        if self.payload_fetcher is None:
            # Nessun fetcher configurato: l'evento resta 'pending' per elaborazione successiva.
            logger.warning(
                "Evento webhook Airtable rinviato (org=%s, event=%s): payload fetcher non configurato.",
                organization_id, event_id,
            )
            return {"status": "deferred", "reason": "payload_fetcher_not_configured"}

        # Claim atomico: un solo worker elabora l'evento. Se un altro worker lo
        # ha gia' preso (processing) o completato, non elaborare due volte.
        claimed = await self.repo.claim_event_processing(organization_id, event_id)
        if not claimed:
            current = await self.repo.get_event(organization_id, event_id)
            current_status = current.status if current else "unknown"
            if current_status in ("completed", "ignored", "failed"):
                return {"status": "skipped", "reason": f"already_{current_status}"}
            return {"status": "deferred", "reason": "already_processing"}

        try:

            current_cursor = int(sub.cursor or 1)
            fetch_cursor = current_cursor
            new_cursor = current_cursor
            records_processed = 0
            relevant_tables = 0
            ignored_tables = 0

            for _ in range(MAX_PAYLOAD_PAGES_PER_EVENT):
                page = await self.payload_fetcher.fetch(
                    organization_id=organization_id,
                    base_id=base_id,
                    webhook_id=webhook_id,
                    cursor=fetch_cursor,
                )
                payloads = page.get("payloads") or []
                if not isinstance(payloads, list):
                    payloads = []

                for entry in payloads:
                    if not isinstance(entry, dict):
                        continue
                    if entry.get("error"):
                        logger.warning(
                            "Payload webhook Airtable con errore ignorato (org=%s, event=%s): %s",
                            organization_id, event_id, entry.get("error"),
                        )
                    else:
                        summary = await self._process_payload_entry(organization_id, base_id, entry)
                        records_processed += summary["records_processed"]
                        relevant_tables += summary["relevant_tables"]
                        ignored_tables += summary["ignored_tables"]

                    entry_cursor = entry.get("cursor")
                    if isinstance(entry_cursor, int) and entry_cursor > new_cursor:
                        new_cursor = entry_cursor

                if not page.get("mightHaveMore") or not payloads:
                    break

                # Paginazione ufficiale: il cursore della prossima pagina è quello
                # dell'ultimo payload recuperato. Se non avanza, evitiamo loop infiniti.
                if new_cursor > fetch_cursor:
                    fetch_cursor = new_cursor
                else:
                    break

            # Stato interno: cursore della prossima lettura (ultimo cursore elaborato + 1).
            # La guardia monotonica e' nel repository: uno stale writer non regredisce.
            if new_cursor > current_cursor:
                advanced = await self.repo.update_cursor(organization_id, base_id, new_cursor + 1)
                if not advanced:
                    logger.warning(
                        "Cursore Airtable non avanzato (stale writer, org=%s, base=%s).",
                        organization_id, base_id,
                    )

            if relevant_tables == 0 and ignored_tables > 0:
                await self.repo.update_event_status(
                    organization_id,
                    event_id,
                    status="ignored",
                    error_message="Nessuna tabella mappata coinvolta nei cambiamenti segnalati.",
                )
                return {"status": "ignored", "reason": "no_relevant_tables"}

            await self.repo.update_event_status(organization_id, event_id, status="completed")
            return {
                "status": "completed",
                "event_id": str(event_id),
                "records_processed": records_processed,
                "relevant_tables": relevant_tables,
                "ignored_tables": ignored_tables,
                "cursor": new_cursor,
            }

        except Exception as exc:
            logger.error(
                "Errore durante elaborazione asincrona evento webhook Airtable (org=%s, event=%s): %s",
                organization_id, event_id, exc, exc_info=True,
            )
            await self.repo.update_event_status(
                organization_id,
                event_id,
                status="failed",
                error_message=str(exc),
            )
            raise AirtableWebhookProcessingError(f"Errore durante elaborazione evento {event_id}: {exc}")

    async def reap_stale_events(
        self, older_than_seconds: int = 1800, limit: int = 50
    ) -> dict[str, Any]:
        """Riporta a 'pending' gli eventi orfani in 'processing' oltre soglia.

        Senza reaper, un crash del worker tra claim e mark lascerebbe l'evento
        orfano per sempre. Idempotente: tocca solo righe stale.
        """
        rows = await self.repo.reap_stale_processing(older_than_seconds, limit)
        if rows:
            logger.warning(
                "Airtable webhook reaper: %d eventi orfani rimessi in coda.",
                len(rows),
            )
        return {"reaped": len(rows)}

    async def register_webhook(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
        webhook_id: str,
        mac_secret: str,
        notification_url: str = "",
        specification: dict[str, Any] | None = None,
        cursor: int = 1,
    ) -> AirtableWebhookSubscription:
        """Registra o aggiorna una sottoscrizione webhook per il tenant (cifrando il segreto at-rest).

        Tenant isolation: un webhook_id registrato da un altro tenant NON puo' essere
        sovrascritto (mac_secret, base_id, is_active): previene l'hijack IDOR della
        sottoscrizione altrui (Invariante 1).
        """
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)

        existing = await self.repo.get_subscription_by_webhook_id(webhook_id)
        if existing is not None and existing.organization_id != organization_id:
            raise AirtableWebhookOwnershipError(webhook_id=webhook_id)

        return await self.repo.save_subscription(
            organization_id=organization_id,
            base_id=base_id,
            webhook_id=webhook_id,
            mac_secret=mac_secret,
            notification_url=notification_url,
            specification=specification,
            cursor=cursor,
        )

    async def get_subscription(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
    ) -> AirtableWebhookSubscription | None:
        """Recupera la sottoscrizione webhook del tenant per la Base specificata."""
        return await self.repo.get_subscription(organization_id, base_id)

    async def list_events(
        self,
        organization_id: uuid.UUID | str,
        base_id: str | None = None,
        limit: int = 50,
    ) -> list[AirtableWebhookEvent]:
        """Elenca gli eventi webhook registrati per il tenant."""
        return await self.repo.list_events(organization_id, base_id=base_id, limit=limit)

    async def get_event(
        self,
        organization_id: uuid.UUID | str,
        event_id: uuid.UUID | str,
    ) -> AirtableWebhookEvent | None:
        """Recupera un singolo evento webhook registrato per il tenant."""
        return await self.repo.get_event(organization_id, event_id)
