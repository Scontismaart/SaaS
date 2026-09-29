from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.api.routes.common import enforce_org_rate_limit


@pytest.mark.asyncio
async def test_org_rate_limit_uses_verified_tenant_key(monkeypatch):
    limiter = AsyncMock()
    limiter.hit.return_value = False
    monkeypatch.setattr(
        "src.core.rate_limit.get_rate_limiter",
        AsyncMock(return_value=limiter),
    )

    await enforce_org_rate_limit("org-a", "knowledge-index", 20, 600)
    limiter.hit.assert_awaited_once_with("org:org-a:knowledge-index", 20, 600)


@pytest.mark.asyncio
async def test_org_rate_limit_denies_missing_scope_and_excess(monkeypatch):
    limiter = AsyncMock()
    limiter.hit.return_value = True
    monkeypatch.setattr(
        "src.core.rate_limit.get_rate_limiter",
        AsyncMock(return_value=limiter),
    )

    with pytest.raises(HTTPException) as missing:
        await enforce_org_rate_limit(None, "knowledge-index", 20, 600)
    assert missing.value.status_code == 403
    limiter.hit.assert_not_awaited()

    with pytest.raises(HTTPException) as excess:
        await enforce_org_rate_limit("org-a", "knowledge-index", 20, 600)
    assert excess.value.status_code == 429


@pytest.mark.asyncio
async def test_production_rejects_process_local_rate_limiting(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "memory")
    from src.core.rate_limit import get_rate_limiter

    with pytest.raises(RuntimeError, match="required in production"):
        await get_rate_limiter()


@pytest.mark.asyncio
async def test_rate_limiter_rejects_unknown_backend(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "memroy")
    from src.core.rate_limit import get_rate_limiter

    with pytest.raises(RuntimeError, match="must be 'redis' or 'memory'"):
        await get_rate_limiter()
