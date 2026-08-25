"""Bloccante B1: DEMO_MODE e' fail-closed in produzione."""
import pytest

from src.core.auth import dependencies
from src.core.startup_guard import assert_production_safe


def test_demo_mode_ignorato_in_produzione(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEMO_MODE", "true")
    assert dependencies.is_demo_mode() is False


def test_demo_mode_attivo_in_dev(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_MODE", "1")
    assert dependencies.is_demo_mode() is True


def test_startup_bloccato_demo_in_prod(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEMO_MODE", "1")
    with pytest.raises(RuntimeError, match="B1"):
        assert_production_safe()


def test_startup_ok_in_dev(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    assert_production_safe()  # non alza


def test_startup_bloccato_senza_encryption_key(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    with pytest.raises(RuntimeError, match="B4"):
        assert_production_safe()


def test_startup_bloccato_chiave_invalida(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ENCRYPTION_KEY", "non-una-chiave")
    with pytest.raises(RuntimeError, match="B4"):
        assert_production_safe()


def test_startup_ok_con_chiave_valida(monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    assert_production_safe()


def test_startup_bloccato_stripe_live_in_dev(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_MODE", "")
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_abc123")
    with pytest.raises(RuntimeError, match="STRIPE_SECRET_KEY live"):
        assert_production_safe()


def test_startup_ok_stripe_test_in_dev(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_MODE", "")
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_abc123")
    assert_production_safe()  # non alza
