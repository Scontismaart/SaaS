"""Behavioral contract tests: Fake, Adapter e Service condividono la stessa semantica.

Hardening Airtable: dimostra che Service, Fake e Adapter non solo hanno firme
compatibili ma si comportano allo stesso modo per:

- record non trovato (get/update/delete -> AirtableNotFoundError)
- risultato vuoto (list/search vuote)
- pagination (list_records pagine, list_all_records, iter_records)
- create / update (PATCH merge vs PUT replace) / delete
- error handling (404/422/429/5xx mappati dall'Adapter)
- batch (create_records con dict/BatchRecordItem/CreateRecordRequest, update_records, delete_records)

Il fake UNICO (FakeAirtablePort) eredita AirtablePort.
"""
from __future__ import annotations

import httpx
import pytest

from src.integrations.airtable import (
    AirtableAdapter,
    AirtableNotFoundError,
    AirtableRateLimitError,
    AirtableServerError,
    AirtableValidationError,
    BatchRecordItem,
    BatchUpdateRecordItem,
    CreateRecordRequest,
    ListRecordsParams,
    UpdateRecordRequest,
)
from tests.integrations.airtable.test_airtable_ai_tools import FakeAirtablePort

BASE_ID = "app_behavioral"
TABLE = "TblBehavior"


def _make_fake() -> FakeAirtablePort:
    return FakeAirtablePort()


def _make_adapter(handler) -> AirtableAdapter:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return AirtableAdapter(token="pat_behavioral_test", http_client=client)


# ── RECORD NON TROVATO ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fake_get_missing_raises_not_found():
    fake = _make_fake()
    with pytest.raises(AirtableNotFoundError):
        await fake.get_record(BASE_ID, TABLE, "rec_missing")


@pytest.mark.asyncio
async def test_fake_update_missing_raises_not_found():
    fake = _make_fake()
    with pytest.raises(AirtableNotFoundError):
        await fake.update_record(
            BASE_ID, TABLE, "rec_missing",
            UpdateRecordRequest(fields={"X": 1}, replace=False),
        )


@pytest.mark.asyncio
async def test_fake_delete_missing_raises_not_found():
    fake = _make_fake()
    with pytest.raises(AirtableNotFoundError):
        await fake.delete_record(BASE_ID, TABLE, "rec_missing")


@pytest.mark.asyncio
async def test_adapter_get_404_raises_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"type": "NOT_FOUND", "message": "not found"}})

    adapter = _make_adapter(handler)
    with pytest.raises(AirtableNotFoundError):
        await adapter.get_record(BASE_ID, TABLE, "rec_missing")


@pytest.mark.asyncio
async def test_adapter_delete_404_raises_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"type": "NOT_FOUND", "message": "not found"}})

    adapter = _make_adapter(handler)
    with pytest.raises(AirtableNotFoundError):
        await adapter.delete_record(BASE_ID, TABLE, "rec_missing")


# ── RISULTATO VUOTO ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fake_empty_table_list_and_search():
    fake = _make_fake()
    page = await fake.list_records(BASE_ID, TABLE)
    assert page.records == []
    assert page.offset is None
    assert await fake.list_all_records(BASE_ID, TABLE) == []
    assert await fake.search_records(BASE_ID, TABLE, formula="OR()") == []
    assert await fake.search_records(BASE_ID, TABLE, formula=None) == []


@pytest.mark.asyncio
async def test_adapter_empty_list():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"records": []})

    adapter = _make_adapter(handler)
    page = await adapter.list_records(BASE_ID, TABLE)
    assert page.records == []
    assert await adapter.search_records(BASE_ID, TABLE, formula=None) == []


# ── PAGINATION ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fake_pagination_list_and_list_all_and_iter():
    fake = _make_fake()
    for i in range(5):
        fake.seed_record(BASE_ID, TABLE, {"Index": i})

    page1 = await fake.list_records(BASE_ID, TABLE, params=ListRecordsParams(page_size=2))
    assert [r["Index"] for r in page1.records] == [0, 1]
    assert page1.offset is not None

    page2 = await fake.list_records(
        BASE_ID, TABLE, params=ListRecordsParams(page_size=2, offset=page1.offset)
    )
    assert [r["Index"] for r in page2.records] == [2, 3]

    all_records = await fake.list_all_records(BASE_ID, TABLE, max_records=4)
    assert len(all_records) == 4

    seen = [r["Index"] async for r in fake.iter_records(BASE_ID, TABLE)]
    assert seen == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_adapter_list_all_truncates_to_max_records():
    seen_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(
            200,
            json={
                "records": [{"id": f"rec_{i}", "fields": {"Index": i}} for i in range(10)],
                "offset": "next",
            },
        )

    adapter = _make_adapter(handler)
    records = await adapter.list_all_records(BASE_ID, TABLE, max_records=7)
    assert len(records) == 7
    assert len(seen_requests) == 1


