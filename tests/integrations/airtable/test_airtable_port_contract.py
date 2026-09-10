"""Test di contratto Port ↔ Adapter ↔ Fake ↔ AirtableAIService.

Hardening: garantisce che esista UNA SOLA convenzione tra AirtableAIService,
AirtablePort, AirtableAdapter e i fake di test. Se Service e Port divergono
nuovamente (table_name / filter_by_formula / destructive_replace / chiamate
senza DTO), questi test falliscono esplicitamente.

Copre:
1. Port/Adapter signature compatibility (inspect + isinstance)
2. Fake implementation → Port (stessa firma canonica)
3. AI Service → Port (runtime, create/update/delete/search)
4. Mapping validation (entità non autorizzate, mapping mancante)
5. Tenant isolation (compact end-to-end)
6. Destructive confirmation (token HMAC, niente token fabbricabile)
7. Static scan: nessun kwargs legacy nel service, nessun HTTP nel layer AI
"""
from __future__ import annotations

import inspect
import uuid
from pathlib import Path

import pytest

from src.integrations.airtable import (
    AirtableAdapter,
    AirtablePort,
)
from tests.integrations.airtable.test_airtable_ai_tools import FakeAirtablePort
from src.integrations.airtable.ai_service import (
    ALLOWED_AI_ENTITIES,
    AirtableAIService,
    _compute_delete_confirmation_token,
)
from src.integrations.airtable.errors import (
    AirtableConfirmationRequiredError,
    AirtableMissingFieldMappingError,
    AirtableValidationError,
)
from src.integrations.airtable.models import (
    CreateRecordRequest,
    TableFieldMapping,
    UpdateRecordRequest,
)

ORG_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
ORG_B = uuid.UUID("22222222-2222-2222-2222-222222222222")
# Base di default risolta dal service in modalità port iniettato (convenzione esistente)
BASE_ID = "app_test_mock"
TABLE_ID = "tblClienti001"

# Metodi del Port usati da AirtableAIService (contratto da presidiare)
AI_USED_PORT_METHODS = ["search_records", "create_record", "update_record", "delete_record"]

CANONICAL_SIGNATURES = {
    "search_records": ["base_id", "table_id_or_name", "formula", "max_records"],
    "create_record": ["base_id", "table_id_or_name", "request"],
    "update_record": ["base_id", "table_id_or_name", "record_id", "request"],
    "delete_record": ["base_id", "table_id_or_name", "record_id"],
}

FORBIDDEN_LEGACY_KWARGS = ["table_name=", "filter_by_formula=", "destructive_replace="]


# ── STRICT FAKE = UNICO FAKE CANONICO (eredita AirtablePort) ─────────────────
# Unificato con FakeAirtablePort di test_airtable_ai_tools.py: un solo fake,
# stessa firma e stessa semantica del Port. Qualsiasi chiamata legacy -> TypeError,
# record mancante -> AirtableNotFoundError (come HTTP 404 dell'Adapter).


StrictContractFakePort = FakeAirtablePort


# ── HELPERS ──────────────────────────────────────────────────────────────────


def _make_mapping(org_id: uuid.UUID) -> TableFieldMapping:
    return TableFieldMapping(
        organization_id=org_id,
        base_id=BASE_ID,
        table_id_or_name=TABLE_ID,
        entity_type="customer",
        field_mappings={
            "customer.name": "Nome",
            "customer.phone": "Telefono",
            "customer.email": "Email",
            "customer.notes": "Note",
        },
        required_fields=["customer.name", "customer.phone"],
    )


class InMemoryMappingRepo:
    def __init__(self):
        self._mappings: dict[tuple[str, str, str], TableFieldMapping] = {}

    def add(self, mapping: TableFieldMapping) -> None:
        key = (str(mapping.organization_id), mapping.base_id, mapping.entity_type)
        self._mappings[key] = mapping

    async def get_mapping_by_entity(self, organization_id, base_id, entity_type):
        return self._mappings.get((str(organization_id), base_id, entity_type.strip().lower()))


