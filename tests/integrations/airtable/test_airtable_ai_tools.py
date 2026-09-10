"""Unit test esaustivi per AI Tools e AirtableAIService.

Verifica:
1. FakeAirtablePort in-memory → nessuna rete, nessun token reale
2. Ogni capability CRM (find, create, update, create_lead, create_request, create_ticket, search, delete)
3. Tenant isolation: nessun org_id/base_id/token nello schema LLM
4. Interdizione settore medico (GDPR Art. 9) per tutti i tool
5. Divieto assoluto di modifiche schema (create_table, delete_table, create_field, update_permissions)
6. Write Safety: delete richiede confirmation_token esplicito
7. Factory create_airtable_tools: 8 tool pre-vincolati al tenant
8. Formula injection sanitization
9. Mapping transform corretto (internal → Airtable → internal round-trip)
10. Entità non autorizzate → errore chiaro
"""
from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.integrations.airtable.ai_service import (
    ALLOWED_AI_ENTITIES,
    AirtableAIService,
    _escape_formula_str,
)
from src.integrations.airtable.ai_tools import (
    CreateCustomerInput,
    CreateCustomerTool,
    CreateLeadInput,
    CreateLeadTool,
    CreateRequestInput,
    CreateRequestTool,
    CreateTicketInput,
    CreateTicketTool,
    DeleteRecordInput,
    DeleteRecordTool,
    FindCustomerInput,
    FindCustomerTool,
    SearchRecordsInput,
    SearchRecordsTool,
    UpdateCustomerInput,
    UpdateCustomerTool,
    create_airtable_tools,
)
from src.integrations.airtable.errors import (
    AirtableConfirmationRequiredError,
    AirtableMedicalPolicyError,
    AirtableNotFoundError,
    AirtableSchemaModificationProhibitedError,
    AirtableValidationError,
)
from src.integrations.airtable.models import (
    AirtableRecord,
    BatchRecordItem,
    BatchUpdateRecordItem,
    CreateRecordRequest,
    DeleteRecordResult,
    ListRecordsParams,
    RecordPage,
    SchemaValidationResult,
    TableFieldMapping,
    UpdateRecordRequest,
)
from src.integrations.airtable.port import AirtablePort


# ── FIXTURES ──────────────────────────────────────────────────────────────────


ORG_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
ORG_B = uuid.UUID("22222222-2222-2222-2222-222222222222")
ORG_MEDICAL = uuid.UUID("33333333-3333-3333-3333-333333333333")
BASE_ID = "app_test_mock"


# ── FAKE AIRTABLE PORT (IN-MEMORY, ZERO RETE) ────────────────────────────────


