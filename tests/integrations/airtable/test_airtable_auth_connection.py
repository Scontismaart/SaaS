"""Test per Authentication e Connection Management di Airtable.

Verifica:
- Registrazione in TENANT_SCOPED_TABLES (Invariante 1)
- Cifratura at-rest Fernet (Invariante 10)
- Gestione connessioni (PAT valido, token invalido, token mancante, unauthorized, base inesistente)
- Disconnessione e revoca
- Gate bloccante di validazione schema (validate_table_schema)
- Zero secrets leak nelle risposte e nei log
- Integrazione con gli endpoint REST FastAPI
"""
import json
import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.core.db.scoping import TENANT_SCOPED_TABLES
from src.integrations.airtable import (
    AirtableAdapter,
    AirtableAuthError,
    AirtableMedicalPolicyError,
    AirtableNotFoundError,
    AirtableQuotaExhaustedError,
    AirtableRateLimitError,
)
from src.integrations.airtable.repository import AirtableConnectionRepository
from src.integrations.airtable.service import AirtableConnectionService


@pytest.fixture(autouse=True)
def setup_encryption_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("ENCRYPTION_KEY", key)
    return key


# ── 1. TEST TENANT SCOPING & CRITTOGRAFIA ────────────────────────────────────


def test_airtable_connections_in_tenant_scoped_tables():
    """Invariante 1 & 2: La tabella airtable_connections deve essere registrata tra le tenant-scoped."""
    assert "airtable_connections" in TENANT_SCOPED_TABLES


@pytest.mark.asyncio
async def test_airtable_connection_repo_crypto_roundtrip():
    """Invariante 10: Il PAT deve essere cifrato at-rest e decifrato solo per uso interno."""
    mock_conn = MagicMock()
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    repo = AirtableConnectionRepository(pool=mock_pool)
    raw_token = "pat_super_secret_token_12345"
    org_id = uuid.uuid4()
    base_id = "appTestCRM123"

    # 1. Verifica crittografia a livello di helper
    encrypted = repo.encrypt_credentials({"token": raw_token, "token_type": "pat"})
    assert raw_token not in encrypted
    decrypted = repo.decrypt_credentials(encrypted)
    assert decrypted["token"] == raw_token

    # 2. Simula salvataggio connessione
    mock_conn.fetchrow = AsyncMock(
        return_value={
            "id": uuid.uuid4(),
            "organization_id": org_id,
            "token_type": "pat",
            "base_id": base_id,
            "base_name": "CRM Principale",
            "scopes": ["data.records:read", "data.records:write"],
            "is_active": True,
            "created_at": "2026-09-06T12:00:00Z",
            "updated_at": "2026-09-06T12:00:00Z",
        }
    )

    saved = await repo.save_connection(
        organization_id=org_id,
        base_id=base_id,
        token=raw_token,
        base_name="CRM Principale",
    )
    assert saved["base_id"] == base_id
    assert "token" not in saved  # Invariante 10: Nessun token in chiaro nella tupla restituita

    # 3. Simula recupero connessione con decifratura
    mock_conn.fetchrow = AsyncMock(
        return_value={
            "id": uuid.uuid4(),
            "organization_id": org_id,
            "token_type": "pat",
            "credentials_encrypted": encrypted,
            "base_id": base_id,
            "base_name": "CRM Principale",
            "scopes": ["data.records:read"],
            "is_active": True,
            "created_at": "2026-09-06T12:00:00Z",
            "updated_at": "2026-09-06T12:00:00Z",
        }
    )

    loaded = await repo.get_connection(org_id, base_id)
    assert loaded is not None
    assert loaded["token"] == raw_token
    assert "credentials_encrypted" not in loaded