# ── CREATE / UPDATE / DELETE ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fake_create_update_delete_lifecycle():
    fake = _make_fake()
    rec = await fake.create_record(BASE_ID, TABLE, CreateRecordRequest(fields={"Nome": "A"}))
    assert rec.id.startswith("rec")
    assert rec.fields == {"Nome": "A"}

    fetched = await fake.get_record(BASE_ID, TABLE, rec.id)
    assert fetched.id == rec.id

    # PATCH: merge parziale
    patched = await fake.update_record(
        BASE_ID, TABLE, rec.id, UpdateRecordRequest(fields={"Extra": 1}, replace=False)
    )
    assert patched.fields == {"Nome": "A", "Extra": 1}

    # PUT: rimpiazzo distruttivo
    replaced = await fake.update_record(
        BASE_ID, TABLE, rec.id, UpdateRecordRequest(fields={"Solo": True}, replace=True)
    )
    assert replaced.fields == {"Solo": True}

    res = await fake.delete_record(BASE_ID, TABLE, rec.id)
    assert res.deleted is True
    with pytest.raises(AirtableNotFoundError):
        await fake.get_record(BASE_ID, TABLE, rec.id)


@pytest.mark.asyncio
async def test_adapter_update_uses_patch_vs_put():
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(200, json={"id": "rec1", "fields": {"Ok": True}})

    adapter = _make_adapter(handler)
    await adapter.update_record(
        BASE_ID, TABLE, "rec1", UpdateRecordRequest(fields={"Ok": True}, replace=False)
    )
    await adapter.update_record(
        BASE_ID, TABLE, "rec1", UpdateRecordRequest(fields={"Ok": True}, replace=True)
    )
    assert methods == ["PATCH", "PUT"]


@pytest.mark.asyncio
async def test_adapter_create_and_delete_mapping():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "rec9", "fields": {"Nome": "B"}})
        return httpx.Response(200, json={"id": "rec9", "deleted": True})

    adapter = _make_adapter(handler)
    rec = await adapter.create_record(BASE_ID, TABLE, CreateRecordRequest(fields={"Nome": "B"}))
    assert rec.id == "rec9"
    res = await adapter.delete_record(BASE_ID, TABLE, "rec9")
    assert res.deleted is True


# ── ERROR HANDLING ADAPTER ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_adapter_422_raises_validation():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"error": {"type": "INVALID_REQUEST", "message": "bad"}})

    adapter = _make_adapter(handler)
    with pytest.raises(AirtableValidationError):
        await adapter.create_record(BASE_ID, TABLE, CreateRecordRequest(fields={}))


@pytest.mark.asyncio
async def test_adapter_429_raises_rate_limit_without_retry():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"type": "RATE_LIMIT", "message": "slow"}})

    adapter = _make_adapter(handler)
    adapter._max_retries = 0
    with pytest.raises(AirtableRateLimitError):
        await adapter.list_records(BASE_ID, TABLE)


@pytest.mark.asyncio
async def test_adapter_500_raises_server_without_retry():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    adapter = _make_adapter(handler)
    adapter._max_retries = 0
    with pytest.raises(AirtableServerError):
        await adapter.list_records(BASE_ID, TABLE)


# ── BATCH ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fake_batch_create_accepts_all_item_shapes():
    fake = _make_fake()
    created = await fake.create_records(
        BASE_ID,
        TABLE,
        [
            {"Nome": "dict-shape"},
            BatchRecordItem(fields={"Nome": "batch-item"}),
            CreateRecordRequest(fields={"Nome": "dto-shape"}),
        ],
    )
    assert [r["Nome"] for r in created] == ["dict-shape", "batch-item", "dto-shape"]
    assert len(await fake.list_all_records(BASE_ID, TABLE)) == 3


@pytest.mark.asyncio
async def test_fake_batch_update_patch_vs_replace_and_delete():
    fake = _make_fake()
    r1 = fake.seed_record(BASE_ID, TABLE, {"Nome": "R1", "Keep": "yes"})
    r2 = fake.seed_record(BASE_ID, TABLE, {"Nome": "R2", "Keep": "yes"})

    patched = await fake.update_records(
        BASE_ID, TABLE,
        [BatchUpdateRecordItem(id=r1.id, fields={"Nome": "R1-new"}), {"id": r2.id, "fields": {"Nome": "R2-new"}}],
        replace=False,
    )
    assert patched[0].fields["Keep"] == "yes"
    assert patched[1].fields["Keep"] == "yes"

    replaced = await fake.update_records(
        BASE_ID, TABLE, [{"id": r1.id, "fields": {"Solo": 1}}], replace=True
    )
    assert replaced[0].fields == {"Solo": 1}

    results = await fake.delete_records(BASE_ID, TABLE, [r1.id, r2.id])
    assert all(r.deleted for r in results)
    assert await fake.list_all_records(BASE_ID, TABLE) == []


@pytest.mark.asyncio
async def test_fake_batch_update_missing_raises_not_found():
    fake = _make_fake()
    with pytest.raises(AirtableNotFoundError):
        await fake.update_records(BASE_ID, TABLE, [{"id": "rec_missing", "fields": {}}])