class FakeAirtablePort(AirtablePort):
    """Port Airtable in-memory per test unitari senza rete — UNICO fake canonico.

    Eredita AirtablePort: se Service e Port divergono, l'istanziazione fallisce
    (metodi astratti) e i test di signature falliscono (inspect). Nessuna API legacy
    (table_name / filter_by_formula / destructive_replace come kwargs del Port).

    Semantica allineata all'Adapter:
    - get/update su record inesistente -> AirtableNotFoundError (come HTTP 404)
    - delete su record inesistente -> AirtableNotFoundError (come HTTP 404)
    - search con formula=None -> tutta la tabella (come filterByFormula assente)
    - list_records pagina con offset = indice stringa, page_size default 100
    """

    def __init__(self):
        # Chiave: (base_id, table_id_or_name), Valore: lista di AirtableRecord
        self._tables: dict[tuple[str, str], list[AirtableRecord]] = {}
        self._id_counter = 0
        self.last_formula: str | None = None

    def _next_id(self) -> str:
        self._id_counter += 1
        return f"rec{self._id_counter:016d}"

    def _get_table(self, base_id: str, table_id_or_name: str) -> list[AirtableRecord]:
        key = (base_id, table_id_or_name)
        if key not in self._tables:
            self._tables[key] = []
        return self._tables[key]

    def _find_record(
        self, base_id: str, table_id_or_name: str, record_id: str
    ) -> AirtableRecord:
        for rec in self._get_table(base_id, table_id_or_name):
            if rec.id == record_id:
                return rec
        raise AirtableNotFoundError(f"Record '{record_id}' non trovato in '{table_id_or_name}'")

    def seed_record(self, base_id: str, table_id_or_name: str, fields: dict[str, Any]) -> AirtableRecord:
        """Helper di test (fuori dal contratto Port): inserisce un record pre-esistente."""
        rec = AirtableRecord(id=self._next_id(), fields=dict(fields))
        self._get_table(base_id, table_id_or_name).append(rec)
        return rec

    def seed(self, base_id: str, table_id_or_name: str, fields: dict[str, Any]) -> AirtableRecord:
        """Alias di seed_record per compatibilità con i contract test."""
        return self.seed_record(base_id, table_id_or_name, fields)

    async def list_records(
        self,
        base_id: str,
        table_id_or_name: str,
        params: ListRecordsParams | None = None,
    ) -> RecordPage:
        records = list(self._get_table(base_id, table_id_or_name))
        page_size = params.page_size if params and params.page_size else 100
        start = 0
        if params and params.offset:
            try:
                start = int(params.offset)
            except ValueError:
                start = 0
        page = records[start : start + page_size]
        next_offset = str(start + page_size) if start + page_size < len(records) else None
        return RecordPage(records=list(page), offset=next_offset)

    async def list_all_records(
        self,
        base_id: str,
        table_id_or_name: str,
        params: ListRecordsParams | None = None,
        max_records: int | None = None,
    ) -> list[AirtableRecord]:
        all_records: list[AirtableRecord] = []
        offset: str | None = params.offset if params else None
        while True:
            effective = params.model_copy() if params else ListRecordsParams()
            effective.offset = offset
            if max_records is not None:
                remaining = max_records - len(all_records)
                if remaining <= 0:
                    break
                effective.page_size = min(remaining, 100)
            page = await self.list_records(base_id, table_id_or_name, params=effective)
            all_records.extend(page.records)
            if max_records is not None and len(all_records) >= max_records:
                return all_records[:max_records]
            if not page.has_more:
                break
            offset = page.offset
        return all_records

    async def iter_records(
        self,
        base_id: str,
        table_id_or_name: str,
        params: ListRecordsParams | None = None,
    ):
        offset: str | None = params.offset if params else None
        while True:
            effective = params.model_copy() if params else ListRecordsParams()
            effective.offset = offset
            page = await self.list_records(base_id, table_id_or_name, params=effective)
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
        return self._find_record(base_id, table_id_or_name, record_id)

    async def search_records(
        self,
        base_id: str,
        table_id_or_name: str,
        formula: str | None = None,
        max_records: int | None = None,
    ) -> list[AirtableRecord]:
        """Ricerca semplificata: il filtering reale è server-side su Airtable.

        Registra la formula ricevuta (per asserzioni) e restituisce i record
        della tabella, come farebbe list_all senza filtro.
        """
        self.last_formula = formula
        records = list(self._get_table(base_id, table_id_or_name))
        if max_records is not None:
            records = records[:max_records]
        return records

    async def create_record(
        self,
        base_id: str,
        table_id_or_name: str,
        request: CreateRecordRequest,
    ) -> AirtableRecord:
        """Crea un record in-memory (contratto canonico con DTO)."""
        rec = AirtableRecord(id=self._next_id(), fields=dict(request.fields))
        self._get_table(base_id, table_id_or_name).append(rec)
        return rec

    async def create_records(
        self,
        base_id: str,
        table_id_or_name: str,
        records: list[dict[str, Any]] | list[BatchRecordItem] | list[CreateRecordRequest],
        typecast: bool = False,
    ) -> list[AirtableRecord]:
        created: list[AirtableRecord] = []
        for item in records or []:
            if isinstance(item, CreateRecordRequest):
                fields = dict(item.fields)
            elif isinstance(item, BatchRecordItem):
                fields = dict(item.fields)
            elif isinstance(item, dict):
                fields = dict(item.get("fields", item) if "fields" in item else item)
            else:
                fields = dict(getattr(item, "fields", {}))
            created.append(await self.create_record(base_id, table_id_or_name, CreateRecordRequest(fields=fields)))
        return created

    async def update_record(
        self,
        base_id: str,
        table_id_or_name: str,
        record_id: str,
        request: UpdateRecordRequest,
    ) -> AirtableRecord:
        """Aggiorna un record esistente: merge parziale (PATCH) o rimpiazzo (PUT)."""
        rec = self._find_record(base_id, table_id_or_name, record_id)
        if request.replace:
            rec.fields = dict(request.fields)
        else:
            rec.fields.update(request.fields)
        return rec

    async def update_records(
        self,
        base_id: str,
        table_id_or_name: str,
        records: list[dict[str, Any]] | list[BatchUpdateRecordItem],
        typecast: bool = False,
        replace: bool = False,
    ) -> list[AirtableRecord]:
        updated: list[AirtableRecord] = []
        for item in records or []:
            if isinstance(item, BatchUpdateRecordItem):
                rec_id, fields = item.id, dict(item.fields)
            elif isinstance(item, dict):
                rec_id, fields = item["id"], dict(item.get("fields", {}))
            else:
                rec_id, fields = getattr(item, "id"), dict(getattr(item, "fields", {}))
            updated.append(
                await self.update_record(
                    base_id, table_id_or_name, rec_id,
                    UpdateRecordRequest(fields=fields, replace=replace),
                )
            )
        return updated

    async def delete_record(
        self,
        base_id: str,
        table_id_or_name: str,
        record_id: str,
    ) -> DeleteRecordResult:
        """Elimina un record; record inesistente -> AirtableNotFoundError (come HTTP 404)."""
        table = self._get_table(base_id, table_id_or_name)
        for i, rec in enumerate(table):
            if rec.id == record_id:
                table.pop(i)
                return DeleteRecordResult(id=record_id, deleted=True)
        raise AirtableNotFoundError(f"Record '{record_id}' non trovato in '{table_id_or_name}'")

    async def delete_records(
        self,
        base_id: str,
        table_id_or_name: str,
        record_ids: list[str],
    ) -> list[DeleteRecordResult]:
        return [await self.delete_record(base_id, table_id_or_name, rid) for rid in (record_ids or [])]

    async def get_base_schema(self, base_id: str) -> list:
        return []

    async def validate_table_schema(
        self,
        base_id: str,
        table_id_or_name: str,
        required_fields: list[str],
    ) -> SchemaValidationResult:
        table = self._get_table(base_id, table_id_or_name)
        available: list[str] = sorted({k for rec in table for k in rec.fields.keys()})
        missing = [f for f in (required_fields or []) if f not in available]
        return SchemaValidationResult(
            is_valid=not missing,
            table_id=table_id_or_name,
            table_name=table_id_or_name,
            missing_fields=missing,
            available_fields=available,
        )


