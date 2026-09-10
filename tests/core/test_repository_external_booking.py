"""Test per ExternalBookingRepository (Task 2).

Verifica la cifratura Fernet di envelope JSON a riposo (flessibile per SimplyBook, ZaK, OAuth),
il ciclo CRUD delle credenziali per-organizzazione, il tracciamento Send-Then-Mark e il tenant scoping.
"""
import os
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock
from cryptography.fernet import Fernet

from src.core.db.scoping import TENANT_SCOPED_TABLES


@pytest.fixture(autouse=True)
def setup_encryption_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("ENCRYPTION_KEY", key)
    return key


def test_tenant_scoped_tables_contains_new_tables():
    """Verifica che le nuove tabelle siano registrate in TENANT_SCOPED_TABLES."""
    assert "external_booking_credentials" in TENANT_SCOPED_TABLES
    assert "external_booking_sync" in TENANT_SCOPED_TABLES


@pytest.mark.asyncio
async def test_external_booking_repo_crypto_roundtrip():
    """Verifica che l'envelope di credenziali (dict) venga cifrato a riposo e decifrato in lettura."""
    from src.core.db.repositories.external_booking_repo import ExternalBookingRepository

    org_id = uuid.uuid4()
    simplybook_creds = {
        "company_login": "org_test",
        "api_key": "sb_secret_key_12345",
        "api_secret": "sb_secret_token_67890",
    }

    mock_conn = MagicMock()
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    repo = ExternalBookingRepository(pool=mock_pool)

    # Verifica cifratura e decifratura dell'envelope
    encrypted_envelope = repo.encrypt_credentials(simplybook_creds)
    assert isinstance(encrypted_envelope, str)
    decrypted = repo.decrypt_credentials(encrypted_envelope)
    assert decrypted == simplybook_creds

    # Simula save_credentials
    mock_conn.fetchrow = AsyncMock(
        return_value={
            "organization_id": org_id,
            "provider": "simplybook",
            "credentials_encrypted": encrypted_envelope,
            "config": '{"mode": "authoritative", "medical_dpa_signed": false}',
            "is_active": True,
        }
    )

    saved = await repo.save_credentials(
        organization_id=org_id,
        provider="simplybook",
        credentials=simplybook_creds,
        config={"mode": "authoritative", "medical_dpa_signed": False},
    )

    assert saved["provider"] == "simplybook"
    assert saved["credentials"]["api_key"] == "sb_secret_key_12345"
    assert saved["api_key"] == "sb_secret_key_12345"
    assert saved["company_login"] == "org_test"
    assert saved["config"]["mode"] == "authoritative"
    assert saved["config"]["medical_dpa_signed"] is False

    # Simula get_credentials
    fetched = await repo.get_credentials(org_id)
    assert fetched is not None
    assert fetched["credentials"] == simplybook_creds
    assert fetched["api_key"] == "sb_secret_key_12345"


@pytest.mark.asyncio
async def test_external_booking_repo_supports_zak_and_oauth_envelopes():
    """Verifica che lo schema supporti credenziali ZaK (singola API key) e OAuth senza modifiche allo schema."""
    from src.core.db.repositories.external_booking_repo import ExternalBookingRepository

    repo = ExternalBookingRepository(pool=MagicMock())

    # Formato ZaK: singola chiave API
    zak_creds = {"api_key": "zak_auth_token_xyz"}
    enc_zak = repo.encrypt_credentials(zak_creds)
    assert repo.decrypt_credentials(enc_zak) == zak_creds

    # Formato OAuth: token, refresh, expiry
    oauth_creds = {
        "access_token": "acc_123",
        "refresh_token": "ref_456",
        "expires_in": 3600,
        "token_type": "bearer",
    }
    enc_oauth = repo.encrypt_credentials(oauth_creds)
    assert repo.decrypt_credentials(enc_oauth) == oauth_creds


@pytest.mark.asyncio
async def test_external_booking_sync_lifecycle():
    """Verifica la registrazione del prepare e la transizione di stato sync."""
    from src.core.db.repositories.external_booking_repo import ExternalBookingRepository

    org_id = uuid.uuid4()
    idempotency_key = f"ext-book:{org_id}:msg-123"

    mock_conn = MagicMock()
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    repo = ExternalBookingRepository(pool=mock_pool)

    # 1. Prepare sync
    mock_conn.fetchrow = AsyncMock(
        return_value={
            "id": uuid.uuid4(),
            "organization_id": org_id,
            "idempotency_key": idempotency_key,
            "provider": "simplybook",
            "sync_status": "pending",
            "retry_count": 0,
        }
    )
    prep = await repo.record_sync_prepare(
        organization_id=org_id,
        idempotency_key=idempotency_key,
        provider="simplybook",
    )
    assert prep["sync_status"] == "pending"

    # 2. Success commit
    mock_conn.fetchrow = AsyncMock(
        return_value={
            "organization_id": org_id,
            "idempotency_key": idempotency_key,
            "external_booking_id": "EXT-999",
            "sync_status": "synced",
        }
    )
    success = await repo.record_sync_success(
        organization_id=org_id,
        idempotency_key=idempotency_key,
        external_booking_id="EXT-999",
    )
    assert success["sync_status"] == "synced"
    assert success["external_booking_id"] == "EXT-999"


def test_tenant_scoping_check_on_external_booking_repo():
    """Verifica che tutte le query di ExternalBookingRepository rispettino il tenant scoping (AST check)."""
    import importlib.util
    from pathlib import Path

    script_path = Path(__file__).resolve().parents[2] / "scripts" / "check_tenant_scoping.py"
    spec = importlib.util.spec_from_file_location("check_tenant_scoping", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    target_file = Path(__file__).resolve().parents[2] / "src" / "core" / "db" / "repositories" / "external_booking_repo.py"
    if target_file.exists():
        violations = module.check_file(target_file)
        assert violations == [], f"Violazioni di tenant scoping trovate: {violations}"