@pytest.mark.asyncio
async def test_airtable_connection_repo_list_and_disconnect():
    """Verifica list_connections (sanificata) e disconnect (eliminazione con org scoping)."""
    mock_conn = MagicMock()
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    repo = AirtableConnectionRepository(pool=mock_pool)
    org_id = uuid.uuid4()

    mock_conn.fetch = AsyncMock(
        return_value=[
            {
                "id": uuid.uuid4(),
                "organization_id": org_id,
                "token_type": "pat",
                "base_id": "app1",
                "base_name": "Base 1",
                "scopes": ["data.records:read"],
                "is_active": True,
                "created_at": "2026-09-06T10:00:00Z",
                "updated_at": "2026-09-06T10:00:00Z",
            }
        ]
    )

    conns = await repo.list_connections(org_id)
    assert len(conns) == 1
    assert "token" not in conns[0]
    assert conns[0]["base_id"] == "app1"

    mock_conn.execute = AsyncMock(return_value="DELETE 1")
    deleted = await repo.disconnect(org_id, "app1")
    assert deleted is True


# ── 2. TEST SERVICE & AUTH VALIDATION ───────────────────────────────────────


@pytest.mark.asyncio
async def test_service_connect_valid_token(monkeypatch):
    """Connessione con PAT valido: verifica live contro Metadata API e salvataggio."""
    mock_repo = MagicMock()
    mock_repo.save_connection = AsyncMock(
        return_value={
            "id": uuid.uuid4(),
            "base_name": "CRM Leads",
            "is_active": True,
            "updated_at": "2026-09-06T12:00:00Z",
        }
    )

    # Simula risposta positiva della Metadata API di Airtable
    async def mock_get_base_schema(self, base_id):
        from src.integrations.airtable.models import AirtableTable
        return [AirtableTable(id="tbl1", name="Leads")]

    monkeypatch.setattr(AirtableAdapter, "get_base_schema", mock_get_base_schema)

    service = AirtableConnectionService(repo=mock_repo)
    org_id = uuid.uuid4()

    res = await service.connect_pat(
        organization_id=org_id,
        token="pat_valid_12345",
        base_id="appValidCRM",
        base_name="CRM Leads",
    )

    assert res["success"] is True
    assert res["base_id"] == "appValidCRM"
    assert res["token_type"] == "pat"
    assert "token" not in res  # Zero secrets leak
    assert res["tables_count"] == 1
    mock_repo.save_connection.assert_called_once()


@pytest.mark.asyncio
async def test_service_connect_missing_token_or_base():
    """Rifiuto immediato a monte di token o Base ID vuoti."""
    mock_repo = MagicMock()
    service = AirtableConnectionService(repo=mock_repo)
    org_id = uuid.uuid4()

    with pytest.raises(AirtableAuthError, match="non può essere vuoto"):
        await service.connect_pat(org_id, token="", base_id="app123")

    with pytest.raises(Exception, match="Base ID di Airtable non può essere vuoto"):
        await service.connect_pat(org_id, token="pat_xyz", base_id="   ")


@pytest.mark.asyncio
async def test_service_connect_invalid_or_unauthorized_token(monkeypatch):
    """Rifiuto se Airtable risponde 401/403 (token scaduto o privo di scope)."""
    mock_repo = MagicMock()
    mock_repo.save_connection = AsyncMock()

    async def mock_get_base_schema(self, base_id):
        raise AirtableAuthError("Token non valido o scaduto", status_code=401)

    monkeypatch.setattr(AirtableAdapter, "get_base_schema", mock_get_base_schema)

    service = AirtableConnectionService(repo=mock_repo)
    org_id = uuid.uuid4()

    with pytest.raises(AirtableAuthError, match="Token non valido o scaduto"):
        await service.connect_pat(org_id, token="pat_invalid", base_id="app123")

    mock_repo.save_connection.assert_not_called()


@pytest.mark.asyncio
async def test_service_connect_base_not_found(monkeypatch):
    """Rifiuto se Airtable risponde 404 (Base ID inesistente o inaccessibile)."""
    mock_repo = MagicMock()
    mock_repo.save_connection = AsyncMock()

    async def mock_get_base_schema(self, base_id):
        raise AirtableNotFoundError("Base ID non trovata", status_code=404)

    monkeypatch.setattr(AirtableAdapter, "get_base_schema", mock_get_base_schema)

    service = AirtableConnectionService(repo=mock_repo)
    org_id = uuid.uuid4()

    with pytest.raises(AirtableNotFoundError, match="Base ID non trovata"):
        await service.connect_pat(org_id, token="pat_valid", base_id="appMissing")

    mock_repo.save_connection.assert_not_called()