# ── IN-MEMORY MAPPING REPOSITORY ─────────────────────────────────────────────


class InMemoryMappingRepo:
    """Repository in-memory per mapping campo interno → colonna Airtable."""

    def __init__(self):
        self._mappings: dict[tuple[str, str, str], TableFieldMapping] = {}

    def add_mapping(self, mapping: TableFieldMapping) -> None:
        key = (str(mapping.organization_id), mapping.base_id, mapping.entity_type)
        self._mappings[key] = mapping

    async def get_mapping_by_entity(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
        entity_type: str,
    ) -> TableFieldMapping | None:
        key = (str(organization_id), base_id, entity_type.strip().lower())
        return self._mappings.get(key)


# ── IN-MEMORY CORE REPO (per vertical check) ─────────────────────────────────


class InMemoryCoreRepo:
    """Repository core per test vertical check senza database."""

    def __init__(self):
        self._profiles: dict[str, dict[str, Any]] = {}

    def set_profile(self, organization_id: uuid.UUID | str, verticale: str) -> None:
        self._profiles[str(organization_id)] = {"verticale": verticale}

    async def get_onboarding_profile(self, organization_id: uuid.UUID | str) -> dict[str, Any] | None:
        return self._profiles.get(str(organization_id))


# ── FIXTURES PYTEST ───────────────────────────────────────────────────────────


def _make_customer_mapping(org_id: uuid.UUID, base_id: str = BASE_ID) -> TableFieldMapping:
    return TableFieldMapping(
        organization_id=org_id,
        base_id=base_id,
        table_id_or_name="Clienti",
        entity_type="customer",
        field_mappings={
            "customer.name": "Nome",
            "customer.phone": "Telefono",
            "customer.email": "Email",
            "customer.notes": "Note",
        },
        required_fields=["customer.name", "customer.phone"],
        is_active=True,
    )


def _make_lead_mapping(org_id: uuid.UUID, base_id: str = BASE_ID) -> TableFieldMapping:
    return TableFieldMapping(
        organization_id=org_id,
        base_id=base_id,
        table_id_or_name="Lead",
        entity_type="lead",
        field_mappings={
            "lead.name": "Nome Contatto",
            "lead.phone": "Cellulare",
            "lead.email": "Email",
            "lead.source": "Provenienza",
            "lead.notes": "Note",
        },
        required_fields=["lead.name", "lead.phone"],
        is_active=True,
    )


def _make_request_mapping(org_id: uuid.UUID, base_id: str = BASE_ID) -> TableFieldMapping:
    return TableFieldMapping(
        organization_id=org_id,
        base_id=base_id,
        table_id_or_name="Richieste",
        entity_type="request",
        field_mappings={
            "request.customer_phone": "Telefono Cliente",
            "request.details": "Dettagli",
            "request.customer_name": "Nome Cliente",
            "request.priority": "Priorità",
        },
        required_fields=["request.customer_phone", "request.details"],
        is_active=True,
    )


def _make_ticket_mapping(org_id: uuid.UUID, base_id: str = BASE_ID) -> TableFieldMapping:
    return TableFieldMapping(
        organization_id=org_id,
        base_id=base_id,
        table_id_or_name="Ticket",
        entity_type="ticket",
        field_mappings={
            "ticket.subject": "Oggetto",
            "ticket.contact_phone": "Telefono",
            "ticket.description": "Descrizione",
            "ticket.priority": "Priorità",
        },
        required_fields=["ticket.subject", "ticket.contact_phone"],
        is_active=True,
    )


@pytest.fixture
def fake_port() -> FakeAirtablePort:
    return FakeAirtablePort()


@pytest.fixture
def mapping_repo() -> InMemoryMappingRepo:
    repo = InMemoryMappingRepo()
    # Mapping per ORG_A (tutte le 4 entità)
    repo.add_mapping(_make_customer_mapping(ORG_A))
    repo.add_mapping(_make_lead_mapping(ORG_A))
    repo.add_mapping(_make_request_mapping(ORG_A))
    repo.add_mapping(_make_ticket_mapping(ORG_A))
    return repo


@pytest.fixture
def core_repo() -> InMemoryCoreRepo:
    repo = InMemoryCoreRepo()
    repo.set_profile(ORG_A, "ristorante")
    repo.set_profile(ORG_B, "ristorante")
    repo.set_profile(ORG_MEDICAL, "studio_medico")
    return repo


@pytest.fixture
def ai_service(fake_port, mapping_repo, core_repo) -> AirtableAIService:
    return AirtableAIService(
        port=fake_port,
        mapping_repo=mapping_repo,
        core_repo=core_repo,
    )


@pytest.fixture
def ai_tools(ai_service) -> list:
    return create_airtable_tools(service=ai_service, organization_id=ORG_A)


# ── TEST: FACTORY create_airtable_tools ───────────────────────────────────────


