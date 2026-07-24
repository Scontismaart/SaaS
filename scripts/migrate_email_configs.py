#!/usr/bin/env python3
"""One-shot migration: email_config.json -> email_configs table.

Usage: python scripts/migrate_email_configs.py <organization_id>
"""

import argparse
import asyncio
import json
import os
import uuid

import asyncpg


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("organization_id", type=uuid.UUID)
    parser.add_argument("--dsn", default=os.getenv("POSTGRES_DSN"))
    parser.add_argument("--config-path", default="data/email_config.json")
    args = parser.parse_args()

    if not os.path.exists(args.config_path):
        print(f"No config file found at {args.config_path}")
        return

    with open(args.config_path) as f:
        configs = json.load(f)

    pool = await asyncpg.create_pool(dsn=args.dsn)
    try:
        async with pool.acquire() as conn:
            for cfg in configs:
                await conn.execute("""
                    INSERT INTO email_configs (id, organization_id, indirizzo)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (organization_id, indirizzo) DO NOTHING
                """, uuid.uuid4(), args.organization_id, cfg["indirizzo"])
        print(f"Migrated {len(configs)} email configs")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
