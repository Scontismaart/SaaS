"""Script diagnostico di esecuzione live per Airtable Web API v0.

Permette di:
1. Eseguire un probe HTTP reale contro il gateway live https://api.airtable.com
2. Eseguire il ciclo completo end-to-end (Create -> Get -> Update -> Search -> Teardown Delete)
   non appena vengono fornite le credenziali di test.
"""
import argparse
import asyncio
import os
import sys
import time
import httpx

from dotenv import load_dotenv

# Aggiungi root al path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
load_dotenv()

from src.integrations.airtable.adapter import AirtableAdapter
from src.integrations.airtable.models import CreateRecordRequest, UpdateRecordRequest


async def probe_gateway():
    print("\n--- 1. PROBE HTTP GATEWAY AIRTABLE LIVE ---")
    url = "https://api.airtable.com/v0/meta/bases"
    print(f"Richiesta GET verso {url} (senza credenziali)...")
    start = time.perf_counter()
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
    elapsed = time.perf_counter() - start
    print(f"Status Code: HTTP {resp.status_code}")
    print(f"Latenza: {elapsed:.3f}s")
    print(f"Server Header: {resp.headers.get('server', 'N/A')}")
    print(f"Content-Type: {resp.headers.get('content-type', 'N/A')}")
    print(f"Body: {resp.text[:300]}")
    return resp.status_code == 401


async def run_live_test(token: str, base_id: str, table_name: str | None = None):
    print("\n--- 2. ESECUZIONE TEST LIVE CONTRO BASE REALE ---")
    adapter = AirtableAdapter(token=token)
    print(f"Adapter istanziato: {adapter}")

    print(f"\n[Passo 1/5] Ispezione schema Base '{base_id}' via Metadata API...")
    tables = await adapter.get_base_schema(base_id)
    print(f"Tabelle trovate ({len(tables)}): {[t.name for t in tables]}")
    if not tables:
        print("ERRORE: La base non contiene alcuna tabella.")
        return False

    target_table = tables[0]
    if table_name:
        for t in tables:
            if t.name.lower() == table_name.lower() or t.id == table_name:
                target_table = t
                break

    print(f"Tabella target: '{target_table.name}' (ID: {target_table.id})")
    primary_field = target_table.fields[0].name
    print(f"Campo primario: '{primary_field}' (Tipo: {target_table.fields[0].type})")

    sentinel = f"[TEST-MELPIS] Live Verification {int(time.time())}"

    created_id = None
    try:
        # Create
        print(f"\n[Passo 2/5] Creazione record sintetico sentinella '{sentinel}'...")
        rec = await adapter.create_record(
            base_id=base_id,
            table_id_or_name=target_table.id,
            request=CreateRecordRequest(fields={primary_field: sentinel}, typecast=True),
        )
        created_id = rec.id
        print(f"Record creato con successo: ID={rec.id}, Fields={rec.fields}")

        # Get
        print(f"\n[Passo 3/5] Lettura record via GET ID '{created_id}'...")
        fetched = await adapter.get_record(base_id, target_table.id, created_id)
        print(f"Record letto: ID={fetched.id}, Field={fetched.fields.get(primary_field)}")

        # Update
        updated_val = f"{sentinel} [UPDATED]"
        print(f"\n[Passo 4/5] Aggiornamento record via PATCH...")
        updated = await adapter.update_record(
            base_id, target_table.id, created_id,
            UpdateRecordRequest(fields={primary_field: updated_val}),
        )
        print(f"Record aggiornato: Field={updated.fields.get(primary_field)}")

        # Search
        formula = f"{{{primary_field}}} = '{updated_val}'"
        print(f"\n[Passo 5/5] Ricerca record con formula: {formula}...")
        results = await adapter.search_records(base_id, target_table.id, formula)
        print(f"Risultati ricerca: {len(results)} trovati (ID: {[r.id for r in results]})")
        assert any(r.id == created_id for r in results), "Record non trovato nella ricerca"

        print("\nESITO TEST LIVE: TUTTE LE OPERAZIONI HANNO AVUTO SUCCESSO!")
        return True

    finally:
        if created_id:
            print(f"\n[TEARDOWN] Cancellazione record sintetico '{created_id}'...")
            del_res = await adapter.delete_record(base_id, target_table.id, created_id)
            print(f"Teardown completato: ID={del_res.id}, Deleted={del_res.deleted}")


async def main():
    parser = argparse.ArgumentParser(description="Airtable Live Diagnostics")
    parser.add_argument("--token", help="Personal Access Token Airtable (pat...)")
    parser.add_argument("--base", help="Base ID Airtable (app...)")
    parser.add_argument("--table", help="Nome o ID tabella Airtable", default=None)
    args = parser.parse_args()

    token = args.token or os.getenv("AIRTABLE_SANDBOX_TOKEN") or os.getenv("AIRTABLE_PAT")
    base_id = args.base or os.getenv("AIRTABLE_SANDBOX_BASE_ID") or os.getenv("AIRTABLE_BASE_ID")
    table_name = args.table or os.getenv("AIRTABLE_SANDBOX_TABLE_NAME")

    # Esegui sempre il probe HTTP gateway
    await probe_gateway()

    if token and base_id:
        await run_live_test(token, base_id, table_name)
    else:
        print("\n[INFO] Per eseguire il test CRUD live contro una base reale, fornisci:")
        print("  --token <AIRTABLE_PAT>")
        print("  --base <AIRTABLE_BASE_ID>")
        print("oppure imposta le variabili d'ambiente AIRTABLE_SANDBOX_TOKEN e AIRTABLE_SANDBOX_BASE_ID.")


if __name__ == "__main__":
    asyncio.run(main())