class TestCreateAirtableToolsFactory:
    """Verifica che la factory produca 8 tool pre-vincolati al tenant."""

    def test_factory_returns_8_tools(self, ai_tools):
        assert len(ai_tools) == 8

    def test_factory_tool_names(self, ai_tools):
        expected_names = {
            "airtable_find_customer",
            "airtable_create_customer",
            "airtable_update_customer",
            "airtable_create_lead",
            "airtable_create_request",
            "airtable_create_ticket",
            "airtable_search_records",
            "airtable_delete_record",
        }
        actual_names = {t.name for t in ai_tools}
        assert actual_names == expected_names

    def test_factory_binds_organization_id(self, ai_tools):
        for tool in ai_tools:
            assert tool.organization_id == ORG_A

    def test_factory_binds_service(self, ai_service, ai_tools):
        for tool in ai_tools:
            assert tool.service is ai_service


# ── TEST: TENANT ISOLATION (Invariante 1) ─────────────────────────────────────


class TestTenantIsolation:
    """Verifica che org_id, base_id e token non appaiano nello schema LLM-facing."""

    def test_find_customer_input_has_no_tenant_fields(self):
        schema = FindCustomerInput.model_json_schema()
        props = schema.get("properties", {})
        for forbidden in ("organization_id", "base_id", "token", "org_id"):
            assert forbidden not in props, f"Campo proibito '{forbidden}' esposto allo schema LLM"

    def test_create_customer_input_has_no_tenant_fields(self):
        schema = CreateCustomerInput.model_json_schema()
        props = schema.get("properties", {})
        for forbidden in ("organization_id", "base_id", "token", "org_id"):
            assert forbidden not in props

    def test_update_customer_input_has_no_tenant_fields(self):
        schema = UpdateCustomerInput.model_json_schema()
        props = schema.get("properties", {})
        for forbidden in ("organization_id", "base_id", "token", "org_id"):
            assert forbidden not in props

    def test_create_lead_input_has_no_tenant_fields(self):
        schema = CreateLeadInput.model_json_schema()
        props = schema.get("properties", {})
        for forbidden in ("organization_id", "base_id", "token", "org_id"):
            assert forbidden not in props

    def test_create_request_input_has_no_tenant_fields(self):
        schema = CreateRequestInput.model_json_schema()
        props = schema.get("properties", {})
        for forbidden in ("organization_id", "base_id", "token", "org_id"):
            assert forbidden not in props

    def test_create_ticket_input_has_no_tenant_fields(self):
        schema = CreateTicketInput.model_json_schema()
        props = schema.get("properties", {})
        for forbidden in ("organization_id", "base_id", "token", "org_id"):
            assert forbidden not in props

    def test_search_records_input_has_no_tenant_fields(self):
        schema = SearchRecordsInput.model_json_schema()
        props = schema.get("properties", {})
        for forbidden in ("organization_id", "base_id", "token", "org_id"):
            assert forbidden not in props

    def test_delete_record_input_has_no_tenant_fields(self):
        schema = DeleteRecordInput.model_json_schema()
        props = schema.get("properties", {})
        for forbidden in ("organization_id", "base_id", "token", "org_id"):
            assert forbidden not in props


# ── TEST: FIND CUSTOMER ──────────────────────────────────────────────────────


class TestFindCustomer:
    """Verifica ricerca clienti con FakeAirtablePort."""

    async def test_find_by_phone(self, ai_service, fake_port):
        fake_port.seed_record(BASE_ID, "Clienti", {"Nome": "Mario Rossi", "Telefono": "+393331234567"})

        results = await ai_service.find_customer(
            organization_id=ORG_A,
            phone="+393331234567",
        )
        assert len(results) >= 1
        assert results[0]["id"].startswith("rec")

    async def test_find_by_email(self, ai_service, fake_port):
        fake_port.seed_record(BASE_ID, "Clienti", {"Nome": "Lucia Verdi", "Email": "lucia@esempio.it"})

        results = await ai_service.find_customer(
            organization_id=ORG_A,
            email="lucia@esempio.it",
        )
        assert len(results) >= 1

    async def test_find_by_name(self, ai_service, fake_port):
        fake_port.seed_record(BASE_ID, "Clienti", {"Nome": "Andrea Bianchi", "Telefono": "+393339999999"})

        results = await ai_service.find_customer(
            organization_id=ORG_A,
            name="andrea",
        )
        assert len(results) >= 1

    async def test_find_no_criteria_returns_empty(self, ai_service):
        results = await ai_service.find_customer(organization_id=ORG_A)
        assert results == []

    async def test_find_no_results(self, ai_service):
        results = await ai_service.find_customer(organization_id=ORG_A, phone="+390000000000")
        # FakePort restituisce tutti i record senza filtering reale, ma con tabella vuota = empty
        assert isinstance(results, list)


# ── TEST: CREATE CUSTOMER ─────────────────────────────────────────────────────


class TestCreateCustomer:
    """Verifica creazione cliente con mapping transform."""

    async def test_create_customer_basic(self, ai_service, fake_port):
        result = await ai_service.create_customer(
            organization_id=ORG_A,
            name="Marco Neri",
            phone="+393334567890",
        )
        assert "id" in result
        assert result["id"].startswith("rec")
        # Il record nella tabella in-memory deve avere i campi Airtable mappati
        table = fake_port._get_table(BASE_ID, "Clienti")
        assert len(table) == 1
        assert table[0].fields["Nome"] == "Marco Neri"
        assert table[0].fields["Telefono"] == "+393334567890"

    async def test_create_customer_with_email_and_notes(self, ai_service, fake_port):
        result = await ai_service.create_customer(
            organization_id=ORG_A,
            name="Sara Verdi",
            phone="+393339876543",
            email="sara@test.it",
            notes="Preferisce mattina",
        )
        assert result["id"].startswith("rec")
        table = fake_port._get_table(BASE_ID, "Clienti")
        rec = table[0]
        assert rec.fields["Email"] == "sara@test.it"
        assert rec.fields["Note"] == "Preferisce mattina"

    async def test_create_customer_mapping_round_trip(self, ai_service, fake_port):
        """Verifica che la trasformazione internal → Airtable → internal sia consistente."""
        result = await ai_service.create_customer(
            organization_id=ORG_A,
            name="Test Roundtrip",
            phone="+39000000",
            email="round@trip.it",
        )
        assert result.get("customer.name") == "Test Roundtrip"
        assert result.get("customer.phone") == "+39000000"
        assert result.get("customer.email") == "round@trip.it"


