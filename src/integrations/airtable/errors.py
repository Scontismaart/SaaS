"""Gerarchia di errori per l'integrazione Airtable.

Mappa i codici di errore HTTP e le condizioni di rete di Airtable
in eccezioni di dominio specifiche ed esplicite.
"""
from __future__ import annotations

from typing import Any


class AirtableError(Exception):
    """Errore base per tutte le operazioni relative ad Airtable."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        error_type: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_type = error_type
        self.details = details or {}

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} status={self.status_code} type={self.error_type} msg={self.message}>"


class AirtableAuthError(AirtableError):
    """Errore di autenticazione o autorizzazione (HTTP 401 / 403).

    Indica token scaduto, non valido o privo degli scopes necessari
    (es. data.records:read / data.records:write) per la Base target.
    """


class AirtableNotFoundError(AirtableError):
    """Risorsa non trovata (HTTP 404).

    Indica che Base ID, Table ID/Name o Record ID specificato non esiste.
    """


class AirtableValidationError(AirtableError):
    """Errore di validazione dello schema o dei campi (HTTP 422).

    Indica incoerenza nei tipi di dato inviati rispetto alla definizione
    dei campi della tabella o violazione di vincoli Airtable.
    """


class AirtableRateLimitError(AirtableError):
    """Superamento del limite di frequenza istantaneo delle chiamate API (HTTP 429).

    Airtable impone 5 req/s per Base. Se superato, il server restituisce 429
    con un blocco transitorio di 30 secondi superabile con backoff.
    """

    def __init__(
        self,
        message: str,
        retry_after: float = 30.0,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            status_code=429,
            error_type="RATE_LIMIT_EXCEEDED",
            details=details,
        )
        self.retry_after = retry_after


class AirtableQuotaExhaustedError(AirtableError):
    """Superamento della quota mensile del workspace (es. 1.000 call/mese su Free o 100.000 su Team).

    A differenza del rate limit istantaneo (5 req/s) che si risolve dopo 30 secondi di backoff,
    l'esaurimento della quota mensile NON può essere risolto con un semplice retry.
    Richiede tassativamente escalation umana esplicita (Invariante 11) o upgrade del piano Airtable.
    """

    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            status_code=429,
            error_type="MONTHLY_QUOTA_EXHAUSTED",
            details=details,
        )
        self.requires_human_escalation = True
        self.error_code = "airtable_quota_exhausted"



class AirtableMedicalPolicyError(AirtableError):
    """Errore bloccante di compliance GDPR / Art. 9 per il settore medico/sanitario.

    Airtable non è certificato per il trattamento di categorie particolari di dati personali
    (dati sanitari / clinici ex GDPR Art. 9). L'integrazione è tassativamente interdetta
    per organizzazioni operanti in ambito medico/sanitario per prevenire la dispersione di dati sensibili.
    """

    def __init__(
        self,
        message: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        msg = message or (
            "Connessione ad Airtable non consentita per il settore medico/sanitario. "
            "Airtable non è autorizzato al trattamento di dati sanitari o clinici (GDPR Art. 9). "
            "L'integrazione con Airtable è interdetta per policy di conformità e sicurezza."
        )
        super().__init__(
            message=msg,
            status_code=403,
            error_type="MEDICAL_POLICY_PROHIBITED",
            details=details,
        )


class AirtableServerError(AirtableError):
    """Errore interno o indisponibilità dei server Airtable (HTTP 5xx)."""


class AirtableNetworkError(AirtableError):
    """Errore di connessione a livello di trasporto di rete o timeout."""


class AirtableMalformedResponseError(AirtableError):
    """Risposta del server Airtable non valida o non decodificabile come JSON."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            message=message,
            status_code=502,
            error_type="MALFORMED_RESPONSE",
            details=details,
        )


class AirtableMappingError(AirtableError):
    """Errore base per la configurazione o validazione dei mapping Airtable."""

    def __init__(
        self,
        message: str,
        status_code: int = 400,
        error_type: str = "MAPPING_ERROR",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message=message, status_code=status_code, error_type=error_type, details=details)


