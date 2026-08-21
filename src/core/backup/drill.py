"""Monthly backup/restore drill orchestration."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import sentry_sdk

logger = logging.getLogger(__name__)


@dataclass
class DrillResult:
    ok: bool
    backup_path: str
    started_at: str
    finished_at: str
    detail: str


def _run(cmd: list[str], env: dict[str, str] | None = None) -> None:
    subprocess.run(cmd, check=True, env=env)


import asyncpg

async def run_backup_restore_drill(
    database_url: str | None = None,
    verify_database_url: str | None = None,
    backup_dir: str | None = None,
) -> DrillResult:
    started = datetime.now(timezone.utc)
    database_url = database_url or os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL", "")
    verify_database_url = verify_database_url or os.getenv("VERIFY_DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL/SUPABASE_DB_URL mancante")
    if not verify_database_url:
        raise RuntimeError("VERIFY_DATABASE_URL mancante")

    out_dir = Path(backup_dir or os.getenv("BACKUP_DIR", "backups")).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    backup_path = out_dir / f"supabase-{started.strftime('%Y%m%dT%H%M%SZ')}.dump"

    try:
        try:
            conn_src = await asyncpg.connect(database_url)
            org_count_pre = await conn_src.fetchval("SELECT count(*) FROM organizations")
            await conn_src.close()
        except Exception:
            org_count_pre = 0

        # Execute dump and restore via subprocess (assuming pg_dump/restore are in PATH inside the container)
        await asyncio.to_thread(_run, ["pg_dump", "--format=custom", "--no-owner", "--file", str(backup_path), database_url])
        await asyncio.to_thread(_run, ["pg_restore", "--clean", "--if-exists", "--no-owner", "--dbname", verify_database_url, str(backup_path)])
        
        try:
            conn_ver = await asyncpg.connect(verify_database_url)
            org_count_post = await conn_ver.fetchval("SELECT count(*) FROM organizations")
            user_count_post = await conn_ver.fetchval("SELECT count(*) FROM user_profiles")
            await conn_ver.close()
        except Exception as e:
            raise RuntimeError(f"Impossibile leggere il database di verifica post-restore: {e}")
            
        if org_count_post < org_count_pre:
            raise RuntimeError(f"Integrità compromessa: organizations post-restore ({org_count_post}) < pre-dump ({org_count_pre})")
        
        if org_count_post == 0 and user_count_post == 0 and org_count_pre > 0:
            raise RuntimeError("Il restore sembra vuoto nonostante il DB sorgente avesse dati.")

        finished = datetime.now(timezone.utc)
        return DrillResult(
            ok=True,
            backup_path=str(backup_path),
            started_at=started.isoformat(),
            finished_at=finished.isoformat(),
            detail=f"backup_restore_drill=ok org_count={org_count_post} user_count={user_count_post}",
        )
    except Exception as exc:
        try:
            sentry_sdk.capture_exception(exc)
        except Exception:
            logger.exception("backup_restore_drill=sentry_failed")
        logger.exception("backup_restore_drill=failed")
        raise


async def run_monthly_loop() -> None:
    interval_seconds = int(os.getenv("BACKUP_DRILL_INTERVAL_SECONDS", str(30 * 24 * 60 * 60)))
    run_on_start = os.getenv("BACKUP_DRILL_RUN_ON_START", "false").lower() in {"1", "true", "yes"}
    if run_on_start:
        await run_backup_restore_drill()
    while True:
        await asyncio.sleep(interval_seconds)
        await run_backup_restore_drill()
