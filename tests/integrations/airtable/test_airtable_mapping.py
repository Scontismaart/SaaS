"""Unit test esaustivi per il sistema di mapping tra modello interno del SaaS e tabelle Airtable.

Verifica:
- Registrazione in TENANT_SCOPED_TABLES (Invariante 1)
- Valid mapping: creazione, recupero e trasformazione bidirezionale
- Missing field: blocco preventivo pre-write se campi interni obbligatori non sono mappati
- Missing data: blocco se mancano i dati obbligatori
- Invalid table: errore chiaro se la tabella non esiste o manca una colonna mappata
- Invalid base: errore chiaro se la base non appartiene al tenant o è inattiva
- Tenant isolation: segregazione totale dei mapping tra organizzazioni diverse
- Create & Update mapping: ciclo di vita completo del mapping
- Data minimization: omissione dei campi interni non mappati nel payload verso Airtable
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.db.scoping import TENANT_SCOPED_TABLES
from src.integrations.airtable import (
    AirtableAdapter,
    AirtableField,
    AirtableInvalidBaseError,
    AirtableInvalidTableError,
    AirtableMappingRepository,
    AirtableMappingService,
    AirtableMissingDataError,
    AirtableMissingFieldMappingError,
    AirtableNotFoundError,
    AirtableTable,
    CreateMappingRequest,
    TableFieldMapping,
    UpdateMappingRequest,
)


# ── FIXTURES & MOCK SETUP ────────────────────────────────────────────────────


@pytest.fixture
def org_a_id() -> uuid.UUID:
    return uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def org_b_id() -> uuid.UUID:
    return uuid.UUID("22222222-2222-2222-2222-222222222222")


class InMemoryMappingRepo:
    """Implementazione in-memory con rispetto rigoroso di tenant isolation per test unitari veloci."""

    def __init__(self):
        # Chiave: (organization_id, base_id, table_id_or_name, entity_type)
        self._store: dict[tuple[uuid.UUID, str, str, str], TableFieldMapping] = {}

    async def save_mapping(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
        table_id_or_name: str,
        entity_type: str,
        field_mappings: dict[str, str],
        required_fields: list[str] | None = None,
        is_active: bool = True,
    ) -> TableFieldMapping:
        org_uuid = uuid.UUID(str(organization_id))
        key = (org_uuid, base_id.strip(), table_id_or_name.strip(), entity_type.strip().lower())
        mapping = TableFieldMapping(
            id=uuid.uuid4(),
            organization_id=org_uuid,
            base_id=base_id.strip(),
            table_id_or_name=table_id_or_name.strip(),
            entity_type=entity_type.strip().lower(),
            field_mappings=field_mappings,
            required_fields=required_fields or [],
            is_active=is_active,
        )
        self._store[key] = mapping
        return mapping

    async def get_mapping(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
        table_id_or_name: str,
        entity_type: str,
    ) -> TableFieldMapping | None:
        org_uuid = uuid.UUID(str(organization_id))
        key = (org_uuid, base_id.strip(), table_id_or_name.strip(), entity_type.strip().lower())
        return self._store.get(key)

    async def list_mappings(
        self,
        organization_id: uuid.UUID | str,
        base_id: str | None = None,
        only_active: bool = True,
    ) -> list[TableFieldMapping]:
        org_uuid = uuid.UUID(str(organization_id))
        results = []
        for (o, b, t, e), m in self._store.items():
            if o == org_uuid:
                if base_id and b != base_id.strip():
                    continue
                if only_active and not m.is_active:
                    continue
                results.append(m)
        return results

    async def delete_mapping(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
        table_id_or_name: str,
        entity_type: str,
    ) -> bool:
        org_uuid = uuid.UUID(str(organization_id))
        key = (org_uuid, base_id.strip(), table_id_or_name.strip(), entity_type.strip().lower())
        if key in self._store:
            del self._store[key]
            return True
        return False


class InMemoryConnectionRepo:
    """Mock del connection repository per verifica appartenenza Base."""

    def __init__(self):
        # (organization_id, base_id) -> dict
        self._connections: dict[tuple[uuid.UUID, str], dict] = {}

    def add_connection(self, organization_id: uuid.UUID, base_id: str, is_active: bool = True):
        self._connections[(organization_id, base_id)] = {
            "organization_id": organization_id,
            "base_id": base_id,
            "is_active": is_active,
        }

    async def get_connection(self, organization_id: uuid.UUID | str, base_id: str):
        org_uuid = uuid.UUID(str(organization_id))
        return self._connections.get((org_uuid, base_id.strip()))


# ── 1. TEST TENANT SCOPING REGISTRATION ──────────────────────────────────────


def test_airtable_field_mappings_in_tenant_scoped_tables():
    """Invariante 1 & 2: La tabella airtable_field_mappings deve essere registrata tra le tenant-scoped."""
    assert "airtable_field_mappings" in TENANT_SCOPED_TABLES


# ── 2. TEST VALID MAPPING & BIDIRECTIONAL TRANSFORMATION ─────────────────────


@pytest.mark.asyncio
async def test_valid_mapping_creation_and_payload_transformation(org_a_id):
    mapping_repo = InMemoryMappingRepo()
    conn_repo = InMemoryConnectionRepo()
    conn_repo.add_connection(org_a_id, "appClienti")

    service = AirtableMappingService(mapping_repo=mapping_repo, connection_repo=conn_repo)

    req = CreateMappingRequest(
        base_id="appClienti",
        table_id_or_name="Customers",
        entity_type="customer",
        field_mappings={
            "customer.name": "Nome",
            "customer.phone": "Telefono",
            "customer.email": "Email",
        },
    )

    created = await service.create_or_update_mapping(org_a_id, req)
    assert created.organization_id == org_a_id
    assert created.table_id_or_name == "Customers"
    assert created.field_mappings["customer.name"] == "Nome"
    assert "customer.name" in created.required_fields

    # Verifica trasformazione per una write: solo i campi mappati devono essere inclusi
    internal_data = {
        "customer.name": "Mario Rossi",
        "customer.phone": "+393331122334",
        "customer.email": "mario@example.com",
        "sensitive_internal_note": "DA NON INVIARE",  # Non mappato: deve essere escluso (data minimization)
    }
    payload = await service.prepare_write_payload(
        organization_id=org_a_id,
        base_id="appClienti",
        table_id_or_name="Customers",
        entity_type="customer",
        internal_data=internal_data,
    )

    assert "fields" in payload
    fields = payload["fields"]
    assert fields["Nome"] == "Mario Rossi"
    assert fields["Telefono"] == "+393331122334"
    assert fields["Email"] == "mario@example.com"
    assert "sensitive_internal_note" not in fields
    assert "DA NON INVIARE" not in str(fields)


@pytest.mark.asyncio
async def test_reverse_transformation_from_airtable(org_a_id):
    mapping = TableFieldMapping(
        organization_id=org_a_id,
        base_id="appCRM",
        table_id_or_name="Leads",
        entity_type="lead",
        field_mappings={
            "lead.name": "Full Name",
            "lead.phone": "Mobile",
            "lead.status": "Stato Lead",
        },
        required_fields=["lead.name", "lead.phone"],
    )

    airtable_record_fields = {
        "Full Name": "Giulia Bianchi",
        "Mobile": "+393470000000",
        "Stato Lead": "Qualificato",
        "AirtableInternalField": "ignorato",
    }

    internal = mapping.transform_from_airtable(airtable_record_fields)
    assert internal["lead.name"] == "Giulia Bianchi"
    assert internal["lead.phone"] == "+393470000000"
    assert internal["lead.status"] == "Qualificato"
    assert "AirtableInternalField" not in internal


# ── 3. TEST MISSING FIELD VALIDATION ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_required_field_in_mapping_definition(org_a_id):
    """Tentativo di creare un mapping dove un campo interno obbligatorio manca."""
    mapping_repo = InMemoryMappingRepo()
    conn_repo = InMemoryConnectionRepo()
    conn_repo.add_connection(org_a_id, "appCRM")
    service = AirtableMappingService(mapping_repo=mapping_repo, connection_repo=conn_repo)

    # Entità customer richiede ["customer.name", "customer.phone"].
    # Mappiamo solo il nome, omettendo il telefono.
    req = CreateMappingRequest(
        base_id="appCRM",
        table_id_or_name="Customers",
        entity_type="customer",
        field_mappings={"customer.name": "Nome"},
    )

    with pytest.raises(AirtableMissingFieldMappingError) as exc_info:
        await service.create_or_update_mapping(org_a_id, req)

    assert exc_info.value.status_code == 400
    assert "customer.phone" in exc_info.value.missing_fields
    assert "customer.phone" in str(exc_info.value)


@pytest.mark.asyncio
async def test_missing_mapping_blocks_write_preemptively(org_a_id):
    """Se non esiste alcuna configurazione per la tabella, la write viene bloccata preventivamente."""
    mapping_repo = InMemoryMappingRepo()
    conn_repo = InMemoryConnectionRepo()
    conn_repo.add_connection(org_a_id, "appCRM")
    service = AirtableMappingService(mapping_repo=mapping_repo, connection_repo=conn_repo)

    with pytest.raises(AirtableMissingFieldMappingError) as exc_info:
        await service.prepare_write_payload(
            organization_id=org_a_id,
            base_id="appCRM",
            table_id_or_name="NonConfigurata",
            entity_type="customer",
            internal_data={"name": "Mario", "phone": "+39111"},
        )
    assert "Nessuna configurazione di mapping trovata" in str(exc_info.value)


@pytest.mark.asyncio
async def test_missing_data_for_mapped_required_field_raises_error(org_a_id):
    """Se il mapping è corretto ma i dati forniti non contengono il valore per un campo obbligatorio."""
    mapping_repo = InMemoryMappingRepo()
    conn_repo = InMemoryConnectionRepo()
    conn_repo.add_connection(org_a_id, "appCRM")
    service = AirtableMappingService(mapping_repo=mapping_repo, connection_repo=conn_repo)

    req = CreateMappingRequest(
        base_id="appCRM",
        table_id_or_name="Customers",
        entity_type="customer",
        field_mappings={"customer.name": "Nome", "customer.phone": "Telefono"},
    )
    await service.create_or_update_mapping(org_a_id, req)

    # Dati interni privi di telefono
    with pytest.raises(AirtableMissingDataError) as exc_info:
        await service.prepare_write_payload(
            organization_id=org_a_id,
            base_id="appCRM",
            table_id_or_name="Customers",
            entity_type="customer",
            internal_data={"customer.name": "Mario Rossi", "customer.phone": ""},
        )
    assert "customer.phone" in exc_info.value.missing_fields


# ── 4. TEST INVALID TABLE & SCHEMA VALIDATION ────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_table_not_in_airtable_schema(org_a_id):
    """Verifica che la tabella esista nella Base Airtable quando validata con adapter."""
    mapping_repo = InMemoryMappingRepo()
    conn_repo = InMemoryConnectionRepo()
    conn_repo.add_connection(org_a_id, "appCRM")
    service = AirtableMappingService(mapping_repo=mapping_repo, connection_repo=conn_repo)

    # Mock adapter che simula tabella inesistente
    mock_adapter = MagicMock()
    mock_adapter.validate_table_schema = AsyncMock(
        return_value=MagicMock(
            is_valid=False,
            error_message="Tabella 'TabellaInesistente' non trovata nella Base 'appCRM'.",
            missing_fields=[],
        )
    )

    req = CreateMappingRequest(
        base_id="appCRM",
        table_id_or_name="TabellaInesistente",
        entity_type="customer",
        field_mappings={"customer.name": "Nome", "customer.phone": "Telefono"},
    )

    with pytest.raises(AirtableInvalidTableError) as exc_info:
        await service.create_or_update_mapping(org_a_id, req, adapter=mock_adapter)

    assert "Tabella 'TabellaInesistente' non trovata" in str(exc_info.value)


@pytest.mark.asyncio
async def test_invalid_table_missing_mapped_columns(org_a_id):
    """Verifica che tutte le colonne Airtable mappate esistano davvero nella tabella."""
    mapping_repo = InMemoryMappingRepo()
    conn_repo = InMemoryConnectionRepo()
    conn_repo.add_connection(org_a_id, "appCRM")
    service = AirtableMappingService(mapping_repo=mapping_repo, connection_repo=conn_repo)

    # Mock adapter che trova la tabella ma segnala che 'ColonnaFantasma' non esiste
    mock_adapter = MagicMock()
    mock_adapter.validate_table_schema = AsyncMock(
        return_value=MagicMock(
            is_valid=False,
            error_message=None,
            missing_fields=["ColonnaFantasma"],
        )
    )

    req = CreateMappingRequest(
        base_id="appCRM",
        table_id_or_name="Customers",
        entity_type="customer",
        field_mappings={"customer.name": "Nome", "customer.phone": "ColonnaFantasma"},
    )

    with pytest.raises(AirtableInvalidTableError) as exc_info:
        await service.create_or_update_mapping(org_a_id, req, adapter=mock_adapter)

    assert "ColonnaFantasma" in str(exc_info.value)


# ── 5. TEST INVALID BASE VALIDATION ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_base_not_connected_for_tenant(org_a_id):
    mapping_repo = InMemoryMappingRepo()
    conn_repo = InMemoryConnectionRepo()
    # Connessione non registrata per org_a_id
    service = AirtableMappingService(mapping_repo=mapping_repo, connection_repo=conn_repo)

    req = CreateMappingRequest(
        base_id="appNonConnessa",
        table_id_or_name="Customers",
        entity_type="customer",
        field_mappings={"customer.name": "Nome", "customer.phone": "Telefono"},
    )

    with pytest.raises(AirtableInvalidBaseError) as exc_info:
        await service.create_or_update_mapping(org_a_id, req)

    assert "non valida o non associata" in str(exc_info.value)
    assert "appNonConnessa" in str(exc_info.value)


@pytest.mark.asyncio
async def test_invalid_base_inactive_connection(org_a_id):
    mapping_repo = InMemoryMappingRepo()
    conn_repo = InMemoryConnectionRepo()
    conn_repo.add_connection(org_a_id, "appDisattivata", is_active=False)
    service = AirtableMappingService(mapping_repo=mapping_repo, connection_repo=conn_repo)

    req = CreateMappingRequest(
        base_id="appDisattivata",
        table_id_or_name="Customers",
        entity_type="customer",
        field_mappings={"customer.name": "Nome", "customer.phone": "Telefono"},
    )

    with pytest.raises(AirtableInvalidBaseError) as exc_info:
        await service.create_or_update_mapping(org_a_id, req)

    assert "disattivata o sospesa" in str(exc_info.value)


# ── 6. TEST TENANT ISOLATION ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_isolation_strict_segregation(org_a_id, org_b_id):
    """Invariante 1: L'Organizzazione A e l'Organizzazione B non possono accedere o sovrascrivere i rispettivi mapping."""
    mapping_repo = InMemoryMappingRepo()
    conn_repo = InMemoryConnectionRepo()
    conn_repo.add_connection(org_a_id, "appSharedBaseId")
    conn_repo.add_connection(org_b_id, "appSharedBaseId")

    service = AirtableMappingService(mapping_repo=mapping_repo, connection_repo=conn_repo)

    # 1. Org A configura mapping verso colonna italiana "Nome" e "Telefono"
    req_a = CreateMappingRequest(
        base_id="appSharedBaseId",
        table_id_or_name="Contacts",
        entity_type="customer",
        field_mappings={"customer.name": "Nome", "customer.phone": "Telefono"},
    )
    await service.create_or_update_mapping(org_a_id, req_a)

    # 2. Org B configura mapping verso colonna inglese "Full Name" e "Mobile"
    req_b = CreateMappingRequest(
        base_id="appSharedBaseId",
        table_id_or_name="Contacts",
        entity_type="customer",
        field_mappings={"customer.name": "Full Name", "customer.phone": "Mobile"},
    )
    await service.create_or_update_mapping(org_b_id, req_b)

    # 3. Verifica che ciascuna organizzazione legga esclusivamente il proprio mapping
    mapping_a = await service.get_mapping(org_a_id, "appSharedBaseId", "Contacts", "customer")
    mapping_b = await service.get_mapping(org_b_id, "appSharedBaseId", "Contacts", "customer")

    assert mapping_a.field_mappings["customer.name"] == "Nome"
    assert mapping_b.field_mappings["customer.name"] == "Full Name"

    # 4. Org A non può cancellare il mapping di Org B
    deleted = await service.delete_mapping(org_a_id, "appSharedBaseId", "Contacts", "customer")
    assert deleted is True

    # Mapping di Org B è ancora intatto
    mapping_b_after = await service.get_mapping(org_b_id, "appSharedBaseId", "Contacts", "customer")
    assert mapping_b_after is not None
    assert mapping_b_after.field_mappings["customer.name"] == "Full Name"


# ── 7. TEST CREATE & UPDATE MAPPING LIFECYCLE ────────────────────────────────


@pytest.mark.asyncio
async def test_mapping_update_lifecycle(org_a_id):
    mapping_repo = InMemoryMappingRepo()
    conn_repo = InMemoryConnectionRepo()
    conn_repo.add_connection(org_a_id, "appCRM")
    service = AirtableMappingService(mapping_repo=mapping_repo, connection_repo=conn_repo)

    # 1. Create
    req = CreateMappingRequest(
        base_id="appCRM",
        table_id_or_name="Clienti",
        entity_type="customer",
        field_mappings={"customer.name": "Nome", "customer.phone": "Telefono"},
    )
    created = await service.create_or_update_mapping(org_a_id, req)
    assert "customer.email" not in created.field_mappings

    # 2. Update: aggiunta campo email
    update_req = UpdateMappingRequest(
        field_mappings={"customer.email": "Email"},
    )
    updated = await service.update_mapping(
        org_a_id,
        base_id="appCRM",
        table_id_or_name="Clienti",
        entity_type="customer",
        request=update_req,
    )
    assert updated.field_mappings["customer.name"] == "Nome"
    assert updated.field_mappings["customer.email"] == "Email"

    # 3. Update su tabella non esistente solleva 404
    with pytest.raises(AirtableNotFoundError):
        await service.update_mapping(
            org_a_id,
            base_id="appCRM",
            table_id_or_name="Inesistente",
            entity_type="customer",
            request=update_req,
        )


# ── 8. TEST SQL REPOSITORY IMPLEMENTATION (SCOPED CONNECTION & AST) ──────────


@pytest.mark.asyncio
async def test_sql_mapping_repo_uses_scoped_conn_and_has_org_id():
    """Verifica che AirtableMappingRepository esegua query con organization_id e passi assert_org_scoped."""
    mock_conn = MagicMock()
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    repo = AirtableMappingRepository(pool=mock_pool)
    org_id = uuid.uuid4()

    mock_row = {
        "id": uuid.uuid4(),
        "organization_id": org_id,
        "base_id": "app1",
        "table_id_or_name": "Tbl",
        "entity_type": "customer",
        "field_mappings": json.dumps({"customer.name": "Nome", "customer.phone": "Tel"}),
        "required_fields": ["customer.name", "customer.phone"],
        "is_active": True,
        "created_at": None,
        "updated_at": None,
    }
    mock_conn.fetchrow = AsyncMock(return_value=mock_row)
    mock_conn.fetch = AsyncMock(return_value=[mock_row])
    mock_conn.execute = AsyncMock(return_value="DELETE 1")

    # 1. Save
    res_save = await repo.save_mapping(
        org_id, "app1", "Tbl", "customer",
        {"customer.name": "Nome", "customer.phone": "Tel"},
        ["customer.name", "customer.phone"],
    )
    assert res_save.organization_id == org_id
    save_sql = mock_conn.fetchrow.call_args[0][0]
    assert "organization_id" in save_sql
    assert "airtable_field_mappings" in save_sql

    # 2. Get
    res_get = await repo.get_mapping(org_id, "app1", "Tbl", "customer")
    assert res_get.table_id_or_name == "Tbl"
    get_sql = mock_conn.fetchrow.call_args[0][0]
    assert "organization_id = $1" in get_sql

    # 3. List
    res_list = await repo.list_mappings(org_id, "app1")
    assert len(res_list) == 1
    list_sql = mock_conn.fetch.call_args[0][0]
    assert "organization_id = $1" in list_sql

    # 4. Delete
    res_del = await repo.delete_mapping(org_id, "app1", "Tbl", "customer")
    assert res_del is True
    del_sql = mock_conn.execute.call_args[0][0]
    assert "organization_id = $1" in del_sql
