"""Test Live Sandbox per Airtable Web API v0 contro Base Reale.

SICUREZZA & ISOLAMENTO DI PRODUZIONE:
1. Non legge mai credenziali dal database di produzione (airtable_connections)
   né accede a dati o tabelle di clienti reali.
2. Le credenziali vengono lette ESCLUSIVAMENTE da variabili d'ambiente dedicate:
   - AIRTABLE_SANDBOX_TOKEN
   - AIRTABLE_SANDBOX_BASE_ID
   - AIRTABLE_SANDBOX_TABLE_NAME (opzionale con auto-discovery)
   - AIRTABLE_SANDBOX_CONFIRMED=true (opt-in esplicito non-production)
3. In assenza di queste variabili, l'intera suite viene saltata (skip) fail-closed
   senza errori né chiamate di rete.
4. Ogni record creato nell'ambiente sandbox utilizza prefissi sintetici sentinella univoci:
   - [TEST-MELPIS-AIRTABLE] Live Verification Record
5. Teardown rigoroso: ogni record creato viene cancellato in un blocco `finally`
   per garantire pulizia totale e zero orfani.
"""
from __future__ import annotations

import os
import uuid
import pytest

from src.integrations.airtable.adapter import AirtableAdapter
from src.integrations.airtable.models import (
    BatchRecordItem,
    BatchUpdateRecordItem,
    CreateRecordRequest,
    UpdateRecordRequest,
)

SANDBOX_TOKEN = os.getenv("AIRTABLE_SANDBOX_TOKEN")
SANDBOX_BASE_ID = os.getenv("AIRTABLE_SANDBOX_BASE_ID")
SANDBOX_TABLE_NAME = os.getenv("AIRTABLE_SANDBOX_TABLE_NAME")


def sandbox_confirmed():
    return os.getenv("AIRTABLE_SANDBOX_CONFIRMED") == "true" and bool(SANDBOX_TOKEN and SANDBOX_BASE_ID)

pytestmark = pytest.mark.skipif(
    not sandbox_confirmed(),
    reason="Test LIVE Airtable: richiede opt-in AIRTABLE_SANDBOX_CONFIRMED e credenziali dedicate sandbox",
)


@pytest.fixture
async def live_airtable_adapter():
    """Istanzia AirtableAdapter puntando al token live di test."""
    adapter = AirtableAdapter(token=SANDBOX_TOKEN or "")
    return adapter


@pytest.mark.asyncio
async def test_live_airtable_schema_inspection(live_airtable_adapter: AirtableAdapter):
    """Verifica autenticazione e lettura dello schema della Base reale tramite Metadata API."""
    tables = await live_airtable_adapter.get_base_schema(SANDBOX_BASE_ID or "")
    assert len(tables) > 0, f"La Base '{SANDBOX_BASE_ID}' non contiene tabelle."
    first_table = tables[0]
    assert first_table.id.startswith("tbl")
    assert len(first_table.fields) > 0


@pytest.mark.asyncio
async def test_live_airtable_crud_lifecycle_with_teardown(live_airtable_adapter: AirtableAdapter):
    """Ciclo completo CRUD reale: Create -> Get -> Update -> Search -> Teardown Delete."""
    base_id = SANDBOX_BASE_ID or ""
    tables = await live_airtable_adapter.get_base_schema(base_id)
    assert len(tables) > 0

    # Auto-discovery della tabella e del campo primario
    target_table = None
    if SANDBOX_TABLE_NAME:
        for t in tables:
            if t.name.lower() == SANDBOX_TABLE_NAME.lower() or t.id == SANDBOX_TABLE_NAME:
                target_table = t
                break
    if not target_table:
        target_table = tables[0]

    primary_field_name = target_table.fields[0].name
    unique_run_id = uuid.uuid4().hex[:8]
    sentinel_value = f"[TEST-MELPIS-AIRTABLE] Run {unique_run_id}"

    created_record = None
    try:
        # 1. CREATE RECORD
        create_req = CreateRecordRequest(
            fields={primary_field_name: sentinel_value},
            typecast=True,
        )
        created_record = await live_airtable_adapter.create_record(
            base_id=base_id,
            table_id_or_name=target_table.id,
            request=create_req,
        )
        assert created_record.id.startswith("rec")
        assert created_record.fields.get(primary_field_name) == sentinel_value

        # 2. GET RECORD
        fetched = await live_airtable_adapter.get_record(
            base_id=base_id,
            table_id_or_name=target_table.id,
            record_id=created_record.id,
        )
        assert fetched.id == created_record.id
        assert fetched.fields.get(primary_field_name) == sentinel_value

        # 3. UPDATE RECORD (PATCH)
        updated_value = f"{sentinel_value} - UPDATED"
        update_req = UpdateRecordRequest(
            fields={primary_field_name: updated_value},
            replace=False,
        )
        updated = await live_airtable_adapter.update_record(
            base_id=base_id,
            table_id_or_name=target_table.id,
            record_id=created_record.id,
            request=update_req,
        )
        assert updated.fields.get(primary_field_name) == updated_value

        # 4. SEARCH RECORD
        formula = f"{{{primary_field_name}}} = '{updated_value}'"
        search_results = await live_airtable_adapter.search_records(
            base_id=base_id,
            table_id_or_name=target_table.id,
            formula=formula,
        )
        assert any(r.id == created_record.id for r in search_results)

    finally:
        # 5. TEARDOWN DELETE RECORD
        if created_record:
            del_result = await live_airtable_adapter.delete_record(
                base_id=base_id,
                table_id_or_name=target_table.id,
                record_id=created_record.id,
            )
            assert del_result.deleted is True
            assert del_result.id == created_record.id


@pytest.mark.asyncio
async def test_live_airtable_batch_lifecycle_with_teardown(live_airtable_adapter: AirtableAdapter):
    """Ciclo batch reale: Batch Create -> Batch Update -> Batch Delete."""
    base_id = SANDBOX_BASE_ID or ""
    tables = await live_airtable_adapter.get_base_schema(base_id)
    assert len(tables) > 0
    target_table = tables[0]
    primary_field_name = target_table.fields[0].name

    unique_run_id = uuid.uuid4().hex[:6]
    items_to_create = [
        BatchRecordItem(fields={primary_field_name: f"[TEST-MELPIS-BATCH-{i}] {unique_run_id}"})
        for i in range(2)
    ]

    created_records = []
    try:
        # 1. BATCH CREATE
        created_records = await live_airtable_adapter.create_records(
            base_id=base_id,
            table_id_or_name=target_table.id,
            records=items_to_create,
            typecast=True,
        )
        assert len(created_records) == 2
        for rec in created_records:
            assert rec.id.startswith("rec")

        # 2. BATCH UPDATE
        items_to_update = [
            BatchUpdateRecordItem(
                id=rec.id,
                fields={primary_field_name: f"{rec.fields.get(primary_field_name)} - UP"},
            )
            for rec in created_records
        ]
        updated_records = await live_airtable_adapter.update_records(
            base_id=base_id,
            table_id_or_name=target_table.id,
            records=items_to_update,
            replace=False,
        )
        assert len(updated_records) == 2

    finally:
        # 3. BATCH DELETE TEARDOWN
        if created_records:
            rec_ids = [r.id for r in created_records]
            del_results = await live_airtable_adapter.delete_records(
                base_id=base_id,
                table_id_or_name=target_table.id,
                record_ids=rec_ids,
            )
            assert len(del_results) == 2
            assert all(dr.deleted for dr in del_results)
