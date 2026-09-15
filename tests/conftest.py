"""Live inference is opt-in, never triggered by incidental local API keys."""
import os

import pytest


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