@pytest.mark.asyncio
async def test_service_validate_schema_gate(monkeypatch):
    """Verifica del gate bloccante di validazione schema per il tenant."""
    mock_repo = MagicMock()
    mock_repo.get_connection = AsyncMock(
        return_value={
            "token": "pat_valid_123",
            "is_active": True,
            "base_id": "appCRM",
        }
    )

    from src.integrations.airtable.models import SchemaValidationResult

    async def mock_validate_table_schema(self, base_id, table_id_or_name, required_fields):
        if "Inesistente" in required_fields:
            return SchemaValidationResult(
                is_valid=False,
                missing_fields=["Inesistente"],
                available_fields=["Nome", "Telefono"],
            )
        return SchemaValidationResult(is_valid=True, missing_fields=[], available_fields=["Nome", "Telefono"])

    monkeypatch.setattr(AirtableAdapter, "validate_table_schema", mock_validate_table_schema)

    service = AirtableConnectionService(repo=mock_repo)
    org_id = uuid.uuid4()

    # 1. Validazione con campi corretti -> pass
    res_ok = await service.validate_schema_for_tenant(org_id, "appCRM", "Leads", ["Nome", "Telefono"])
    assert res_ok.is_valid is True

    # 2. Validazione con colonna errata -> fail bloccante
    res_fail = await service.validate_schema_for_tenant(org_id, "appCRM", "Leads", ["Nome", "Inesistente"])
    assert res_fail.is_valid is False
    assert "Inesistente" in res_fail.missing_fields


# ── 2b. TEST MEDICAL POLICY & GDPR ART. 9 (DIVIETO TOTALE) ──────────────────


@pytest.mark.asyncio
async def test_connect_prohibited_for_medical_verticale():
    """Divieto assoluto di connessione Airtable per settore medico/sanitario (Invariante 6)."""
    mock_repo = MagicMock()
    mock_repo.save_connection = AsyncMock()
    service = AirtableConnectionService(repo=mock_repo)
    org_id = uuid.uuid4()

    with pytest.raises(AirtableMedicalPolicyError, match=r"non consentita per il settore medico/sanitario \('studio_medico'\)"):
        await service.connect_pat(
            organization_id=org_id,
            token="pat_valid_123",
            base_id="appMedical123",
            verticale="studio_medico",
        )

    mock_repo.save_connection.assert_not_called()


@pytest.mark.asyncio
async def test_connect_prohibited_for_medical_verticale_from_repo():
    """Divieto se il repository core indica che l'organizzazione appartiene a un settore medico."""
    mock_repo = MagicMock()
    mock_repo.save_connection = AsyncMock()
    mock_core_repo = MagicMock()
    mock_core_repo.get_onboarding_profile = AsyncMock(
        return_value={"verticale": "studio_medico_dentista"}
    )

    service = AirtableConnectionService(repo=mock_repo, core_repo=mock_core_repo)
    org_id = uuid.uuid4()

    with pytest.raises(AirtableMedicalPolicyError, match=r"non consentita per il settore medico/sanitario \('studio_medico_dentista'\)"):
        await service.connect_pat(
            organization_id=org_id,
            token="pat_valid_123",
            base_id="appMedical123",
        )

    mock_repo.save_connection.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("verticale_sanitario", [
    "clinica",
    "dentista",
    "odontoiatra",
    "fisioterapia",
    "psicologo",
    "psicoterapeuta",
    "veterinario",
    "poliambulatorio",
])
async def test_connect_prohibited_for_all_clinical_verticals(verticale_sanitario):
    """Verifica che l'interdizione totale copra tutti i verticali clinici e parasanitari."""
    mock_repo = MagicMock()
    mock_repo.save_connection = AsyncMock()
    service = AirtableConnectionService(repo=mock_repo)
    org_id = uuid.uuid4()

    with pytest.raises(AirtableMedicalPolicyError):
        await service.connect_pat(
            organization_id=org_id,
            token="pat_valid_123",
            base_id="appMedical123",
            verticale=verticale_sanitario,
        )

    mock_repo.save_connection.assert_not_called()


