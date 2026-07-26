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


STATO_MAP = {
    "in_attesa": "in_attesa",
    "confermato": "confermata",
    "confermata": "confermata",
    "cancellato": "cancellata",
    "cancellata": "cancellata",
    "annullato": "cancellata",
    "rifiutato": "rifiutata",
    "rifiutata": "rifiutata",
    "completato": "completata",
    "completata": "completata",
    "no_show": "no_show",
}


def _normalize_stato(raw: str | None) -> str:
    if not raw:
        return "in_attesa"
    normalized = raw.lower().replace(" ", "_")
    return STATO_MAP.get(normalized, "in_attesa")


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
    errors = []
    for i, r in enumerate(records):
        try:
            fields = r.get("fields", {})
            data = fields.get("Data prenotazione") or ""
            ora = ""
            ora_pren = fields.get("Ora prenotazione") or ""
            if isinstance(ora_pren, str) and "T" in ora_pren:
                data = data or ora_pren[:10]
                ora = ora_pren[11:16]
            elif isinstance(ora_pren, str):
                ora = ora_pren[:5]
            stato = _normalize_stato(fields.get("Stato"))
            result.append({
                "nome_cliente": fields.get("Nome cliente", ""),
                "telefono": fields.get("Telefono", ""),
                "data": data,
                "ora": ora,
                "coperti": fields.get("Numero coperti"),
                "note": fields.get("Note", ""),
                "stato": stato,
                "origine": fields.get("Origine", "Airtable"),
                "richiede_intervento": bool(fields.get("Richiesta umano", False)),
                "id_conversazione": fields.get("ID conversazione"),
            })
        except Exception as e:
            errors.append({"index": i, "record_id": r.get("id"), "error": str(e)})
    if errors:
        print(f"WARNING: {len(errors)} records failed to parse:")
        for e in errors:
            print(f"  [{e['index']}] id={e['record_id']}: {e['error']}")
    return result


async def insert_bookings(pool, org_id, bookings: list[dict]):
    inserted = 0
    errors = []
    async with pool.acquire() as conn:
        for i, b in enumerate(bookings):
            try:
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
                inserted += 1
            except Exception as e:
                errors.append({"index": i, "nome": b["nome_cliente"], "error": str(e)})
    if errors:
        print(f"WARNING: {len(errors)} rows failed to insert:")
        for e in errors:
            print(f"  [{e['index']}] {e['nome']}: {e['error']}")
    return inserted


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
        count = await insert_bookings(pool, args.organization_id, bookings)
        print(f"Inserted {count}/{len(bookings)} bookings")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
