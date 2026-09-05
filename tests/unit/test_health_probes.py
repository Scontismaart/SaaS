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
    assert "Fatal loop crash" in data["workers"]["inbound_task"]


def test_health_ready_probe_ok(client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test_key_ok")
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
    monkeypatch.setenv("OPENROUTER_API_KEY", "test_key_ok")
    mock_pool = MagicMock()
    mock_pool.acquire.side_effect = ConnectionRefusedError("DB connection refused")

    app.state.pool = mock_pool

    resp = client.get("/api/health/ready")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "degraded"
    assert "DB connection refused" in data["checks"]["database"]
