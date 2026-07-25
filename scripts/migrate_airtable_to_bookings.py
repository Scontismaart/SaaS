#!/usr/bin/env python3
"""One-shot migration: Airtable -> bookings table.

Usage: python scripts/migrate_airtable_to_bookings.py <organization_id>

Reads all records from Airtable Prenotazioni table, transforms them to
bookings rows, and bulk-inserts into PostgreSQL.
"""

import argparse
import asyncio
import os
import uuid

import asyncpg
from pyairtable import Api


def fetch_airtable_bookings() -> list[dict]:
    api_key = os.getenv("AIRTABLE_API_KEY")
    base_id = os.getenv("AIRTABLE_BASE_ID")
    table_name = os.getenv("AIRTABLE_TABLE_NAME", "Prenotazioni")
    if not api_key or not base_id:
        print("AIRTABLE_API_KEY and AIRTABLE_BASE_ID must be set")
        return []
    api = Api(api_key)
    table = api.table(base_id, table_name)
    records = table.all()
    result = []
    for r in records:
        fields = r.get("fields", {})
        data = fields.get("Data prenotazione") or ""
        ora = ""
        ora_pren = fields.get("Ora prenotazione") or ""
        if isinstance(ora_pren, str) and "T" in ora_pren:
            data = data or ora_pren[:10]
            ora = ora_pren[11:16]
        elif isinstance(ora_pren, str):
            ora = ora_pren[:5]
        result.append({
            "nome_cliente": fields.get("Nome cliente", ""),
            "telefono": fields.get("Telefono", ""),
            "data": data,
            "ora": ora,
            "coperti": fields.get("Numero coperti"),
            "note": fields.get("Note", ""),
            "stato": fields.get("Stato", "in_attesa").lower().replace(" ", "_"),
            "origine": fields.get("Origine", "Airtable"),
            "richiede_intervento": bool(fields.get("Richiesta umano", False)),
            "id_conversazione": fields.get("ID conversazione"),
        })
    return result


async def insert_bookings(pool, org_id, bookings: list[dict]):
    async with pool.acquire() as conn:
        for b in bookings:
            await conn.execute("""
                INSERT INTO bookings (id, organization_id, nome_cliente, telefono,
                                      data, ora, coperti, note, stato, origine,
                                      richiede_intervento, id_conversazione)
                VALUES ($1, $2, $3, $4, $5::date, $6::time, $7, $8, $9, $10, $11, $12)
                ON CONFLICT DO NOTHING
            """, uuid.uuid4(), org_id, b["nome_cliente"], b["telefono"],
            b["data"] or None, b["ora"] or None, b["coperti"],
            b["note"], b["stato"], b["origine"],
            b["richiede_intervento"], b["id_conversazione"])


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("organization_id", type=uuid.UUID)
    parser.add_argument("--dsn", default=os.getenv("POSTGRES_DSN"))
    args = parser.parse_args()

    print("Fetching Airtable bookings...")
    bookings = fetch_airtable_bookings()
    print(f"Found {len(bookings)} records")

    if not bookings:
        return

    pool = await asyncpg.create_pool(dsn=args.dsn)
    try:
        await insert_bookings(pool, args.organization_id, bookings)
        print(f"Inserted {len(bookings)} bookings")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