class AirtableMissingFieldMappingError(AirtableMappingError):
    """Sollevato prima di una write quando un campo interno obbligatorio non è configurato nel mapping."""

    def __init__(
        self,
        missing_fields: list[str],
        entity_type: str,
        table_id_or_name: str,
        message: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        self.missing_fields = missing_fields
        self.entity_type = entity_type
        self.table_id_or_name = table_id_or_name
        msg = message or (
            f"Configurazione mapping incompleta per il tenant: i campi interni obbligatori {missing_fields} "
            f"per l'entità '{entity_type}' non sono mappati verso la tabella '{table_id_or_name}'. "
            f"Configurare il mapping prima di inviare dati verso Airtable."
        )
        d = details or {}
        d.update({
            "missing_fields": missing_fields,
            "entity_type": entity_type,
            "table_id_or_name": table_id_or_name,
        })
        super().__init__(
            message=msg,
            status_code=400,
            error_type="MISSING_FIELD_MAPPING",
            details=d,
        )


class AirtableInvalidTableError(AirtableMappingError):
    """Sollevato quando la tabella specificata non esiste nella Base o non contiene le colonne mappate."""

    def __init__(
        self,
        table_id_or_name: str,
        base_id: str,
        message: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        self.table_id_or_name = table_id_or_name
        self.base_id = base_id
        msg = message or (
            f"Tabella non valida o non trovata nella Base '{base_id}': '{table_id_or_name}'."
        )
        d = details or {}
        d.update({"table_id_or_name": table_id_or_name, "base_id": base_id})
        super().__init__(
            message=msg,
            status_code=400,
            error_type="INVALID_TABLE",
            details=d,
        )


class AirtableInvalidBaseError(AirtableMappingError):
    """Sollevato quando la Base non esiste o il tenant non possiede una connessione attiva per essa."""

    def __init__(
        self,
        base_id: str,
        organization_id: Any | None = None,
        message: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        self.base_id = base_id
        self.organization_id = str(organization_id) if organization_id else None
        msg = message or (
            f"Base non valida o non associata: '{base_id}' non appartiene al tenant o la connessione non è attiva."
        )
        d = details or {}
        d.update({"base_id": base_id, "organization_id": str(organization_id) if organization_id else None})
        super().__init__(
            message=msg,
            status_code=400,
            error_type="INVALID_BASE",
            details=d,
        )


class AirtableMissingDataError(AirtableMappingError):
    """Sollevato prima di una write quando i dati interni forniti mancano di valori per campi obbligatori."""

    def __init__(
        self,
        missing_fields: list[str],
        entity_type: str,
        message: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        self.missing_fields = missing_fields
        self.entity_type = entity_type
        msg = message or (
            f"Dati interni mancanti per la scrittura dell'entità '{entity_type}': "
            f"fornire valori non vuoti per i campi obbligatori {missing_fields}."
        )
        d = details or {}
        d.update({"missing_fields": missing_fields, "entity_type": entity_type})
        super().__init__(
            message=msg,
            status_code=400,
            error_type="MISSING_DATA",
            details=d,
        )


class AirtableWebhookError(AirtableError):
    """Errore base per la gestione dei webhook Airtable."""


class AirtableWebhookAuthError(AirtableWebhookError):
    """Firma HMAC X-Airtable-Content-MAC assente, non valida o non corrispondente."""

    def __init__(self, message: str = "Autenticazione webhook fallita: firma X-Airtable-Content-MAC non valida"):
        super().__init__(
            message=message,
            status_code=401,
            error_type="WEBHOOK_AUTH_FAILED",
        )


class AirtableUnknownIntegrationError(AirtableWebhookError):
    """L'identificativo webhook o base ricevuto non corrisponde ad alcun tenant registrato."""

    def __init__(self, webhook_id: str | None = None, base_id: str | None = None):
        super().__init__(
            message=f"Integrazione Airtable sconosciuta per webhook_id='{webhook_id}' e base_id='{base_id}'",
            status_code=404,
            error_type="UNKNOWN_INTEGRATION",
            details={"webhook_id": webhook_id, "base_id": base_id},
        )


class AirtableWebhookOwnershipError(AirtableWebhookError):
    """Tentativo di registrare/sovrascrivere un webhook_id registrato da un altro tenant (IDOR).

    Impedisce che un tenant possa alterare mac_secret, base_id o stato attivo della
    sottoscrizione webhook di un altro tenant (DoS sull'integrazione altrui).
    """

    def __init__(self, webhook_id: str | None = None):
        super().__init__(
            message=f"Webhook '{webhook_id}' gia' registrato da un'altra organizzazione: "
                    "operazione non consentita.",
            status_code=403,
            error_type="WEBHOOK_OWNERSHIP_CONFLICT",
            details={"webhook_id": webhook_id},
        )


class AirtableMalformedWebhookError(AirtableWebhookError):
    """Payload del webhook malformato o privo dei campi strutturali obbligatori."""

    def __init__(self, message: str = "Payload webhook malformato"):
        super().__init__(
            message=message,
            status_code=400,
            error_type="MALFORMED_WEBHOOK",
        )


class AirtableWebhookProcessingError(AirtableWebhookError):
    """Errore durante l'elaborazione asincrona dell'evento webhook."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            message=message,
            status_code=500,
            error_type="WEBHOOK_PROCESSING_FAILED",
            details=details,
        )


# ── ERRORI AI TOOLS & CAPABILITY BOUNDARIES ───────────────────────────────────


class AirtableAIError(AirtableError):
    """Errore durante l'esecuzione di tool AI o capability verso Airtable."""


class AirtableSchemaModificationProhibitedError(AirtableAIError):
    """Sollevato se un tool AI o LLM tenta di alterare schema, tabelle o permessi."""

    def __init__(
        self,
        message: str = "Operazione non consentita: all'agente AI è vietato creare, modificare o eliminare tabelle, campi e schemi Airtable.",
    ):
        super().__init__(
            message=message,
            status_code=403,
            error_type="SCHEMA_MODIFICATION_PROHIBITED",
        )


class AirtableConfirmationRequiredError(AirtableAIError):
    """Sollevato quando un'operazione distruttiva richiede una conferma esplicita dell'utente/operatore."""

    def __init__(
        self,
        action: str,
        record_id: str,
        confirmation_token: str,
        message: str | None = None,
    ):
        self.action = action
        self.record_id = record_id
        self.confirmation_token = confirmation_token
        msg = message or (
            f"Operazione distruttiva '{action}' su record '{record_id}' richiede conferma esplicita. "
            f"Per procedere, confermare fornendo il token '{confirmation_token}'."
        )
        super().__init__(
            message=msg,
            status_code=409,
            error_type="CONFIRMATION_REQUIRED",
            details={
                "action": action,
                "record_id": record_id,
                "confirmation_token": confirmation_token,
            },
        )


