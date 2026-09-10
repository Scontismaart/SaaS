"""Modelli DTO tipizzati per l'integrazione con Airtable Web API.

Fornisce rappresentazioni fortemente tipizzate per Basi, Tabelle, Campi,
Record e Paginazione, evitando l'uso indiscriminato di dict[str, Any]
pur mantenendo flessibile la struttura dinamica del dizionario `fields` di Airtable.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
import uuid

from pydantic import BaseModel, ConfigDict, Field


class AirtableField(BaseModel):
    """Metadati di un singolo campo di una tabella Airtable."""
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    name: str
    type: str | None = None
    description: str | None = None
    options: dict[str, Any] | None = None


class AirtableTable(BaseModel):
    """Metadati di una tabella all'interno di una Base Airtable."""
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    primary_field_id: str | None = None
    fields: list[AirtableField] = Field(default_factory=list)
    description: str | None = None


class AirtableBase(BaseModel):
    """Metadati di una Base Airtable."""
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    permission_level: str | None = None
    tables: list[AirtableTable] = Field(default_factory=list)


class AirtableRecord(BaseModel):
    """Rappresentazione tipizzata di un singolo record Airtable."""
    model_config = ConfigDict(extra="ignore")

    id: str
    created_time: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)

    def get_field(self, name: str, default: Any = None) -> Any:
        """Restituisce il valore del campo specificato o il default."""
        return self.fields.get(name, default)

    def __getitem__(self, item: str) -> Any:
        return self.fields[item]

    def __contains__(self, item: str) -> bool:
        return item in self.fields


class PaginationParams(BaseModel):
    """Parametri per il controllo della paginazione."""
    model_config = ConfigDict(extra="ignore")

    page_size: int = Field(default=100, ge=1, le=100)
    offset: str | None = None


class ListRecordsParams(BaseModel):
    """Parametri di filtro, ordinamento e paginazione per list_records."""
    model_config = ConfigDict(extra="ignore")

    fields: list[str] | None = None
    filter_by_formula: str | None = None
    max_records: int | None = Field(default=None, ge=1)
    page_size: int = Field(default=100, ge=1, le=100)
    offset: str | None = None
    sort: list[dict[str, str]] | None = None
    view: str | None = None
    cell_format: str | None = None
    time_zone: str | None = None
    user_locale: str | None = None


class RecordPage(BaseModel):
    """Pagina di risultati restituita da list_records."""
    model_config = ConfigDict(extra="ignore")

    records: list[AirtableRecord] = Field(default_factory=list)
    offset: str | None = None

    @property
    def has_more(self) -> bool:
        """Indica se sono presenti ulteriori record da recuperare."""
        return bool(self.offset)


class CreateRecordRequest(BaseModel):
    """Richiesta di creazione di un nuovo record."""
    model_config = ConfigDict(extra="forbid")

    fields: dict[str, Any] = Field(default_factory=dict)
    typecast: bool = False


class UpdateRecordRequest(BaseModel):
    """Richiesta di aggiornamento di un record esistente."""
    model_config = ConfigDict(extra="forbid")

    fields: dict[str, Any] = Field(default_factory=dict)
    typecast: bool = False
    replace: bool = False  # False = PATCH (merge parziale), True = PUT (rimpiazzo distruttivo)


class DeleteRecordResult(BaseModel):
    """Risultato della cancellazione di un record.

    Semantica:
    - `deleted` rispecchia il flag `deleted` restituito dall'API Airtable
      (l'Adapter lo mappa con `bool(raw.get("deleted", True))`).
    - Un record inesistente NON produce `deleted=False`: sia l'Adapter
      (HTTP 404 -> AirtableNotFoundError) sia il fake di test sollevano
      AirtableNotFoundError. `deleted=False` resta possibile solo se
      l'API upstream lo dichiara esplicitamente nel payload.
    """
    model_config = ConfigDict(extra="ignore")

    id: str
    deleted: bool = True


