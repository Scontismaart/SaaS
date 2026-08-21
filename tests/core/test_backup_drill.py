import subprocess
import pytest
import asyncpg
from src.core.backup.drill import run_backup_restore_drill

pytestmark = pytest.mark.asyncio

async def test_backup_restore_drill_detects_empty_restore(tmp_path, postgres_container, pg_pool, sample_org, monkeypatch):
    import asyncio
    
    dsn = postgres_container.get_connection_url().replace("+psycopg2", "")

    # We mock _run to simulate pg_restore failing or doing a partial restore
    # Specifically, we'll make it TRUNCATE the organizations table to simulate a corrupted restore
    def fake_run(cmd, check=True, env=None):
        if cmd[0] == "pg_restore":
            async def truncate():
                conn = await asyncpg.connect(dsn)
                await conn.execute("TRUNCATE TABLE organizations CASCADE")
                await conn.close()
            # use a new event loop to run async inside synchronous mock
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(truncate())
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("src.core.backup.drill._run", fake_run)
    
    with pytest.raises(RuntimeError, match="Integrità compromessa"):
        await run_backup_restore_drill(
            database_url=dsn,
            verify_database_url=dsn,
            backup_dir=str(tmp_path),
        )

async def test_backup_restore_drill_runs_dump_restore_verify(tmp_path, postgres_container, pg_pool, sample_org, monkeypatch):
    dsn = postgres_container.get_connection_url().replace("+psycopg2", "")
        
    calls = []

    def fake_run(cmd, check=True, env=None):
        calls.append(cmd)
        if cmd[0] == "pg_dump":
            backup_file = cmd[cmd.index("--file") + 1]
            with open(backup_file, "wb") as f:
                f.write(b"dump")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("src.core.backup.drill._run", fake_run)
    result = await run_backup_restore_drill(
        database_url=dsn,
        verify_database_url=dsn,
        backup_dir=str(tmp_path),
    )

    assert result.ok is True
    assert calls[0][0] == "pg_dump"
    assert calls[1][0] == "pg_restore"

async def test_backup_restore_drill_alerts_sentry_on_failure(tmp_path, monkeypatch):
    captured = []

    def fail_run(cmd, check=True, env=None):
        raise RuntimeError("pg_dump failed")

    monkeypatch.setattr("src.core.backup.drill._run", fail_run)
    monkeypatch.setattr("src.core.backup.drill.sentry_sdk.capture_exception", captured.append)

    with pytest.raises(RuntimeError):
        await run_backup_restore_drill(
            database_url="postgresql://fake",
            verify_database_url="postgresql://fake",
            backup_dir=str(tmp_path),
        )

    assert captured
