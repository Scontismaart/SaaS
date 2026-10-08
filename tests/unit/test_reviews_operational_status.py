"""OAuth success must not certify genuine Business Profile resource access."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.parametrize("account,location,synced,expected", [
    (None, None, None, False),
    ("accounts/123", "accounts/123/locations/456", None, False),
    ("accounts/123", "accounts/123/locations/456", datetime.now(timezone.utc), True),
])
async def test_oauth_without_completed_resource_sync_is_not_operational(monkeypatch, account, location, synced, expected):
    from src.core.reviews import google_routes as routes

    monkeypatch.setenv("GOOGLE_BUSINESS_ENABLED", "true")
    monkeypatch.setattr(routes, "check_feature_blocked_by_plan", AsyncMock(return_value=None))
    connection = MagicMock()
    connection.fetchrow = AsyncMock(return_value={"account_name": account, "location_name": location, "last_sync_at": synced})
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=connection)
    context.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.acquire.return_value = context
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=pool, repo=MagicMock())))
    result = await routes.google_reviews_status(request, user={"organization_id": "11111111-1111-1111-1111-111111111111"})
    assert result["connected"] is True
    assert result["operational"] is expected
