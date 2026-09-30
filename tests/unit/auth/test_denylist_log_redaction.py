import logging

import pytest
from fastapi import HTTPException
from redis.asyncio import Redis

from src.core.auth.denylist import is_token_revoked, revoke_token

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("operation", ("revoke", "check"))
async def test_redis_exception_details_are_not_logged_or_returned(
    monkeypatch, caplog, operation
):
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "redis")

    class BrokenRedis:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def set(self, *_args, **_kwargs):
            raise RuntimeError("redis://user:SYNTHETIC_REDIS_SECRET@host")

        async def exists(self, *_args):
            raise RuntimeError("redis://user:SYNTHETIC_REDIS_SECRET@host")

    monkeypatch.setattr(
        Redis,
        "from_url",
        classmethod(lambda _cls, *_args, **_kwargs: BrokenRedis()),
    )
    caplog.set_level(logging.CRITICAL, logger="src.core.auth.denylist")

    if operation == "revoke":
        with pytest.raises(RuntimeError) as exc:
            await revoke_token("synthetic-session-token")
        assert "SYNTHETIC_REDIS_SECRET" not in str(exc.value)
    else:
        with pytest.raises(HTTPException) as exc:
            await is_token_revoked("synthetic-session-token")
        assert exc.value.status_code == 503

    assert "SYNTHETIC_REDIS_SECRET" not in caplog.text
    assert "error_type=RuntimeError" in caplog.text
