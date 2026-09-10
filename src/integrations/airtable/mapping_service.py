"""Servizio applicativo per la gestione e validazione dei mapping Airtable (tenant-scoped).

Implementa:
- Validazione configurazione mapping contro schema reale della Base e della Tabella
- Isolamento tenant rigoroso (Invariante 1): nessun tenant può usare o alterare mapping altrui
- Pre-write validation gate: blocca preventivamente scritture se i campi obbligatori non sono mappati
- Data minimization: trasforma ed esporta verso Airtable solo i campi esplicitamente mappati
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from src.integrations.airtable.errors import (
    AirtableInvalidBaseError,
    AirtableInvalidTableError,
    AirtableMissingFieldMappingError,
    AirtableNotFoundError,
)
from src.integrations.airtable.models import (
    CreateMappingRequest,
    STANDARD_ENTITY_REQUIRED_FIELDS,
    TableFieldMapping,
    UpdateMappingRequest,
)
from src.integrations.airtable.port import AirtablePort
from src.integrations.airtable.repository import (
    AirtableConnectionRepository,
    AirtableMappingRepository,
)

logger = logging.getLogger(__name__)


class AirtableMappingService:
    """Service applicativo tenant-scoped per la configurazione e applicazione dei mapping Airtable."""

    def __init__(
        self,
        mapping_repo: AirtableMappingRepository,
        connection_repo: AirtableConnectionRepository | None = None,
    ):
        self.mapping_repo = mapping_repo
        self.connection_repo = connection_repo

    async def _verify_base_ownership(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
    ) -> dict[str, Any]:
        """Accerta che la Base appartenga al tenant e che la connessione sia attiva."""
        if not self.connection_repo:
            return {}

        conn = await self.connection_repo.get_connection(organization_id, base_id)
        if not conn:
            raise AirtableInvalidBaseError(
                base_id=base_id,
                organization_id=organization_id,
                message=(
                    f"Base ID '{base_id}' non valida o non associata all'organizzazione. "
                    f"Connettere la Base prima di configurare i mapping."
                ),
            )
        if not conn.get("is_active", True):
            raise AirtableInvalidBaseError(
                base_id=base_id,
                organization_id=organization_id,
                message=f"La connessione alla Base '{base_id}' è disattivata o sospesa.",
            )
        return conn

    async def create_or_update_mapping(
        self,
        organization_id: uuid.UUID | str,
        request: CreateMappingRequest,
        adapter: AirtablePort | None = None,
    ) -> TableFieldMapping:
        """Crea o aggiorna la configurazione di mapping verificando schema e campi obbligatori."""
        # 1. Verifica appartenenza e stato Base per il tenant
        await self._verify_base_ownership(organization_id, request.base_id)

        # 2. Risolvi i campi interni obbligatori per l'entità
        required_fields = (
            request.required_fields
            if request.required_fields is not None
            else STANDARD_ENTITY_REQUIRED_FIELDS.get(request.entity_type, [])
        )

        # 3. Verifica preventiva che i campi interni obbligatori siano mappati
        missing_mappings = []
        for req_f in required_fields:
            mapped_col = request.field_mappings.get(req_f)
            if not mapped_col:
                short_name = req_f.split(".", 1)[-1]
                mapped_col = request.field_mappings.get(short_name)
            if not mapped_col or not str(mapped_col).strip():
                missing_mappings.append(req_f)

        if missing_mappings:
            raise AirtableMissingFieldMappingError(
                missing_fields=missing_mappings,
                entity_type=request.entity_type,
                table_id_or_name=request.table_id_or_name,
            )

        # 4. Se fornito l'adapter, valida l'esistenza della tabella e delle colonne su Airtable
        if adapter:
            target_cols = [c for c in request.field_mappings.values() if c and c.strip()]
            val_res = await adapter.validate_table_schema(
                base_id=request.base_id,
                table_id_or_name=request.table_id_or_name,
                required_fields=target_cols,
            )
            if not val_res.is_valid:
                err_msg = val_res.error_message or "Validazione schema fallita."
                if "non trovata" in err_msg.lower():
                    raise AirtableInvalidTableError(
                        table_id_or_name=request.table_id_or_name,
                        base_id=request.base_id,
                        message=err_msg,
                    )
                else:
                    raise AirtableInvalidTableError(
                        table_id_or_name=request.table_id_or_name,
                        base_id=request.base_id,
                        message=(
                            f"Colonne Airtable mappate inesistenti nella tabella '{request.table_id_or_name}': "
                            f"{val_res.missing_fields}"
                        ),
                    )

        # 5. Persistenza sicura nel repository tenant-scoped
        saved = await self.mapping_repo.save_mapping(
            organization_id=organization_id,
            base_id=request.base_id,
            table_id_or_name=request.table_id_or_name,
            entity_type=request.entity_type,
            field_mappings=request.field_mappings,
            required_fields=required_fields,
            is_active=request.is_active,
        )

        logger.info(
            "airtable_mapping_saved: org=%s base=%s table=%s entity=%s fields=%d",
            organization_id,
            request.base_id,
            request.table_id_or_name,
            request.entity_type,
            len(request.field_mappings),
        )
        return saved

    async def update_mapping(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
        table_id_or_name: str,
        entity_type: str,
        request: UpdateMappingRequest,
        adapter: AirtablePort | None = None,
    ) -> TableFieldMapping:
        """Aggiorna le associazioni di colonne di un mapping esistente."""
        await self._verify_base_ownership(organization_id, base_id)

        existing = await self.mapping_repo.get_mapping(
            organization_id=organization_id,
            base_id=base_id,
            table_id_or_name=table_id_or_name,
            entity_type=entity_type,
        )
        if not existing:
            raise AirtableNotFoundError(
                f"Mapping per entità '{entity_type}' sulla tabella '{table_id_or_name}' non trovato.",
                status_code=404,
            )

        merged_fields = dict(existing.field_mappings)
        merged_fields.update(request.field_mappings)

        merged_required = (
            request.required_fields
            if request.required_fields is not None
            else existing.required_fields
        )

        create_req = CreateMappingRequest(
            base_id=base_id,
            table_id_or_name=table_id_or_name,
            entity_type=entity_type,
            field_mappings=merged_fields,
            required_fields=merged_required,
            is_active=request.is_active if request.is_active is not None else existing.is_active,
        )
        return await self.create_or_update_mapping(organization_id, create_req, adapter=adapter)

    async def get_mapping(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
        table_id_or_name: str,
        entity_type: str = "customer",
    ) -> TableFieldMapping | None:
        """Recupera la configurazione di mapping garantendo isolamento tenant."""
        return await self.mapping_repo.get_mapping(
            organization_id=organization_id,
            base_id=base_id,
            table_id_or_name=table_id_or_name,
            entity_type=entity_type,
        )

    async def list_mappings(
        self,
        organization_id: uuid.UUID | str,
        base_id: str | None = None,
        only_active: bool = True,
    ) -> list[TableFieldMapping]:
        """Elenca tutti i mapping configurati per il tenant."""
        return await self.mapping_repo.list_mappings(
            organization_id=organization_id,
            base_id=base_id,
            only_active=only_active,
        )

    async def delete_mapping(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
        table_id_or_name: str,
        entity_type: str,
    ) -> bool:
        """Elimina la configurazione di mapping per il tenant specificato."""
        return await self.mapping_repo.delete_mapping(
            organization_id=organization_id,
            base_id=base_id,
            table_id_or_name=table_id_or_name,
            entity_type=entity_type,
        )

    async def prepare_write_payload(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
        table_id_or_name: str,
        entity_type: str,
        internal_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Gate pre-write bloccante: valida e trasforma i dati interni prima dell'invio ad Airtable.

        Solleva AirtableMissingFieldMappingError se mancano mapping obbligatori,
        o AirtableMissingDataError se mancano i dati necessari.
        Restituisce un payload pronto per la Web API Airtable ({ 'fields': ... }).
        """
        # 1. Verifica che la Base sia attiva e di proprietà del tenant
        await self._verify_base_ownership(organization_id, base_id)

        # 2. Recupera il mapping per la specifica tabella ed entità
        mapping = await self.mapping_repo.get_mapping(
            organization_id=organization_id,
            base_id=base_id,
            table_id_or_name=table_id_or_name,
            entity_type=entity_type,
        )
        if not mapping:
            req_f = STANDARD_ENTITY_REQUIRED_FIELDS.get(entity_type, [])
            raise AirtableMissingFieldMappingError(
                missing_fields=req_f,
                entity_type=entity_type,
                table_id_or_name=table_id_or_name,
                message=(
                    f"Nessuna configurazione di mapping trovata per l'entità '{entity_type}' "
                    f"sulla tabella '{table_id_or_name}' nella Base '{base_id}'. "
                    f"Configurare il mapping prima di inviare dati verso Airtable."
                ),
            )

        # 3. Valida e trasforma i campi interni verso le colonne Airtable
        fields_payload = mapping.transform_to_airtable(internal_data)
        return {"fields": fields_payload}
