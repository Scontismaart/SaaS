"""Unit test esaustivi per operazioni CRUD e Batch di Airtable (Port & Adapter).

Verifica:
- list_all_records con paginazione trasparente e capping max_records
- iter_records generatore asincrono streaming
- create_records batching (<=10 e chunking automatico per >10)
- update_records batching (PATCH merge vs PUT replace, chunking >10)
- delete_records batching (records[]=... e chunking >10)
- gestione risposte malformate (AirtableMalformedResponseError)
- escaping sicuro di base_id, table name con spazi e caratteri speciali
- zero leak di secret, token e payload nei log
"""
import json
import logging
from urllib.parse import parse_qs, unquote

import httpx
import pytest

from src.integrations.airtable import (
    AirtableAdapter,
    AirtableMalformedResponseError,
    BatchRecordItem,
    BatchUpdateRecordItem,
    CreateRecordRequest,
    ListRecordsParams,
    UpdateRecordRequest,
)


# ── TEST BATCH MODELS ─────────────────────────────────────────────────────────


def test_batch_record_item_models():
    create_item = BatchRecordItem(fields={"Nome": "Mario", "Quota": 100})
    assert create_item.fields["Nome"] == "Mario"

    update_item = BatchUpdateRecordItem(id="rec123", fields={"Quota": 150})
    assert update_item.id == "rec123"
    assert update_item.fields["Quota"] == 150


# ── TEST LIST_ALL_RECORDS & ITER_RECORDS (PAGINATION) ─────────────────────────


@pytest.mark.asyncio
async def test_list_all_records_multi_page():
    requests_received = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        requests_received.append(request)
        url_str = str(request.url)
        if "offset=page2_token" in url_str:
            return httpx.Response(
                200,
                json={
                    "records": [
                        {"id": "rec3", "fields": {"Val": 3}},
                        {"id": "rec4", "fields": {"Val": 4}},
                    ],
                    # Nessun offset: fine pagine
                },
            )
        else:
            return httpx.Response(
                200,
                json={
                    "records": [
                        {"id": "rec1", "fields": {"Val": 1}},
                        {"id": "rec2", "fields": {"Val": 2}},
                    ],
                    "offset": "page2_token",
                },
            )

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = AirtableAdapter(token="pat_mock_test", http_client=client)

    all_records = await adapter.list_all_records("appTest", "Lead")

    assert len(all_records) == 4
    assert [r.id for r in all_records] == ["rec1", "rec2", "rec3", "rec4"]
    assert len(requests_received) == 2


