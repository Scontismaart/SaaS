"""Test pool effimeri dello scheduler.

Contratto (post-incidente: le connessioni asyncpg sono legate all'event
loop che le crea; condividerle tra uvicorn e asyncio.run() dei job
corrompeva il protocollo e appiccicava le richieste web senza errori):
- ogni _run_* crea un PROPRIO pool dentro asyncio.run() (min 1, max 2,
  command_timeout=30) e lo chiude sempre, anche su errore;
- nessun job riceve piu' un pool globale condiviso (imposta_pool rimossa).
"""

import pytest

from src.core import scheduler

pytestmark = pytest.mark.asyncio


class FakePool:
    def __init__(self, registry):
        self.closed = False
        self.queries = []
        registry.append(self)

    async def fetch(self, *a, **k):
        self.queries.append(a[0] if a else "")
        return []

    async def execute(self, *a, **k):
        self.queries.append(a[0] if a else "")
        return "OK"

    async def acquire(self):
        raise NotImplementedError

    async def close(self):
        self.closed = True


@pytest.fixture
def track_create_pool(monkeypatch):
    created = []

    async def fake_create_pool(**kwargs):
        pool = FakePool(created)
        pool.kwargs = kwargs
        return pool

    monkeypatch.setenv("DATABASE_URL", "postgresql://fake:5432/db")
    monkeypatch.setattr(scheduler.asyncpg, "create_pool", fake_create_pool)
    return created


async def test_con_pool_esimero_crea_chiude_parametri_ok(track_create_pool):
    viste = []

    async def job(pool):
        viste.append(pool)
        await pool.fetch("SELECT 1")

    await scheduler._con_pool_esimero(job)

    assert len(track_create_pool) == 1
    assert viste == [track_create_pool[0]]
    kwargs = track_create_pool[0].kwargs
    assert kwargs["min_size"] == 1
    assert kwargs["max_size"] == 2
    assert kwargs["command_timeout"] == 30
    assert track_create_pool[0].closed is True


async def test_pool_chiuso_anche_su_errore_job(track_create_pool):
    async def job_che_esplode(pool):
        await pool.fetch("SELECT boom")
        raise RuntimeError("job fallito")

    with pytest.raises(RuntimeError):
        await scheduler._con_pool_esimero(job_che_esplode)

    assert len(track_create_pool) == 1
    assert track_create_pool[0].closed is True


def test_run_reminder_check_end_to_end(monkeypatch, track_create_pool):
    """Il wrapper reale (thread APScheduler) crea e chiude il suo pool."""
    scheduler._run_reminder_check()
    assert len(track_create_pool) == 1
    assert track_create_pool[0].closed is True
    # La prima query del job elenca le organizzazioni
    assert "FROM organizations" in track_create_pool[0].queries[0]


def test_imposta_pool_rimossa():
    """La via d'accesso al pool condiviso non deve più esistere."""
    assert not hasattr(scheduler, "imposta_pool")