class InMemoryCoreRepo:
    def __init__(self):
        self._profiles: dict[str, dict] = {}

    def set_profile(self, organization_id, verticale: str) -> None:
        self._profiles[str(organization_id)] = {"verticale": verticale}

    async def get_onboarding_profile(self, organization_id):
        return self._profiles.get(str(organization_id))


def _make_service(port, org_id: uuid.UUID = ORG_A) -> AirtableAIService:
    mapping_repo = InMemoryMappingRepo()
    mapping_repo.add(_make_mapping(org_id))
    return AirtableAIService(port=port, mapping_repo=mapping_repo, core_repo=InMemoryCoreRepo())


# ── 1. PORT/ADAPTER SIGNATURE COMPATIBILITY ──────────────────────────────────


def _param_names(func) -> list[str]:
    return [p for p in inspect.signature(func).parameters if p != "self"]


def test_adapter_is_airtable_port():
    """AirtableAdapter implementa il contratto AirtablePort."""
    assert issubclass(AirtableAdapter, AirtablePort)


def test_fake_is_airtable_port():
    """Il fake UNICO eredita AirtablePort: la divergenza fallisce all'istanziazione."""
    assert issubclass(FakeAirtablePort, AirtablePort)
    assert issubclass(StrictContractFakePort, AirtablePort)
    # L'ereditarietà impone tutti i metodi astratti implementati
    assert set(getattr(FakeAirtablePort, "__abstractmethods__", ())) == set()


@pytest.mark.parametrize("method", AI_USED_PORT_METHODS)
def test_adapter_signature_matches_canonical_contract(method):
    """L'Adapter implementa esattamente la firma canonica del Port (nessuna API parallela)."""
    assert _param_names(getattr(AirtablePort, method)) == CANONICAL_SIGNATURES[method]
    assert _param_names(getattr(AirtableAdapter, method)) == _param_names(getattr(AirtablePort, method))


def test_create_records_signature_supports_dto():
    """create_records batch accetta CreateRecordRequest sia sul Port che sull'Adapter."""
    import typing

    for cls in (AirtablePort, AirtableAdapter, FakeAirtablePort):
        ann = typing.get_type_hints(getattr(cls, "create_records"))
        records_ann = str(ann.get("records", ""))
        assert "CreateRecordRequest" in records_ann, f"{cls.__name__}.create_records senza CreateRecordRequest"


def test_search_records_formula_is_optional():
    """search_records.formula è opzionale (None = nessun filtro)."""
    import inspect as _inspect

    for cls in (AirtablePort, AirtableAdapter, FakeAirtablePort):
        sig = _inspect.signature(getattr(cls, "search_records"))
        param = sig.parameters["formula"]
        assert param.default is None, f"{cls.__name__}.search_records.formula deve defaultare a None"


@pytest.mark.parametrize("method", AI_USED_PORT_METHODS)
def test_fake_signature_matches_port_contract(method):
    """Il fake implementa la STESSA firma del Port: se divergono, i test falliscono."""
    assert _param_names(getattr(FakeAirtablePort, method)) == CANONICAL_SIGNATURES[method]
    assert _param_names(getattr(StrictContractFakePort, method)) == CANONICAL_SIGNATURES[method]


# ── 2. STATIC SCAN: NESSUN KWARGS LEGACY NEL SERVICE ─────────────────────────


def test_ai_service_has_no_legacy_port_kwargs():
    """Ricerca statica: il service non usa più table_name / filter_by_formula / destructive_replace."""
    source = Path("src/integrations/airtable/ai_service.py").read_text(encoding="utf-8")
    for legacy in FORBIDDEN_LEGACY_KWARGS:
        assert legacy not in source, f"kwargs legacy '{legacy}' ancora presente in ai_service.py"