@pytest.mark.asyncio
async def test_list_all_records_with_max_records_limit():
    requests_received = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        requests_received.append(request)
        return httpx.Response(
            200,
            json={
                "records": [
                    {"id": f"rec_{i}", "fields": {"Index": i}}
                    for i in range(1, 11)
                ],
                "offset": "next_page",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = AirtableAdapter(token="pat_mock_test", http_client=client)

    # Richiediamo solo 7 record: la prima pagina da 10 deve essere troncata esattamente a 7
    # e non deve chiamare la pagina successiva
    records = await adapter.list_all_records("appTest", "Lead", max_records=7)

    assert len(records) == 7
    assert len(requests_received) == 1
    assert records[0].id == "rec_1"
    assert records[-1].id == "rec_7"


@pytest.mark.asyncio
async def test_iter_records_streaming():
    requests_received = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        requests_received.append(request)
        url_str = str(request.url)
        if "offset=p2" in url_str:
            return httpx.Response(
                200,
                json={
                    "records": [{"id": "rec_b1"}, {"id": "rec_b2"}],
                },
            )
        else:
            return httpx.Response(
                200,
                json={
                    "records": [{"id": "rec_a1"}, {"id": "rec_a2"}],
                    "offset": "p2",
                },
            )

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = AirtableAdapter(token="pat_mock_test", http_client=client)

    collected_ids = []
    async for rec in adapter.iter_records("appTest", "Lead"):
        collected_ids.append(rec.id)

    assert collected_ids == ["rec_a1", "rec_a2", "rec_b1", "rec_b2"]
    assert len(requests_received) == 2


# ── TEST BATCH CREATE ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_batch_create_records_under_ten():
    recorded_body = None

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal recorded_body
        assert request.method == "POST"
        assert "/v0/appCRM/Clienti" in str(request.url)
        recorded_body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "records": [
                    {"id": "rec1", "createdTime": "2026-09-07T00:00:00.000Z", "fields": {"Nome": "A"}},
                    {"id": "rec2", "createdTime": "2026-09-07T00:00:00.000Z", "fields": {"Nome": "B"}},
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = AirtableAdapter(token="pat_mock_test", http_client=client)

    items = [
        BatchRecordItem(fields={"Nome": "A"}),
        {"Nome": "B"},
    ]
    created = await adapter.create_records("appCRM", "Clienti", items, typecast=True)

    assert len(created) == 2
    assert created[0].id == "rec1"
    assert created[1].id == "rec2"
    assert recorded_body["typecast"] is True
    assert len(recorded_body["records"]) == 2
    assert recorded_body["records"][0]["fields"] == {"Nome": "A"}
    assert recorded_body["records"][1]["fields"] == {"Nome": "B"}


@pytest.mark.asyncio
async def test_batch_create_records_chunking_over_ten():
    # Invio di 25 record: deve suddividere in chunk da 10, 10, 5 (3 richieste HTTP)
    batch_calls = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        batch_calls.append(data["records"])
        return httpx.Response(
            200,
            json={
                "records": [
                    {"id": f"rec_{item['fields']['n']}", "fields": item["fields"]}
                    for item in data["records"]
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = AirtableAdapter(token="pat_mock_test", http_client=client)

    items = [{"n": i} for i in range(25)]
    created = await adapter.create_records("appCRM", "Clienti", items)

    assert len(created) == 25
    assert len(batch_calls) == 3
    assert len(batch_calls[0]) == 10
    assert len(batch_calls[1]) == 10
    assert len(batch_calls[2]) == 5
    assert created[0].id == "rec_0"
    assert created[24].id == "rec_24"


@pytest.mark.asyncio
async def test_batch_create_records_empty():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(500)))
    adapter = AirtableAdapter(token="pat_mock_test", http_client=client)

    res = await adapter.create_records("appCRM", "Clienti", [])
    assert res == []


# ── TEST BATCH UPDATE ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_batch_update_records_patch_and_put():
    methods_used = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        methods_used.append(request.method)
        data = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "records": [
                    {"id": r["id"], "fields": r["fields"]}
                    for r in data["records"]
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = AirtableAdapter(token="pat_mock_test", http_client=client)

    items = [
        BatchUpdateRecordItem(id="rec1", fields={"Status": "OK"}),
        {"id": "rec2", "fields": {"Status": "Pending"}},
    ]

    # Test PATCH (replace=False)
    res_patch = await adapter.update_records("appCRM", "Clienti", items, replace=False)
    assert len(res_patch) == 2
    assert methods_used[-1] == "PATCH"

    # Test PUT (replace=True)
    res_put = await adapter.update_records("appCRM", "Clienti", items, replace=True)
    assert len(res_put) == 2
    assert methods_used[-1] == "PUT"


@pytest.mark.asyncio
async def test_batch_update_records_chunking_over_ten():
    batch_calls = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        batch_calls.append(data["records"])
        return httpx.Response(
            200,
            json={
                "records": [
                    {"id": r["id"], "fields": r["fields"]}
                    for r in data["records"]
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = AirtableAdapter(token="pat_mock_test", http_client=client)

    items = [BatchUpdateRecordItem(id=f"rec_{i}", fields={"idx": i}) for i in range(23)]
    updated = await adapter.update_records("appCRM", "Clienti", items)

    assert len(updated) == 23
    assert len(batch_calls) == 3
    assert len(batch_calls[0]) == 10
    assert len(batch_calls[1]) == 10
    assert len(batch_calls[2]) == 3


@pytest.mark.asyncio
async def test_batch_update_records_empty():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(500)))
    adapter = AirtableAdapter(token="pat_mock_test", http_client=client)

    res = await adapter.update_records("appCRM", "Clienti", [])
    assert res == []


# ── TEST BATCH DELETE ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_batch_delete_records_under_ten():
    query_params_sent = None

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal query_params_sent
        assert request.method == "DELETE"
        assert "/v0/appCRM/Clienti" in str(request.url)
        query_params_sent = parse_qs(request.url.query.decode())
        return httpx.Response(
            200,
            json={
                "records": [
                    {"id": "rec1", "deleted": True},
                    {"id": "rec2", "deleted": True},
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = AirtableAdapter(token="pat_mock_test", http_client=client)

    results = await adapter.delete_records("appCRM", "Clienti", ["rec1", "rec2"])

    assert len(results) == 2
    assert all(r.deleted for r in results)
    assert query_params_sent["records[]"] == ["rec1", "rec2"]


@pytest.mark.asyncio
async def test_batch_delete_records_chunking_over_ten():
    delete_queries = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        qs = parse_qs(request.url.query.decode())
        rec_ids = qs.get("records[]", [])
        delete_queries.append(rec_ids)
        return httpx.Response(
            200,
            json={"records": [{"id": rid, "deleted": True} for rid in rec_ids]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = AirtableAdapter(token="pat_mock_test", http_client=client)

    ids_to_del = [f"rec_{i}" for i in range(22)]
    results = await adapter.delete_records("appCRM", "Clienti", ids_to_del)

    assert len(results) == 22
    assert len(delete_queries) == 3
    assert len(delete_queries[0]) == 10
    assert len(delete_queries[1]) == 10
    assert len(delete_queries[2]) == 2


@pytest.mark.asyncio
async def test_batch_delete_records_empty():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(500)))
    adapter = AirtableAdapter(token="pat_mock_test", http_client=client)

    res = await adapter.delete_records("appCRM", "Clienti", [])
    assert res == []


# ── TEST URL ENCODING CON SPAZI E SPECIAL CHARACTERS ─────────────────────────


@pytest.mark.asyncio
async def test_table_and_base_name_encoding():
    requested_url = ""

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal requested_url
        requested_url = str(request.url)
        return httpx.Response(200, json={"records": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = AirtableAdapter(token="pat_mock_test", http_client=client)

    # Base e tabella con spazi, slash, caratteri accentati
    base_id = "app 123/prod"
    table_name = "Prenotazioni & Clienti VIP"

    await adapter.list_records(base_id, table_name)

    # La URL deve contenere la codifica percentuale sicura
    assert "/v0/app%20123%2Fprod/Prenotazioni%20%26%20Clienti%20VIP" in requested_url


# ── TEST MALFORMED RESPONSES ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_malformed_json_response_raises_malformed_error():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="This is not valid JSON <xml>error</xml>")

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = AirtableAdapter(token="pat_mock_test", http_client=client)

    with pytest.raises(AirtableMalformedResponseError) as exc_info:
        await adapter.get_record("appCRM", "Leads", "rec1")

    assert exc_info.value.status_code == 502
    assert exc_info.value.error_type == "MALFORMED_RESPONSE"
    assert "non decodificabile come JSON" in str(exc_info.value)


@pytest.mark.asyncio
async def test_non_dict_json_response_raises_malformed_error():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        # JSON valido sintatticamente ma array invece di oggetto dict
        return httpx.Response(200, json=["unexpected", "list"])

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = AirtableAdapter(token="pat_mock_test", http_client=client)

    with pytest.raises(AirtableMalformedResponseError) as exc_info:
        await adapter.get_record("appCRM", "Leads", "rec1")

    assert exc_info.value.status_code == 502
    assert "atteso oggetto JSON dict" in str(exc_info.value)


# ── TEST SECURITY & LOGGING HYGIENE ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_logging_hygiene_no_token_or_pii_leaks(caplog):
    secret_pat = "pat_ultra_confidential_99999"
    customer_phone = "+393339988776"
    customer_name = "Gianna Nannini"

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "rec1",
                "fields": {"Nome": customer_name, "Telefono": customer_phone},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = AirtableAdapter(token=secret_pat, http_client=client)

    with caplog.at_level(logging.DEBUG):
        await adapter.get_record("app1", "Clienti", "rec1")
        _ = repr(adapter)

    log_text = caplog.text
    # Invariante 10: I token non devono mai comparire nei log
    assert secret_pat not in log_text
    # Nessun leak di PII non necessario
    assert customer_phone not in log_text