class BatchRecordItem(BaseModel):
    """Elemento singolo per creazione batch di record Airtable."""
    model_config = ConfigDict(extra="ignore")

    fields: dict[str, Any] = Field(default_factory=dict)


class BatchUpdateRecordItem(BaseModel):
    """Elemento per aggiornamento batch di un record esistente."""
    model_config = ConfigDict(extra="ignore")

    id: str
    fields: dict[str, Any] = Field(default_factory=dict)


class SchemaValidationResult(BaseModel):
    """Risultato della validazione preventiva dello schema al salvataggio configurazione."""
    model_config = ConfigDict(extra="ignore")

    is_valid: bool
    table_id: str | None = None
    table_name: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    available_fields: list[str] = Field(default_factory=list)
    error_message: str | None = None


# ── MAPPING MODELLO INTERNO <-> AIRTABLE (TENANT-SCOPED) ─────────────────────

# Campi interni canonici e requisiti minimi per entità standard
STANDARD_ENTITY_REQUIRED_FIELDS: dict[str, list[str]] = {
    "customer": ["customer.name", "customer.phone"],
    "lead": ["lead.name", "lead.phone"],
    "ticket": ["ticket.subject", "ticket.contact_phone"],
    "request": ["request.customer_phone", "request.details"],
    "booking": ["booking.customer_name", "booking.phone", "booking.start_time"],
}


class TableFieldMapping(BaseModel):
    """Configurazione tenant-scoped del mapping tra campi interni e colonne Airtable.

    Esempio:
      base_id: "appCRM123"
      table_id_or_name: "Customers"
      entity_type: "customer"
      field_mappings: {
          "customer.name": "Nome",
          "customer.phone": "Telefono",
          "customer.email": "Email"
      }
      required_fields: ["customer.name", "customer.phone"]
    """
    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID | None = None
    organization_id: uuid.UUID
    base_id: str
    table_id_or_name: str
    entity_type: str = "customer"
    field_mappings: dict[str, str] = Field(default_factory=dict)
    required_fields: list[str] = Field(default_factory=list)
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def get_airtable_field(self, internal_field: str) -> str | None:
        """Restituisce il nome della colonna Airtable mappata per il campo interno specificato."""
        if internal_field in self.field_mappings:
            return self.field_mappings[internal_field]
        # Prova lookup senza o con prefisso entity_type (es. "name" -> "customer.name")
        prefixed = f"{self.entity_type}.{internal_field}"
        if prefixed in self.field_mappings:
            return self.field_mappings[prefixed]
        return None

    def validate_for_write(self, internal_data: dict[str, Any]) -> None:
        """Verifica preventiva prima di una write: accerta che tutti i campi obbligatori siano mappati e forniti.

        Solleva eccezioni esplicite se la configurazione è incompleta.
        """
        from src.integrations.airtable.errors import (
            AirtableMissingDataError,
            AirtableMissingFieldMappingError,
        )

        # 1. Verifica che i campi obbligatori abbiano una colonna Airtable associata
        unmapped_required = []
        for req_field in self.required_fields:
            col_name = self.get_airtable_field(req_field)
            if not col_name or not col_name.strip():
                unmapped_required.append(req_field)

        if unmapped_required:
            raise AirtableMissingFieldMappingError(
                missing_fields=unmapped_required,
                entity_type=self.entity_type,
                table_id_or_name=self.table_id_or_name,
            )

        # 2. Verifica che i dati interni forniscano valori non vuoti per tali campi
        missing_data = []
        for req_field in self.required_fields:
            # cerca valore sia come "customer.name" sia come "name"
            val = internal_data.get(req_field)
            if val is None:
                short_name = req_field.split(".", 1)[-1]
                val = internal_data.get(short_name)
            if val is None or (isinstance(val, str) and not val.strip()):
                missing_data.append(req_field)

        if missing_data:
            raise AirtableMissingDataError(
                missing_fields=missing_data,
                entity_type=self.entity_type,
            )

    def transform_to_airtable(self, internal_data: dict[str, Any]) -> dict[str, Any]:
        """Trasforma un dizionario di dati interni in un payload fields per Airtable.

        Include SOLO i campi per i quali esiste una mappatura esplicita (whitelist rigorosa).
        """
        self.validate_for_write(internal_data)

        airtable_payload: dict[str, Any] = {}
        for internal_key, value in internal_data.items():
            if value is None:
                continue
            col_name = self.get_airtable_field(internal_key)
            if col_name:
                airtable_payload[col_name] = value

        return airtable_payload

    def transform_from_airtable(self, airtable_record_fields: dict[str, Any]) -> dict[str, Any]:
        """Esegue il reverse mapping da un record Airtable verso il modello interno del SaaS."""
        reverse_map = {col: internal for internal, col in self.field_mappings.items()}
        internal_payload: dict[str, Any] = {}
        for col_name, value in airtable_record_fields.items():
            internal_field = reverse_map.get(col_name)
            if internal_field:
                internal_payload[internal_field] = value
        return internal_payload