def test_ai_tools_have_no_legacy_port_kwargs_and_no_http():
    """Il layer AI non fa HTTP e non usa kwargs legacy: passa solo dal service."""
    for file in ("ai_tools.py", "ai_service.py"):
        source = Path("src/integrations/airtable", file).read_text(encoding="utf-8")
        for legacy in FORBIDDEN_LEGACY_KWARGS:
            assert legacy not in source, f"kwargs legacy '{legacy}' in {file}"
        for http_marker in ("httpx", "requests.", "api.airtable.com"):
            assert http_marker not in source, f"HTTP diretto ('{http_marker}') non ammesso in {file}"


# ── 3. AI SERVICE → PORT RUNTIME (create/update/delete/search) ───────────────


class TestServiceToPortRuntime:
    """Runtime end-to-end sul contratto: Service → Port canonico (strict fake)."""

    async def test_create_customer(self):
        port = StrictContractFakePort()
        service = _make_service(port)

        result = await service.create_customer(
            organization_id=ORG_A, name="Mario Rossi", phone="+393331234567"
        )

        assert result["id"].startswith("rec")
        assert result["customer.name"] == "Mario Rossi"
        assert result["customer.phone"] == "+393331234567"
        # Il record è stato scritto sulla tabella mappata con i campi Airtable corretti
        seeded = port._tables[(BASE_ID, TABLE_ID)][0]
        assert seeded.fields == {"Nome": "Mario Rossi", "Telefono": "+393331234567"}

    async def test_update_record(self):
        port = StrictContractFakePort()
        service = _make_service(port)
        rec = port.seed(BASE_ID, TABLE_ID, {"Nome": "Old", "Telefono": "+39000", "Email": "x@y.it"})

        result = await service.update_customer(
            organization_id=ORG_A, customer_id=rec.id, name="New"
        )

        assert result["id"] == rec.id
        # PATCH merge: i campi non toccati restano invariati
        assert rec.fields["Nome"] == "New"
        assert rec.fields["Telefono"] == "+39000"
        assert rec.fields["Email"] == "x@y.it"

    async def test_delete_record(self):
        port = StrictContractFakePort()
        service = _make_service(port)
        rec = port.seed(BASE_ID, TABLE_ID, {"Nome": "Da eliminare", "Telefono": "+39999"})

        with pytest.raises(AirtableConfirmationRequiredError) as exc_info:
            await service.delete_record_safe(
                organization_id=ORG_A, entity_type="customer", record_id=rec.id
            )
        token = exc_info.value.confirmation_token

        result = await service.delete_record_safe(
            organization_id=ORG_A, entity_type="customer", record_id=rec.id, confirmation_token=token
        )
        assert result["status"] == "deleted"
        assert result["deleted"] is True
        assert port._tables[(BASE_ID, TABLE_ID)] == []

    async def test_search_records(self):
        port = StrictContractFakePort()
        service = _make_service(port)
        port.seed(BASE_ID, TABLE_ID, {"Nome": "Mario", "Telefono": "+39111"})
        port.seed(BASE_ID, TABLE_ID, {"Nome": "Luigi", "Telefono": "+39222"})

        results = await service.search_records(
            organization_id=ORG_A, entity_type="customer", query="Mario"
        )

        # La formula (sanitizzata) è stata passata al Port: il filtering reale è server-side
        assert "mario" in port.last_formula.lower()
        # Il fake restituisce tutta la tabella trasformata verso il modello interno
        assert len(results) == 2
        assert results[0]["customer.name"] == "Mario"
        assert results[1]["customer.name"] == "Luigi"


# ── 4. MAPPING VALIDATION ────────────────────────────────────────────────────


class TestMappingValidation:
    async def test_entity_not_allowed_raises(self):
        service = _make_service(StrictContractFakePort())

        with pytest.raises(AirtableValidationError, match="non consentito"):
            await service.search_records(
                organization_id=ORG_A, entity_type="booking", query="test"
            )

    async def test_missing_mapping_raises(self):
        port = StrictContractFakePort()
        service = AirtableAIService(port=port, mapping_repo=InMemoryMappingRepo(), core_repo=InMemoryCoreRepo())

        with pytest.raises(AirtableMissingFieldMappingError):
            await service.create_customer(organization_id=ORG_A, name="X", phone="+39000")