# ── TEST: UPDATE CUSTOMER ─────────────────────────────────────────────────────


class TestUpdateCustomer:
    """Verifica aggiornamento parziale di un cliente."""

    async def test_update_customer_partial(self, ai_service, fake_port):
        # Seed record pre-esistente
        rec = fake_port.seed_record(BASE_ID, "Clienti", {"Nome": "Old Name", "Telefono": "+390000000"})

        result = await ai_service.update_customer(
            organization_id=ORG_A,
            customer_id=rec.id,
            name="New Name",
        )
        assert result["id"] == rec.id
        # Verifica che il campo sia stato aggiornato
        updated = fake_port._get_table(BASE_ID, "Clienti")[0]
        assert updated.fields["Nome"] == "New Name"
        # Il telefono deve restare invariato
        assert updated.fields["Telefono"] == "+390000000"

    async def test_update_customer_no_fields_raises(self, ai_service, fake_port):
        rec = fake_port.seed_record(BASE_ID, "Clienti", {"Nome": "Test", "Telefono": "+39111"})

        with pytest.raises(AirtableValidationError, match="Nessun campo valido"):
            await ai_service.update_customer(
                organization_id=ORG_A,
                customer_id=rec.id,
            )

    async def test_update_customer_empty_id_raises(self, ai_service):
        with pytest.raises(AirtableValidationError, match="customer_id"):
            await ai_service.update_customer(
                organization_id=ORG_A,
                customer_id="",
                name="Test",
            )


# ── TEST: CREATE LEAD ─────────────────────────────────────────────────────────


class TestCreateLead:
    """Verifica creazione lead commerciale."""

    async def test_create_lead_basic(self, ai_service, fake_port):
        result = await ai_service.create_lead(
            organization_id=ORG_A,
            name="Azienda XYZ",
            phone="+393330001111",
            source="WhatsApp",
        )
        assert result["id"].startswith("rec")
        table = fake_port._get_table(BASE_ID, "Lead")
        assert len(table) == 1
        assert table[0].fields["Nome Contatto"] == "Azienda XYZ"
        assert table[0].fields["Cellulare"] == "+393330001111"
        assert table[0].fields["Provenienza"] == "WhatsApp"


# ── TEST: CREATE REQUEST ──────────────────────────────────────────────────────


class TestCreateRequest:
    """Verifica registrazione richiesta operativa."""

    async def test_create_request_basic(self, ai_service, fake_port):
        result = await ai_service.create_request(
            organization_id=ORG_A,
            customer_phone="+393330001111",
            details="Richiesta informazioni menu",
            customer_name="Lucia",
            priority="high",
        )
        assert result["id"].startswith("rec")
        table = fake_port._get_table(BASE_ID, "Richieste")
        assert len(table) == 1
        assert table[0].fields["Telefono Cliente"] == "+393330001111"
        assert table[0].fields["Dettagli"] == "Richiesta informazioni menu"
        assert table[0].fields["Priorità"] == "high"


# ── TEST: CREATE TICKET ───────────────────────────────────────────────────────


class TestCreateTicket:
    """Verifica apertura ticket di supporto."""

    async def test_create_ticket_basic(self, ai_service, fake_port):
        result = await ai_service.create_ticket(
            organization_id=ORG_A,
            subject="Problema prenotazione",
            contact_phone="+393330002222",
            description="Non riesco a prenotare per sabato sera",
            priority="urgent",
        )
        assert result["id"].startswith("rec")
        table = fake_port._get_table(BASE_ID, "Ticket")
        assert len(table) == 1
        assert table[0].fields["Oggetto"] == "Problema prenotazione"
        assert table[0].fields["Telefono"] == "+393330002222"
        assert table[0].fields["Priorità"] == "urgent"


# ── TEST: SEARCH RECORDS ─────────────────────────────────────────────────────


class TestSearchRecords:
    """Verifica ricerca generica tra i record del CRM."""

    async def test_search_customers(self, ai_service, fake_port):
        fake_port.seed_record(BASE_ID, "Clienti", {"Nome": "Mario", "Telefono": "+39333"})
        fake_port.seed_record(BASE_ID, "Clienti", {"Nome": "Luigi", "Telefono": "+39444"})

        results = await ai_service.search_records(
            organization_id=ORG_A,
            entity_type="customer",
            query="Mario",
            limit=5,
        )
        assert isinstance(results, list)
        assert len(results) >= 1

    async def test_search_invalid_entity_raises(self, ai_service):
        with pytest.raises(AirtableValidationError, match="non consentito"):
            await ai_service.search_records(
                organization_id=ORG_A,
                entity_type="invoice",  # Non in ALLOWED_AI_ENTITIES
                query="test",
            )

    async def test_search_limit_clamped(self, ai_service, fake_port):
        """Verifica che limit > 20 venga limitato a 20."""
        for i in range(25):
            fake_port.seed_record(BASE_ID, "Clienti", {"Nome": f"Cliente {i}", "Telefono": f"+39{i}"})

        results = await ai_service.search_records(
            organization_id=ORG_A,
            entity_type="customer",
            query="Cliente",
            limit=100,
        )
        # Il service chiama page_size=min(max(1,limit),20) = 20
        assert len(results) <= 20


