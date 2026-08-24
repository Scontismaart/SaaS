"""Bloccante B3: i token di export GDPR vivono in Redis con TTL 15 min."""
import pytest
from src.core.gdpr import token_store


class FakeRedis:
    def __init__(self):
        self.d = {}

    async def set(self, key, value, ex=None):
        self.d[key] = value

    async def getdel(self, key):
        return self.d.pop(key, None)


@pytest.fixture(autouse=True)
def _reset_store(monkeypatch):
    monkeypatch.setattr(token_store, "_memory", {})
    monkeypatch.setattr(token_store, "_redis", None)


def _use(fake, monkeypatch):
    async def _get():
        return fake
    monkeypatch.setattr(token_store, "_get_redis", _get)


@pytest.mark.asyncio
async def test_token_consumo_one_time(monkeypatch):
    fake = FakeRedis()
    _use(fake, monkeypatch)
    await token_store.save_token("t1", "org-1", {"dati": [1]})
    meta = await token_store.pop_token("t1")
    assert meta["org_id"] == "org-1"
    assert await token_store.pop_token("t1") is None  # one-time


@pytest.mark.asyncio
async def test_token_sconosciuto(monkeypatch):
    _use(FakeRedis(), monkeypatch)
    assert await token_store.pop_token("nope") is None


@pytest.mark.asyncio
async def test_fallback_memory_senza_redis(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "")
    await token_store.save_token("t2", "org-2", {})
    assert (await token_store.pop_token("t2"))["org_id"] == "org-2"


@pytest.mark.asyncio
async def test_token_scaduto(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "")
    await token_store.save_token("t3", "org-3", {})
    token_store._memory["t3"]["expires"] = 0  # forzato scaduto
    assert await token_store.pop_token("t3") is None
