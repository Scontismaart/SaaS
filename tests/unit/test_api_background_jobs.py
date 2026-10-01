from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI

from src.api import main


def test_background_jobs_default_to_enabled_outside_staging(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("MELPIS_BACKGROUND_JOBS_ENABLED", raising=False)

    assert main._background_jobs_enabled_from_env() is True


def test_staging_requires_explicit_background_job_setting(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.delenv("MELPIS_BACKGROUND_JOBS_ENABLED", raising=False)

    with pytest.raises(RuntimeError, match="must be explicit in staging"):
        main._background_jobs_enabled_from_env()


def test_staging_can_disable_background_jobs(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("MELPIS_BACKGROUND_JOBS_ENABLED", "false")

    assert main._background_jobs_enabled_from_env() is False


@pytest.mark.parametrize("app_env", ["development", "production"])
def test_background_jobs_cannot_be_disabled_outside_staging(monkeypatch, app_env):
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("MELPIS_BACKGROUND_JOBS_ENABLED", "false")

    with pytest.raises(RuntimeError, match="only be disabled when APP_ENV=staging"):
        main._background_jobs_enabled_from_env()


def test_background_jobs_setting_rejects_ambiguous_values(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("MELPIS_BACKGROUND_JOBS_ENABLED", "0")

    with pytest.raises(RuntimeError, match="must be 'true' or 'false'"):
        main._background_jobs_enabled_from_env()


@pytest.mark.asyncio
async def test_staging_lifespan_with_jobs_disabled_starts_no_background_services(
    monkeypatch,
):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("MELPIS_BACKGROUND_JOBS_ENABLED", "false")
    monkeypatch.setenv("DATABASE_URL", "postgresql://qa:qa@127.0.0.1:5432/qa")
    monkeypatch.delenv("META_APP_SECRET", raising=False)
    monkeypatch.delenv("META_VERIFY_TOKEN", raising=False)

    pool = SimpleNamespace(close=AsyncMock())
    repo = SimpleNamespace(
        org_repo=object(),
        doc_repo=object(),
        billing_repo=object(),
        conv_repo=object(),
    )
    whatsapp_service = SimpleNamespace(fast_path_match=lambda *_args, **_kwargs: None)

    monkeypatch.setattr("asyncpg.create_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr(main, "CoreRepository", Mock(return_value=repo))
    monkeypatch.setattr(main, "WhatsAppRepository", Mock(return_value=object()))
    monkeypatch.setattr(main, "GoogleCalendarService", Mock(return_value=object()))
    monkeypatch.setattr(main, "start_worker", Mock())
    monkeypatch.setattr(main, "stop_email_worker", Mock())
    monkeypatch.setattr(main, "avvia_scheduler", Mock())
    monkeypatch.setattr(main, "ferma_scheduler", Mock())
    monkeypatch.setattr(main, "reset_memory_rate_limiter", Mock())
    monkeypatch.setattr("src.core.startup_guard.assert_production_safe", Mock())
    monkeypatch.setattr("src.core.bookings.BookingService", Mock(return_value=object()))
    monkeypatch.setattr("src.whatsapp.service.WhatsAppService", Mock(return_value=whatsapp_service))
    monkeypatch.setattr(
        "src.core.db.repositories.booking_repo.BookingRepository",
        Mock(return_value=object()),
    )
    monkeypatch.setattr(
        "src.core.db.repositories.organization_repo.OrganizationRepository",
        Mock(return_value=object()),
    )
    monkeypatch.setattr(
        "src.integrations.airtable.wiring.build_airtable_tool_factory",
        Mock(return_value=None),
    )
    monkeypatch.setattr(
        "src.core.receptionist.conversation_orchestrator.ConversationOrchestrator",
        Mock(return_value=object()),
    )
    monkeypatch.setattr(
        "src.whatsapp.inbound_processor.InboundProcessor", Mock(return_value=object())
    )
    monkeypatch.setattr("src.whatsapp.retry_worker.RetryWorker", Mock(return_value=object()))

    app = FastAPI()
    async with main.lifespan(app):
        assert app.state.pool is pool
        assert app.state.background_jobs_enabled is False
        assert app.state.inbound_task is None
        assert app.state.retry_task is None
        assert app.state.governance_task is None

    main.start_worker.assert_not_called()
    main.avvia_scheduler.assert_not_called()
    main.ferma_scheduler.assert_not_called()
    main.stop_email_worker.assert_not_called()
    pool.close.assert_awaited_once()


def test_liveness_identifies_intentionally_disabled_jobs(monkeypatch):
    from fastapi.testclient import TestClient

    app = main.app
    monkeypatch.setattr(app.state, "background_jobs_enabled", False, raising=False)
    for task_name in ("inbound_task", "retry_task", "governance_task"):
        monkeypatch.setattr(app.state, task_name, None, raising=False)

    response = TestClient(app).get("/api/health/live")

    assert response.status_code == 200
    assert response.json()["background_jobs"] == "disabled"
    assert set(response.json()["workers"].values()) == {"disabled"}