# ── TEST: DELETE RECORD (WRITE SAFETY) ────────────────────────────────────────


class TestDeleteRecordSafety:
    """Verifica protezione write safety: eliminazione con conferma esplicita obbligatoria."""

    async def test_delete_without_token_raises_confirmation_required(self, ai_service, fake_port):
        rec = fake_port.seed_record(BASE_ID, "Clienti", {"Nome": "Da eliminare", "Telefono": "+39999"})

        with pytest.raises(AirtableConfirmationRequiredError) as exc_info:
            await ai_service.delete_record_safe(
                organization_id=ORG_A,
                entity_type="customer",
                record_id=rec.id,
                confirmation_token=None,
            )

        # L'eccezione deve contenere il token atteso per la conferma
        emitted_token = exc_info.value.confirmation_token
        assert emitted_token.startswith("CONFIRM_DELETE_")
        # Il token NON è più il pattern deterministico legacy fabbricabile dall'LLM
        assert emitted_token != f"CONFIRM_DELETE_{rec.id}"
        assert len(emitted_token) > len("CONFIRM_DELETE_") + 16
        assert exc_info.value.record_id == rec.id

    async def test_delete_with_wrong_token_raises(self, ai_service, fake_port):
        rec = fake_port.seed_record(BASE_ID, "Clienti", {"Nome": "Da eliminare", "Telefono": "+39999"})

        with pytest.raises(AirtableConfirmationRequiredError):
            await ai_service.delete_record_safe(
                organization_id=ORG_A,
                entity_type="customer",
                record_id=rec.id,
                confirmation_token="WRONG_TOKEN",
            )

    async def test_delete_with_correct_token_succeeds(self, ai_service, fake_port):
        rec = fake_port.seed_record(BASE_ID, "Clienti", {"Nome": "Da eliminare", "Telefono": "+39999"})

        # Il token valido è quello emesso dalla richiesta di conferma (HMAC server-side)
        with pytest.raises(AirtableConfirmationRequiredError) as exc_info:
            await ai_service.delete_record_safe(
                organization_id=ORG_A,
                entity_type="customer",
                record_id=rec.id,
                confirmation_token=None,
            )
        emitted_token = exc_info.value.confirmation_token

        result = await ai_service.delete_record_safe(
            organization_id=ORG_A,
            entity_type="customer",
            record_id=rec.id,
            confirmation_token=emitted_token,
        )
        assert result["status"] == "deleted"
        assert result["id"] == rec.id
        assert result["deleted"] is True

    async def test_delete_with_fabricated_legacy_token_fails(self, ai_service, fake_port):
        """Il vecchio token deterministico fabbricabile dall'LLM NON deve più essere accettato."""
        rec = fake_port.seed_record(BASE_ID, "Clienti", {"Nome": "Da eliminare", "Telefono": "+39998"})

        with pytest.raises(AirtableConfirmationRequiredError):
            await ai_service.delete_record_safe(
                organization_id=ORG_A,
                entity_type="customer",
                record_id=rec.id,
                confirmation_token=f"CONFIRM_DELETE_{rec.id}",
            )

    async def test_delete_empty_record_id_raises(self, ai_service):
        with pytest.raises(AirtableValidationError, match="record_id"):
            await ai_service.delete_record_safe(
                organization_id=ORG_A,
                entity_type="customer",
                record_id="",
            )


# ── TEST: SCHEMA MODIFICATION PROHIBITED (Invariante 5) ──────────────────────


class TestSchemaModificationBlocked:
    """Verifica che tutte le operazioni di alterazione schema siano bloccate."""

    async def test_create_table_raises(self, ai_service):
        with pytest.raises(AirtableSchemaModificationProhibitedError):
            await ai_service.create_table()

    async def test_delete_table_raises(self, ai_service):
        with pytest.raises(AirtableSchemaModificationProhibitedError):
            await ai_service.delete_table()

    async def test_create_field_raises(self, ai_service):
        with pytest.raises(AirtableSchemaModificationProhibitedError):
            await ai_service.create_field()

    async def test_update_permissions_raises(self, ai_service):
        with pytest.raises(AirtableSchemaModificationProhibitedError):
            await ai_service.update_permissions()


# ── TEST: INTERDIZIONE SETTORE MEDICO (GDPR Art. 9) ──────────────────────────


