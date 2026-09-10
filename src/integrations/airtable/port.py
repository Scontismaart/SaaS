"""Contratto astratto per l'integrazione con Airtable (Port).

Disaccoppia l'applicazione Melpis dai dettagli implementativi HTTP di Airtable.
Definisce le operazioni essenziali di manipolazione record (list, get, create,
update, delete, search) senza speculazioni non necessarie.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from collections.abc import AsyncIterator
from typing import Any

from src.integrations.airtable.models import (
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


class AirtablePort(ABC):
    """Porta architetturale agnostica per operazioni su Airtable."""

    @abstractmethod
    async def list_records(
        self,
        base_id: str,
        table_id_or_name: str,
        params: ListRecordsParams | None = None,
    ) -> RecordPage:
        """Elenca i record di una tabella, supportando filtri, ordinamenti e paginazione (fino a 100 record per pagina).

        Args:
            base_id: Identificativo della Base Airtable (es. 'appXXXXXXXXXXXXXX').
            table_id_or_name: ID della tabella o nome visualizzato (es. 'tblXXXXXXXXXXXXXX' o 'Leads').
            params: Parametri opzionali di filtro, ordinamento e offset.

        Returns:
            RecordPage contenente la lista di record e l'offset per la pagina successiva.
        """

    @abstractmethod
    async def list_all_records(
        self,
        base_id: str,
        table_id_or_name: str,
        params: ListRecordsParams | None = None,
        max_records: int | None = None,
    ) -> list[AirtableRecord]:
        """Recupera ricorsivamente tutte le pagine di record gestendo la paginazione internamente.

        Args:
            base_id: Identificativo della Base Airtable.
            table_id_or_name: ID della tabella o nome visualizzato.
            params: Parametri di filtro e ordinamento.
            max_records: Limite massimo facoltativo di record totali da restituire.

        Returns:
            Lista completa dei record recuperati.
        """

    @abstractmethod
    def iter_records(
        self,
        base_id: str,
        table_id_or_name: str,
        params: ListRecordsParams | None = None,
    ) -> AsyncIterator[AirtableRecord]:
        """Generatore asincrono per iterare i record pagina per pagina senza caricare tutto in memoria.

        Args:
            base_id: Identificativo della Base Airtable.
            table_id_or_name: ID della tabella o nome visualizzato.
            params: Parametri di filtro e ordinamento.

        Yields:
            AirtableRecord uno per uno man mano che le pagine vengono scaricate.
        """

    @abstractmethod
    async def get_record(
        self,
        base_id: str,
        table_id_or_name: str,
        record_id: str,
    ) -> AirtableRecord:
        """Recupera un singolo record tramite il suo ID univoco.

        Args:
            base_id: Identificativo della Base Airtable.
            table_id_or_name: ID della tabella o nome visualizzato.
            record_id: Identificativo univoco del record (es. 'recXXXXXXXXXXXXXX').

        Returns:
            AirtableRecord con campi e metadati.
        """

    @abstractmethod
    async def create_record(
        self,
        base_id: str,
        table_id_or_name: str,
        request: CreateRecordRequest,
    ) -> AirtableRecord:
        """Crea un singolo nuovo record nella tabella specificata.

        Args:
            base_id: Identificativo della Base Airtable.
            table_id_or_name: ID della tabella o nome visualizzato.
            request: DTO contenente i campi del record e flag typecast.

        Returns:
            AirtableRecord appena creato con ID assegnato da Airtable.
        """

    @abstractmethod
    async def create_records(
        self,
        base_id: str,
        table_id_or_name: str,
        records: list[dict[str, Any]] | list[BatchRecordItem] | list[CreateRecordRequest],
        typecast: bool = False,
    ) -> list[AirtableRecord]:
        """Crea record in batch (sfruttando l'endpoint batch di Airtable fino a 10 record/request).
        Se records > 10, esegue il chunking automatico in blocchi da 10.

        Args:
            base_id: Identificativo della Base Airtable.
            table_id_or_name: ID della tabella o nome visualizzato.
            records: Lista di dizionari con i campi o BatchRecordItem.
            typecast: Se True, tenta la conversione automatica dei tipi di dato.

        Returns:
            Lista degli AirtableRecord creati.
        """

    @abstractmethod
    async def update_record(
        self,
        base_id: str,
        table_id_or_name: str,
        record_id: str,
        request: UpdateRecordRequest,
    ) -> AirtableRecord:
        """Aggiorna i campi di un record esistente (merge parziale o sostituzione distruttiva).

        Args:
            base_id: Identificativo della Base Airtable.
            table_id_or_name: ID della tabella o nome visualizzato.
            record_id: Identificativo univoco del record da aggiornare.
            request: DTO contenente i nuovi campi, flag typecast e flag replace (PATCH vs PUT).

        Returns:
            AirtableRecord aggiornato.
        """

    @abstractmethod
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

        Args:
            base_id: Identificativo della Base Airtable.
            table_id_or_name: ID della tabella o nome visualizzato.
            records: Lista di elementi contenenti 'id' e 'fields'.
            typecast: Se True, tenta la conversione automatica dei tipi.
            replace: Se True (PUT), sovrascrive distruttivamente i campi non forniti; se False (PATCH), esegue merge.

        Returns:
            Lista degli AirtableRecord aggiornati.
        """

    @abstractmethod
    async def delete_record(
        self,
        base_id: str,
        table_id_or_name: str,
        record_id: str,
    ) -> DeleteRecordResult:
        """Elimina un record identificato dal suo ID univoco.

        Args:
            base_id: Identificativo della Base Airtable.
            table_id_or_name: ID della tabella o nome visualizzato.
            record_id: Identificativo del record da eliminare.

        Returns:
            DeleteRecordResult con id e flag deleted=True.
        """

    @abstractmethod
    async def delete_records(
        self,
        base_id: str,
        table_id_or_name: str,
        record_ids: list[str],
    ) -> list[DeleteRecordResult]:
        """Elimina record in batch (fino a 10 record/request con chunking automatico).

        Args:
            base_id: Identificativo della Base Airtable.
            table_id_or_name: ID della tabella o nome visualizzato.
            record_ids: Lista degli ID dei record da eliminare.

        Returns:
            Lista di DeleteRecordResult con gli esiti di cancellazione.
        """

    @abstractmethod
    async def search_records(
        self,
        base_id: str,
        table_id_or_name: str,
        formula: str | None = None,
        max_records: int | None = None,
    ) -> list[AirtableRecord]:
        """Cerca record che soddisfano una formula Airtable (es. '{Telefono} = "+39..."').

        Args:
            base_id: Identificativo della Base Airtable.
            table_id_or_name: ID della tabella o nome visualizzato.
            formula: Espressione formula Airtable valida (filterByFormula).
                None = nessun filtro (restituisce i record della tabella).
            max_records: Numero massimo di record da restituire.

        Returns:
            Lista di record corrispondenti ai criteri di ricerca.
        """

    @abstractmethod
    async def get_base_schema(self, base_id: str) -> list[AirtableTable]:
        """Recupera l'elenco delle tabelle e dei rispettivi campi per una Base (Metadata API).

        Richiede scope 'schema.bases:read'.

        Args:
            base_id: Identificativo della Base Airtable.

        Returns:
            Lista di AirtableTable con definizioni dei campi.
        """

    @abstractmethod
    async def validate_table_schema(
        self,
        base_id: str,
        table_id_or_name: str,
        required_fields: list[str],
    ) -> SchemaValidationResult:
        """Valida preventivamente l'esistenza della tabella e dei campi mappati.

        Permette di intercettare errori di configurazione o nomi di colonne errati
        al momento del salvataggio nel pannello di onboarding, prima di qualsiasi chiamata reale.

        Args:
            base_id: Identificativo della Base Airtable.
            table_id_or_name: ID della tabella o nome visualizzato.
            required_fields: Lista dei nomi di colonna che devono esistere nella tabella.

        Returns:
            SchemaValidationResult con esito (is_valid), campi mancanti e campi disponibili.
        """


