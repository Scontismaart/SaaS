import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from src.api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_health_live_probe_ok_when_running(client):
    # Setup worker tasks as running
    mock_inbound = MagicMock()
    mock_inbound.done.return_value = False
    mock_retry = MagicMock()
    mock_retry.done.return_value = False

    app.state.inbound_task = mock_inbound
    app.state.retry_task = mock_retry

    resp = client.get("/api/health/live")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["workers"]["inbound_task"] == "running"
    assert data["workers"]["retry_task"] == "running"


def test_health_live_probe_unhealthy_on_worker_crash(client):
    # Simulate a crashed worker task
    mock_inbound = MagicMock()
    mock_inbound.done.return_value = True
    mock_inbound.cancelled.return_value = False
    mock_inbound.exception.return_value = RuntimeError("Fatal loop crash")

    mock_retry = MagicMock()
    mock_retry.done.return_value = False

    app.state.inbound_task = mock_inbound
    app.state.retry_task = mock_retry

    resp = client.get("/api/health/live")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "unhealthy"
    assert data["workers"]["inbound_task"] == "stopped: worker failure"
    assert "Fatal loop crash" not in resp.text


def test_health_ready_probe_ok(client, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test_key_ok")
    monkeypatch.setenv("GROQ_FREE_ACCOUNT_CONFIRMED", "true")
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_conn.fetchval = AsyncMock(return_value=1)
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    app.state.pool = mock_pool

    resp_ready = client.get("/api/health/ready")
    assert resp_ready.status_code == 200
    assert resp_ready.json()["status"] == "ok"

    resp_alias = client.get("/api/health")
    assert resp_alias.status_code == 200
    assert resp_alias.json()["status"] == "ok"


def test_health_ready_probe_db_down(client, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test_key_ok")
    monkeypatch.setenv("GROQ_FREE_ACCOUNT_CONFIRMED", "true")
    mock_pool = MagicMock()
    mock_pool.acquire.side_effect = ConnectionRefusedError("DB connection refused")

    app.state.pool = mock_pool

    resp = client.get("/api/health/ready")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "degraded"
    assert data["checks"]["database"] == "errore di connessione"
    assert "DB connection refused" not in resp.text


def test_health_ready_remains_ok_without_ai_provider(client, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_conn.fetchval = AsyncMock(return_value=1)
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    app.state.pool = mock_pool

    ready = client.get("/api/health/ready")
    assert ready.status_code == 200
    assert ready.json()["checks"]["ai_provider"] == "non_configurato"
    ai = client.get("/api/health/ai")
    assert ai.status_code == 503
    assert ai.json()["remote_status"] == "non_verificato"
    assert "dummy-offline-key" not in ai.text


def test_health_ready_requires_database_pool(client):
    app.state.pool = None
    ready = client.get("/api/health/ready")
    assert ready.status_code == 503
    assert ready.json()["checks"]["database"].startswith("non configurato")


def test_malformed_ai_endpoint_does_not_break_core_health(client, monkeypatch):
    monkeypatch.setenv("LLM_COST_POLICY", "standard")
    monkeypatch.setenv("AI_PROVIDER", "openai_compatible")
    monkeypatch.setenv("AI_MODEL", "custom-free-model")
    monkeypatch.setenv("AI_API_KEY", "dummy-offline-key")
    monkeypatch.setenv("AI_BASE_URL", "http://[bad-ipv6")
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_conn.fetchval = AsyncMock(return_value=1)
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    app.state.pool = mock_pool
    assert client.get("/api/health/ready").status_code == 200
    ai = client.get("/api/health/ai")
    assert ai.status_code == 503
    assert ai.json()["status"] == "non_configurato"