class TestMedicalVerticalProhibition:
    """Verifica interdizione categorica per organizzazioni del settore medico/sanitario."""

    @pytest.mark.parametrize("verticale", [
        "studio_medico",
        "studio_medico_dentista",
        "medico",
        "clinica",
        "sanitario",
        "sanita",
        "odontoiatra",
        "dentista",
        "fisioterapia",
        "dottore",
        "poliambulatorio",
        "psicologo",
        "psicoterapeuta",
        "veterinario",
    ])
    async def test_medical_vertical_blocks_find_customer(self, fake_port, mapping_repo, verticale):
        """Ogni verticale medico deve bloccare categoricamente l'accesso AI ad Airtable."""
        core_repo = InMemoryCoreRepo()
        core_repo.set_profile(ORG_MEDICAL, verticale)

        # Configura mapping per org_medical
        mapping_repo.add_mapping(_make_customer_mapping(ORG_MEDICAL))

        service = AirtableAIService(
            port=fake_port,
            mapping_repo=mapping_repo,
            core_repo=core_repo,
        )

        with pytest.raises(AirtableMedicalPolicyError, match="GDPR Art. 9"):
            await service.find_customer(
                organization_id=ORG_MEDICAL,
                phone="+39111",
            )

    async def test_medical_blocks_create_customer(self, fake_port, mapping_repo):
        core_repo = InMemoryCoreRepo()
        core_repo.set_profile(ORG_MEDICAL, "studio_medico")
        mapping_repo.add_mapping(_make_customer_mapping(ORG_MEDICAL))

        service = AirtableAIService(port=fake_port, mapping_repo=mapping_repo, core_repo=core_repo)

        with pytest.raises(AirtableMedicalPolicyError):
            await service.create_customer(
                organization_id=ORG_MEDICAL,
                name="Test",
                phone="+39000",
            )

    async def test_medical_blocks_create_lead(self, fake_port, mapping_repo):
        core_repo = InMemoryCoreRepo()
        core_repo.set_profile(ORG_MEDICAL, "clinica")
        mapping_repo.add_mapping(_make_lead_mapping(ORG_MEDICAL))

        service = AirtableAIService(port=fake_port, mapping_repo=mapping_repo, core_repo=core_repo)

        with pytest.raises(AirtableMedicalPolicyError):
            await service.create_lead(
                organization_id=ORG_MEDICAL,
                name="Test Lead",
                phone="+39111",
            )

    async def test_medical_blocks_search_records(self, fake_port, mapping_repo):
        core_repo = InMemoryCoreRepo()
        core_repo.set_profile(ORG_MEDICAL, "odontoiatra")
        mapping_repo.add_mapping(_make_customer_mapping(ORG_MEDICAL))

        service = AirtableAIService(port=fake_port, mapping_repo=mapping_repo, core_repo=core_repo)

        with pytest.raises(AirtableMedicalPolicyError):
            await service.search_records(
                organization_id=ORG_MEDICAL,
                entity_type="customer",
                query="test",
            )

    async def test_medical_blocks_delete(self, fake_port, mapping_repo):
        core_repo = InMemoryCoreRepo()
        core_repo.set_profile(ORG_MEDICAL, "fisioterapia")
        mapping_repo.add_mapping(_make_customer_mapping(ORG_MEDICAL))

        service = AirtableAIService(port=fake_port, mapping_repo=mapping_repo, core_repo=core_repo)

        with pytest.raises(AirtableMedicalPolicyError):
            await service.delete_record_safe(
                organization_id=ORG_MEDICAL,
                entity_type="customer",
                record_id="rec0001",
                confirmation_token="CONFIRM_DELETE_rec0001",
            )

    async def test_non_medical_vertical_allowed(self, ai_service, fake_port):
        """Un verticale non medico (ristorante) deve poter usare i tool normalmente."""
        result = await ai_service.create_customer(
            organization_id=ORG_A,
            name="Cliente Ristorante",
            phone="+393330000000",
        )
        assert result["id"].startswith("rec")


# ── TEST: ENTITÀ NON AUTORIZZATE ──────────────────────────────────────────────


class TestUnauthorizedEntity:
    """Verifica che entità fuori dalla whitelist ALLOWED_AI_ENTITIES siano bloccate."""

    async def test_disallowed_entity_raises(self, ai_service):
        with pytest.raises(AirtableValidationError, match="non consentito"):
            await ai_service.search_records(
                organization_id=ORG_A,
                entity_type="booking",  # Non in ALLOWED_AI_ENTITIES
                query="test",
            )

    def test_allowed_entities_set(self):
        assert ALLOWED_AI_ENTITIES == frozenset({"customer", "lead", "request", "ticket"})


# ── TEST: FORMULA INJECTION SANITIZATION ──────────────────────────────────────


class TestFormulaInjection:
    """Verifica sanitizzazione contro formula injection."""

    def test_escape_single_quotes(self):
        assert "\\'" in _escape_formula_str("O'Brien")

    def test_escape_backslash(self):
        assert "\\\\" in _escape_formula_str("test\\path")

    def test_escape_newlines(self):
        result = _escape_formula_str("line1\nline2\rline3")
        assert "\n" not in result
        assert "\r" not in result

    def test_empty_string(self):
        assert _escape_formula_str("") == ""

    def test_normal_string_unchanged(self):
        assert _escape_formula_str("Mario Rossi") == "Mario Rossi"


# ── TEST: CREWAI TOOLS (INTEGRAZIONE TOOL → SERVICE → FAKE PORT) ─────────────


