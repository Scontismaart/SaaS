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