# ── 5. TENANT ISOLATION (compact) ────────────────────────────────────────────


class TestTenantIsolationContract:
    async def test_org_b_cannot_use_org_a_data(self):
        """ORG_B (senza mapping) non accede ai dati/mapping di ORG_A sullo stesso port."""
        port = StrictContractFakePort()
        service = _make_service(port, org_id=ORG_A)  # mapping registrato solo per ORG_A

        with pytest.raises(AirtableMissingFieldMappingError):
            await service.search_records(organization_id=ORG_B, entity_type="customer", query="Mario")


# ── 6. DESTRUCTIVE CONFIRMATION ──────────────────────────────────────────────


class TestDestructiveConfirmationContract:
    async def test_legacy_deterministic_token_rejected(self):
        """Il vecchio token deterministico CONFIRM_DELETE_{record_id} NON è più valido."""
        port = StrictContractFakePort()
        service = _make_service(port)
        rec = port.seed(BASE_ID, TABLE_ID, {"Nome": "X", "Telefono": "+39000"})

        with pytest.raises(AirtableConfirmationRequiredError):
            await service.delete_record_safe(
                organization_id=ORG_A,
                entity_type="customer",
                record_id=rec.id,
                confirmation_token=f"CONFIRM_DELETE_{rec.id}",
            )

    async def test_token_is_hmac_bound_to_org_entity_record(self):
        """Il token dipende da tenant+entità+record: non riutilizzabile cross-record/cross-tenant."""
        token_a = _compute_delete_confirmation_token(ORG_A, "customer", "rec1")
        token_b = _compute_delete_confirmation_token(ORG_B, "customer", "rec1")
        token_c = _compute_delete_confirmation_token(ORG_A, "lead", "rec1")
        token_d = _compute_delete_confirmation_token(ORG_A, "customer", "rec2")

        assert len({token_a, token_b, token_c, token_d}) == 4
        assert token_a.startswith("CONFIRM_DELETE_")

    async def test_cross_record_token_rejected(self):
        """Un token valido per un record non vale per un altro record dello stesso tenant."""
        port = StrictContractFakePort()
        service = _make_service(port)
        rec1 = port.seed(BASE_ID, TABLE_ID, {"Nome": "A", "Telefono": "+39111"})
        rec2 = port.seed(BASE_ID, TABLE_ID, {"Nome": "B", "Telefono": "+39222"})

        with pytest.raises(AirtableConfirmationRequiredError) as exc_info:
            await service.delete_record_safe(
                organization_id=ORG_A, entity_type="customer", record_id=rec1.id
            )
        token_rec1 = exc_info.value.confirmation_token

        with pytest.raises(AirtableConfirmationRequiredError):
            await service.delete_record_safe(
                organization_id=ORG_A,
                entity_type="customer",
                record_id=rec2.id,
                confirmation_token=token_rec1,
            )

    async def test_medical_policy_gates_before_confirmation(self):
        """Il divieto medico (GDPR Art. 9) prevale sulla richiesta di conferma: fail-closed."""
        from src.integrations.airtable.errors import AirtableMedicalPolicyError

        port = StrictContractFakePort()
        core_repo = InMemoryCoreRepo()
        core_repo.set_profile(ORG_B, "studio_medico")
        mapping_repo = InMemoryMappingRepo()
        mapping_repo.add(_make_mapping(ORG_B))
        service = AirtableAIService(port=port, mapping_repo=mapping_repo, core_repo=core_repo)

        with pytest.raises(AirtableMedicalPolicyError):
            await service.delete_record_safe(
                organization_id=ORG_B,
                entity_type="customer",
                record_id="rec0001",
                confirmation_token=None,
            )


# ── 7. ENTITÀ AUTORIZZATE (canone invariato) ─────────────────────────────────


def test_allowed_entities_canonical_set():
    assert ALLOWED_AI_ENTITIES == frozenset({"customer", "lead", "request", "ticket"})