class TestCrewAIToolIntegration:
    """Test di integrazione: CrewAI Tool → AirtableAIService → FakeAirtablePort."""

    async def test_find_customer_tool_arun(self, ai_tools, fake_port):
        fake_port.seed_record(BASE_ID, "Clienti", {"Nome": "Tool Test", "Telefono": "+393339999999"})

        find_tool = next(t for t in ai_tools if t.name == "airtable_find_customer")
        result = await find_tool._arun(phone="+393339999999")
        assert "Tool Test" in result or "Nessun cliente" in result

    async def test_create_customer_tool_arun(self, ai_tools, fake_port):
        create_tool = next(t for t in ai_tools if t.name == "airtable_create_customer")
        result = await create_tool._arun(name="Tool Cliente", phone="+393330000001")
        assert "successo" in result.lower() or "creato" in result.lower()

    async def test_update_customer_tool_arun(self, ai_tools, fake_port):
        rec = fake_port.seed_record(BASE_ID, "Clienti", {"Nome": "Da Aggiornare", "Telefono": "+39111"})
        update_tool = next(t for t in ai_tools if t.name == "airtable_update_customer")
        result = await update_tool._arun(customer_id=rec.id, name="Aggiornato")
        assert "aggiornato" in result.lower() or "successo" in result.lower()

    async def test_create_lead_tool_arun(self, ai_tools, fake_port):
        lead_tool = next(t for t in ai_tools if t.name == "airtable_create_lead")
        result = await lead_tool._arun(name="Lead Test", phone="+393330001111", source="WhatsApp")
        assert "successo" in result.lower() or "registrato" in result.lower()

    async def test_create_request_tool_arun(self, ai_tools, fake_port):
        request_tool = next(t for t in ai_tools if t.name == "airtable_create_request")
        result = await request_tool._arun(
            customer_phone="+393330001111",
            details="Richiesta test",
        )
        assert "successo" in result.lower() or "registrat" in result.lower()

    async def test_create_ticket_tool_arun(self, ai_tools, fake_port):
        ticket_tool = next(t for t in ai_tools if t.name == "airtable_create_ticket")
        result = await ticket_tool._arun(
            subject="Test Ticket",
            contact_phone="+393330002222",
            description="Descrizione test",
        )
        assert "successo" in result.lower() or "aperto" in result.lower()

    async def test_search_records_tool_arun(self, ai_tools, fake_port):
        fake_port.seed_record(BASE_ID, "Clienti", {"Nome": "Cerca Me", "Telefono": "+39555"})
        search_tool = next(t for t in ai_tools if t.name == "airtable_search_records")
        result = await search_tool._arun(entity_type="customer", query="Cerca")
        assert "Cerca Me" in result or "Nessun record" in result

    async def test_delete_tool_no_token_returns_confirmation_request(self, ai_tools, fake_port):
        rec = fake_port.seed_record(BASE_ID, "Clienti", {"Nome": "Delete Me", "Telefono": "+39666"})
        delete_tool = next(t for t in ai_tools if t.name == "airtable_delete_record")
        result = await delete_tool._arun(entity_type="customer", record_id=rec.id)
        assert "CONFERMA" in result.upper() or "CONFIRM" in result.upper()

    async def test_delete_tool_with_correct_token_succeeds(self, ai_tools, fake_port, ai_service):
        rec = fake_port.seed_record(BASE_ID, "Clienti", {"Nome": "Delete Me", "Telefono": "+39777"})
        delete_tool = next(t for t in ai_tools if t.name == "airtable_delete_record")

        # Il token valido è quello emesso dalla richiesta di conferma (HMAC server-side)
        with pytest.raises(AirtableConfirmationRequiredError) as exc_info:
            await ai_service.delete_record_safe(
                organization_id=ORG_A,
                entity_type="customer",
                record_id=rec.id,
                confirmation_token=None,
            )
        emitted_token = exc_info.value.confirmation_token

        result = await delete_tool._arun(
            entity_type="customer",
            record_id=rec.id,
            confirmation_token=emitted_token,
        )
        assert "eliminato" in result.lower() or "successo" in result.lower()

    async def test_medical_tool_returns_policy_error_string(self, fake_port, mapping_repo):
        """Un tool per un tenant medico deve restituire un messaggio di errore policy, non sollevare eccezione."""
        core_repo = InMemoryCoreRepo()
        core_repo.set_profile(ORG_MEDICAL, "studio_medico")
        mapping_repo.add_mapping(_make_customer_mapping(ORG_MEDICAL))

        service = AirtableAIService(port=fake_port, mapping_repo=mapping_repo, core_repo=core_repo)
        tools = create_airtable_tools(service=service, organization_id=ORG_MEDICAL)

        find_tool = next(t for t in tools if t.name == "airtable_find_customer")
        # Il tool cattura l'eccezione e restituisce una stringa di errore
        result = await find_tool._arun(phone="+39111")
        assert "POLICY" in result.upper() or "GDPR" in result.upper()


# ── TEST: MAPPING NON CONFIGURATO ────────────────────────────────────────────


class TestMappingNotConfigured:
    """Verifica errore chiaro quando il mapping non è configurato per un tenant."""

    async def test_create_customer_without_mapping_raises(self, fake_port, core_repo):
        """ORG_B non ha mapping configurato → errore esplicito."""
        empty_mapping_repo = InMemoryMappingRepo()
        service = AirtableAIService(
            port=fake_port,
            mapping_repo=empty_mapping_repo,
            core_repo=core_repo,
        )

        from src.integrations.airtable.errors import AirtableMissingFieldMappingError
        with pytest.raises(AirtableMissingFieldMappingError, match="Nessuna tabella configurata"):
            await service.create_customer(
                organization_id=ORG_B,
                name="Test",
                phone="+39000",
            )
