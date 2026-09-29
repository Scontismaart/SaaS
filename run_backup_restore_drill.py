#!/usr/bin/env python3
import asyncio
import logging

from src.core.logging_filter import configure_logging
from src.core.observability import configure_error_reporting
from src.core.backup.drill import run_monthly_loop

configure_logging(level=logging.INFO)
configure_error_reporting()
logger = logging.getLogger("backup_restore_drill")


if __name__ == "__main__":
    logger.info("backup_restore_drill=started")
    asyncio.run(run_monthly_loop())