@pytest.mark.asyncio
async def test_connect_allowed_for_non_medical_verticale(monkeypatch):
    """Per verticali non medici (es. ristorante, hotel), la connessione è pienamente consentita."""
    mock_repo = MagicMock()
    mock_repo.save_connection = AsyncMock(
        return_value={"id": str(uuid.uuid4()), "base_name": "Ristorante CRM", "is_active": True, "updated_at": "2026-09-07T10:00:00"}
    )

    async def mock_get_base_schema(self, base_id):
        from src.integrations.airtable.models import AirtableTable
        return [AirtableTable(id="tbl1", name="Prenotazioni")]

    monkeypatch.setattr(AirtableAdapter, "get_base_schema", mock_get_base_schema)

    service = AirtableConnectionService(repo=mock_repo)
    org_id = uuid.uuid4()

    res = await service.connect_pat(
        organization_id=org_id,
        token="pat_valid_123",
        base_id="appRisto123",
        verticale="ristorante",
    )

    assert res["success"] is True
    assert res["verticale"] == "ristorante"
    mock_repo.save_connection.assert_called_once()
    assert mock_repo.save_connection.call_args.kwargs["metadata"]["medical_prohibition_check"] == "passed"


# ── 3. TEST FASTAPI REST ENDPOINTS ──────────────────────────────────────────


def test_api_routes_airtable_connect_and_status(monkeypatch):
    """Verifica degli endpoint FastAPI /api/v1/integrations/airtable/* con TestClient."""
    from src.core.auth.dependencies import get_organization_context
    from src.api.routes.airtable import router

    app = FastAPI()
    app.include_router(router)

    test_org_id = str(uuid.uuid4())
    mock_service = MagicMock()
    app.state.airtable_service = mock_service

    # Override del contesto organizzativo (risolve require_ruolo per tutti i ruoli ammessi)
    app.dependency_overrides[get_organization_context] = lambda: {
        "organization_id": test_org_id,
        "ruolo": "owner",
        "user_id": str(uuid.uuid4()),
        "source": "jwt",
    }

    client = TestClient(app)

    # 1. POST /connect con esito positivo
    mock_service.connect_pat = AsyncMock(
        return_value={
            "success": True,
            "message": "Connessione ad Airtable verificata con successo.",
            "base_id": "appCRM123",
            "base_name": "Vendite",
            "token_type": "pat",
            "is_active": True,
        }
    )

    resp = client.post(
        "/api/v1/integrations/airtable/connect",
        json={"token": "pat_valid_token", "base_id": "appCRM123", "base_name": "Vendite"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["base_id"] == "appCRM123"
    assert "token" not in body

    # 2. POST /connect con errore di autenticazione 401
    mock_service.connect_pat = AsyncMock(side_effect=AirtableAuthError("Token non valido", status_code=401))
    resp_err = client.post(
        "/api/v1/integrations/airtable/connect",
        json={"token": "pat_bad", "base_id": "appCRM123"},
    )
    assert resp_err.status_code == 401
    assert "Token non valido" in resp_err.json()["detail"]

    # 2b. POST /connect con rifiuto Policy Medica 403 (studio medico - divieto totale)
    mock_service.connect_pat = AsyncMock(
        side_effect=AirtableMedicalPolicyError("Connessione non consentita per il settore 'studio_medico'")
    )
    resp_med = client.post(
        "/api/v1/integrations/airtable/connect",
        json={"token": "pat_valid", "base_id": "appCRM123"},
    )
    assert resp_med.status_code == 403
    assert "studio_medico" in resp_med.json()["detail"]

    # 3. GET /status
    mock_service.get_status = AsyncMock(
        return_value={
            "is_configured": True,
            "active_connections_count": 1,
            "connections": [{"base_id": "appCRM123", "base_name": "Vendite", "is_active": True}],
        }
    )
    resp_status = client.get("/api/v1/integrations/airtable/status")
    assert resp_status.status_code == 200
    assert resp_status.json()["is_configured"] is True

    # 4. DELETE disconnessione
    mock_service.disconnect = AsyncMock(return_value={"success": True, "base_id": "appCRM123"})
    resp_del = client.delete("/api/v1/integrations/airtable?base_id=appCRM123")
    assert resp_del.status_code == 200
    assert resp_del.json()["success"] is True