class CreateMappingRequest(BaseModel):
    """Richiesta di creazione o definizione di un mapping per tabella ed entità."""
    model_config = ConfigDict(extra="ignore")

    base_id: str
    table_id_or_name: str
    entity_type: str = "customer"
    field_mappings: dict[str, str] = Field(default_factory=dict)
    required_fields: list[str] | None = None
    is_active: bool = True


class UpdateMappingRequest(BaseModel):
    """Richiesta di aggiornamento di un mapping esistente."""
    model_config = ConfigDict(extra="ignore")

    field_mappings: dict[str, str] = Field(default_factory=dict)
    required_fields: list[str] | None = None
    is_active: bool | None = None


# ── MODELLI WEBHOOK AIRTABLE ──────────────────────────────────────────────────


class AirtableWebhookNotification(BaseModel):
    """Payload di notifica inviato da Airtable verso il webhook endpoint."""
    model_config = ConfigDict(extra="ignore")

    base_id: str
    webhook_id: str
    timestamp: str | None = None
    cursor: int | None = None

    @classmethod
    def from_raw_payload(cls, data: dict[str, Any]) -> AirtableWebhookNotification:
        base_obj = data.get("base")
        webhook_obj = data.get("webhook")

        base_id = base_obj.get("id") if isinstance(base_obj, dict) else data.get("base_id")
        webhook_id = webhook_obj.get("id") if isinstance(webhook_obj, dict) else data.get("webhook_id")

        if not base_id or not webhook_id:
            from src.integrations.airtable.errors import AirtableMalformedWebhookError
            raise AirtableMalformedWebhookError(
                "Payload non valido: 'base.id' e 'webhook.id' sono obbligatori."
            )

        return cls(
            base_id=str(base_id),
            webhook_id=str(webhook_id),
            timestamp=data.get("timestamp"),
            cursor=data.get("cursor"),
        )


class AirtableWebhookSubscription(BaseModel):
    """Registrazione tenant-scoped di una sottoscrizione webhook Airtable."""
    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID | None = None
    organization_id: uuid.UUID
    base_id: str
    webhook_id: str
    mac_secret: str
    cursor: int = 1
    notification_url: str = ""
    specification: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AirtableWebhookEvent(BaseModel):
    """Evento webhook Airtable persistito per tracciamento ed idempotenza."""
    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID | None = None
    organization_id: uuid.UUID
    base_id: str
    webhook_id: str
    external_event_id: str
    event_type: str = "table_data_changed"
    payload: dict[str, Any] = Field(default_factory=dict)
    status: str = "pending"
    error_message: str | None = None
    created_at: datetime | None = None
    processed_at: datetime | None = None

