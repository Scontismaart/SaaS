"""Live inference is opt-in, never triggered by incidental local API keys."""
import os
from pathlib import Path

import pytest


# Local, ignored browser-QA helpers are executable scripts: importing them
# launches Playwright immediately.  Keep them available for manual visual
# checks without allowing pytest's filename discovery to execute them during
# the deterministic unit/integration suite.
_LOCAL_BROWSER_QA_SCRIPTS = frozenset({
    "browser_qa_runner.py",
    "browser_qa_runner_full.py",
    "capture_dashboard_views.py",
    "capture_full.py",
    "check_sections.py",
    "crop.py",
    "production_smoke_test.py",
    "test_inbox_responsive.py",
    "test_panoramica_responsive.py",
    "test_prenotazioni_responsive.py",
    "test_recensioni_responsive.py",
    "test_team_responsive.py",
    "verify_recovered_landing.py",
    "verify_regression_fix.py",
})


def pytest_ignore_collect(collection_path: Path, config):
    """Exclude executable local browser helpers from normal suite discovery."""
    if collection_path.parent == Path(__file__).parent:
        return collection_path.name in _LOCAL_BROWSER_QA_SCRIPTS
    return None


@pytest.fixture
def install_test_identity():
    """Install a test-only JWT identity without reviving service-key user auth.

    Older route tests use a short opaque credential for convenience.  The
    override maps that credential to the same trusted identity shape produced
    by a verified Supabase JWT, while keeping production dependencies intact.
    """
    def install(
        app,
        api_key: str,
        *,
        default_org_id=None,
        ruolo="owner",
        user_id="00000000-0000-0000-0000-000000000001",
    ):
        from fastapi import Depends, Header, HTTPException
        from src.core.auth.dependencies import get_current_user, get_organization_context, get_token

        async def identity(
            token=Depends(get_token),
            x_organization_id: str | None = Header(None),
        ):
            if token is None:
                raise HTTPException(401, "Test session required")
            accepted = {api_key, f"apikey:{api_key}", f"{api_key}-aal1"}
            if token not in accepted:
                raise HTTPException(403, "Invalid test session")
            org_id = x_organization_id or default_org_id
            return {
                "source": "jwt",
                "aal": "aal1" if token.endswith("-aal1") else "aal2",
                "organization_id": str(org_id) if org_id else None,
                "ruolo": ruolo,
                "auth_user_id": user_id,
                "user_id": user_id,
            }

        app.dependency_overrides[get_current_user] = identity
        app.dependency_overrides[get_organization_context] = identity

    return install


def pytest_addoption(parser):
    parser.addoption("--live-llm", action="store_true", default=False,
                     help="Allow explicitly confirmed Groq FREE account inference")


def pytest_configure(config):
    config.addinivalue_line("markers", "live_llm: real inference, disabled unless --live-llm")
    if config.getoption("--live-llm"):
        if (os.getenv("LLM_COST_POLICY", "free_only") != "free_only"
                or os.getenv("GROQ_FREE_ACCOUNT_CONFIRMED") != "true"
                or not os.getenv("GROQ_API_KEY")):
            raise pytest.UsageError("Live tests require free_only and a confirmed Groq FREE account")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--live-llm"):
        for item in items:
            if item.get_closest_marker("live_llm"):
                item.add_marker(pytest.mark.skip(reason="Live LLM disabled: requires explicit --live-llm"))
