"""Unit tests per il layer architetturale Airtable (Port, Adapter, DTO, Errori).

Esegue verifiche complete senza alcuna chiamata di rete esterna,
usando httpx.MockTransport per simulare il comportamento di Airtable Web API v0.
"""
import json
import pytest
import httpx

from src.integrations.airtable import (
    AirtableAdapter,
    AirtableAuthError,
    AirtableBase,
    AirtableError,
    AirtableField,
    AirtableNetworkError,
    AirtableNotFoundError,
    AirtablePort,
    AirtableQuotaExhaustedError,
    AirtableRateLimitError,
    AirtableRecord,
    AirtableServerError,
    AirtableTable,
    AirtableValidationError,
    CreateRecordRequest,
    DeleteRecordResult,
    ListRecordsParams,
    RecordPage,
    SchemaValidationResult,
    UpdateRecordRequest,
)


# ── TEST DTO & DATA MODEL ────────────────────────────────────────────────────


def test_airtable_dto_models():
    field1 = AirtableField(id="fld1", name="Nome", type="singleLineText")
    field2 = AirtableField(id="fld2", name="Telefono", type="phoneNumber")
    table = AirtableTable(id="tbl1", name="Leads", fields=[field1, field2])
    base = AirtableBase(id="app1", name="CRM Melpis", tables=[table])

    assert base.id == "app1"
    assert base.name == "CRM Melpis"
    assert len(base.tables) == 1
    assert base.tables[0].name == "Leads"
    assert len(base.tables[0].fields) == 2


def test_airtable_record_accessors():
    rec = AirtableRecord(
        id="rec123",
        created_time="2026-09-06T12:00:00.000Z",
        fields={"Nome": "Mario Rossi", "Telefono": "+393331234567", "Score": 95},
    )

    assert rec.id == "rec123"
    assert rec.get_field("Nome") == "Mario Rossi"
    assert rec.get_field("Inesistente", "default_val") == "default_val"
    assert rec["Telefono"] == "+393331234567"
    assert "Score" in rec
    assert "Email" not in rec


def test_record_page_pagination():
    page_with_more = RecordPage(
        records=[AirtableRecord(id="rec1", fields={"A": 1})],
        offset="itrNextPageToken",
    )
    assert page_with_more.has_more is True

    page_last = RecordPage(
        records=[AirtableRecord(id="rec2", fields={"A": 2})],
        offset=None,
    )
    assert page_last.has_more is False


def test_request_dtos():
    req_create = CreateRecordRequest(fields={"Nome": "Luigi"}, typecast=True)
    assert req_create.fields == {"Nome": "Luigi"}
    assert req_create.typecast is True

    req_update = UpdateRecordRequest(fields={"Stato": "Contattato"}, replace=False)
    assert req_update.replace is False

    del_res = DeleteRecordResult(id="rec999", deleted=True)
    assert del_res.deleted is True


# ── TEST ERROR HIERARCHY ─────────────────────────────────────────────────────


def test_airtable_error_hierarchy():
    err_rate = AirtableRateLimitError("Too many calls", retry_after=45.0)
    assert isinstance(err_rate, AirtableError)
    assert err_rate.status_code == 429
    assert err_rate.retry_after == 45.0

    err_auth = AirtableAuthError("Unauthorized", status_code=401)
    assert isinstance(err_auth, AirtableError)
    assert err_auth.status_code == 401

    err_net = AirtableNetworkError("Timeout")
    assert isinstance(err_net, AirtableError)


# ── TEST ADAPTER & PORT IMPLEMENTATION ───────────────────────────────────────


def test_adapter_implements_port():
    adapter = AirtableAdapter(token="pat_test_token_12345")
    assert isinstance(adapter, AirtablePort)


def test_adapter_zero_secrets_leak():
    token = "pat_very_secret_token_abcdefg"
    adapter = AirtableAdapter(token=token)
    repr_str = repr(adapter)

    # Invariante 10: Il token reale non deve mai apparire in chiaro nel repr
    assert token not in repr_str
    assert "pat_***" in repr_str or "***" in repr_str


def test_adapter_rejects_empty_token():
    with pytest.raises(ValueError, match="non può essere vuoto"):
        AirtableAdapter(token="  ")


@pytest.mark.asyncio
async def test_adapter_list_records_mocked():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert "/v0/app123/Leads%20VIP" in str(request.url)
        assert request.headers["authorization"] == "Bearer pat_test"
        assert "filterByFormula" in request.url.query.decode()

        content = {
            "records": [
                {
                    "id": "rec001",
                    "createdTime": "2026-09-06T10:00:00.000Z",
                    "fields": {"Nome": "Test Lead 1", "Telefono": "+39111"},
                }
            ],
            "offset": "next_page_token_abc",
        }
        return httpx.Response(200, json=content)

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = AirtableAdapter(token="pat_test", http_client=client)

    page = await adapter.list_records(
        base_id="app123",
        table_id_or_name="Leads VIP",
        params=ListRecordsParams(
            filter_by_formula="{Telefono} != ''",
            page_size=10,
        ),
    )

    assert len(page.records) == 1
    assert page.records[0].id == "rec001"
    assert page.records[0].fields["Nome"] == "Test Lead 1"
    assert page.has_more is True
    assert page.offset == "next_page_token_abc"


@pytest.mark.asyncio
async def test_adapter_get_record_mocked():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert "/v0/app123/Leads/recXYZ" in str(request.url)
        content = {
            "id": "recXYZ",
            "createdTime": "2026-09-06T10:00:00.000Z",
            "fields": {"Status": "Qualificato"},
        }
        return httpx.Response(200, json=content)

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = AirtableAdapter(token="pat_test", http_client=client)

    rec = await adapter.get_record("app123", "Leads", "recXYZ")
    assert rec.id == "recXYZ"
    assert rec.fields["Status"] == "Qualificato"


@pytest.mark.asyncio
async def test_adapter_create_record_mocked():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        body = json.loads(request.content)
        assert body["fields"]["Nome"] == "Nuovo Contatto"
        assert body["typecast"] is True

        content = {
            "id": "recNew999",
            "createdTime": "2026-09-06T11:00:00.000Z",
            "fields": body["fields"],
        }
        return httpx.Response(200, json=content)

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = AirtableAdapter(token="pat_test", http_client=client)

    rec = await adapter.create_record(
        base_id="app123",
        table_id_or_name="Leads",
        request=CreateRecordRequest(
            fields={"Nome": "Nuovo Contatto"},
            typecast=True,
        ),
    )
    assert rec.id == "recNew999"
    assert rec.fields["Nome"] == "Nuovo Contatto"


@pytest.mark.asyncio
async def test_adapter_update_record_patch_and_put():
    called_methods = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        called_methods.append(request.method)
        content = {
            "id": "rec123",
            "fields": {"Updated": True},
        }
        return httpx.Response(200, json=content)

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = AirtableAdapter(token="pat_test", http_client=client)

    # 1. Update con PATCH (replace=False)
    await adapter.update_record(
        "app1", "Tbl", "rec123",
        UpdateRecordRequest(fields={"Updated": True}, replace=False),
    )
    assert called_methods[-1] == "PATCH"

    # 2. Update con PUT (replace=True)
    await adapter.update_record(
        "app1", "Tbl", "rec123",
        UpdateRecordRequest(fields={"Updated": True}, replace=True),
    )
    assert called_methods[-1] == "PUT"


@pytest.mark.asyncio
async def test_adapter_delete_record():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        return httpx.Response(200, json={"id": "recDel", "deleted": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = AirtableAdapter(token="pat_test", http_client=client)

    res = await adapter.delete_record("app1", "Tbl", "recDel")
    assert res.id == "recDel"
    assert res.deleted is True


@pytest.mark.asyncio
async def test_adapter_search_records_pagination():
    call_count = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(200, json={
                "records": [{"id": "rec1", "fields": {"Index": 1}}],
                "offset": "page2",
            })
        else:
            return httpx.Response(200, json={
                "records": [{"id": "rec2", "fields": {"Index": 2}}],
            })

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = AirtableAdapter(token="pat_test", http_client=client)

    records = await adapter.search_records(
        base_id="app1",
        table_id_or_name="Tbl",
        formula="{Index} > 0",
    )

    assert len(records) == 2
    assert records[0].id == "rec1"
    assert records[1].id == "rec2"
    assert call_count == 2


@pytest.mark.asyncio
async def test_adapter_error_normalization_401():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"type": "AUTHENTICATION_REQUIRED", "message": "Invalid token"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = AirtableAdapter(token="pat_invalid", http_client=client)

    with pytest.raises(AirtableAuthError) as exc_info:
        await adapter.get_record("app1", "Tbl", "rec1")
    assert exc_info.value.status_code == 401
    assert "Invalid token" in str(exc_info.value)


@pytest.mark.asyncio
async def test_adapter_error_normalization_404():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "NOT_FOUND"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = AirtableAdapter(token="pat_test", http_client=client)

    with pytest.raises(AirtableNotFoundError) as exc_info:
        await adapter.get_record("app1", "Tbl", "rec_missing")
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_adapter_error_normalization_422():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"error": {"type": "INVALID_VALUE_FOR_COLUMN", "message": "Field mismatch"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = AirtableAdapter(token="pat_test", http_client=client)

    with pytest.raises(AirtableValidationError) as exc_info:
        await adapter.create_record("app1", "Tbl", CreateRecordRequest(fields={"A": 1}))
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_adapter_error_normalization_429():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"Retry-After": "25.0"},
            json={"error": {"message": "Too many requests"}},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    # Test di NORMALIZZAZIONE dell'errore (non di retry): retry disattivato per verificare
    # la mappatura immediata 429 -> AirtableRateLimitError (il retry è coperto dai test di resilienza).
    adapter = AirtableAdapter(token="pat_test", http_client=client, max_retries=0)

    with pytest.raises(AirtableRateLimitError) as exc_info:
        await adapter.get_record("app1", "Tbl", "rec1")
    assert exc_info.value.status_code == 429
    assert exc_info.value.retry_after == 25.0


@pytest.mark.asyncio
async def test_adapter_error_normalization_500():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = AirtableAdapter(token="pat_test", http_client=client, max_retries=0)

    with pytest.raises(AirtableServerError) as exc_info:
        await adapter.get_record("app1", "Tbl", "rec1")
    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_adapter_timeout_handling():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Read timed out")

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = AirtableAdapter(token="pat_test", http_client=client, max_retries=0)

    with pytest.raises(AirtableNetworkError) as exc_info:
        await adapter.get_record("app1", "Tbl", "rec1")
    assert "Timeout" in str(exc_info.value)


@pytest.mark.asyncio
async def test_adapter_error_normalization_monthly_quota_exhausted():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"error": {"message": "You have exceeded your monthly request limit on your plan"}},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = AirtableAdapter(token="pat_test", http_client=client, max_retries=0)

    with pytest.raises(AirtableQuotaExhaustedError) as exc_info:
        await adapter.get_record("app1", "Tbl", "rec1")
    assert exc_info.value.status_code == 429
    assert exc_info.value.requires_human_escalation is True
    assert exc_info.value.error_code == "airtable_quota_exhausted"


@pytest.mark.asyncio
async def test_adapter_get_base_schema_mocked():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert "/v0/meta/bases/appCRM/tables" in str(request.url)
        content = {
            "tables": [
                {
                    "id": "tblLeads",
                    "name": "Leads",
                    "primaryFieldId": "fld1",
                    "fields": [
                        {"id": "fld1", "name": "Nome", "type": "singleLineText"},
                        {"id": "fld2", "name": "Telefono", "type": "phoneNumber"},
                        {"id": "fld3", "name": "Note", "type": "multilineText"},
                    ],
                }
            ]
        }
        return httpx.Response(200, json=content)

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = AirtableAdapter(token="pat_test", http_client=client)

    tables = await adapter.get_base_schema("appCRM")
    assert len(tables) == 1
    assert tables[0].id == "tblLeads"
    assert tables[0].name == "Leads"
    assert len(tables[0].fields) == 3
    assert tables[0].fields[0].name == "Nome"


@pytest.mark.asyncio
async def test_adapter_validate_table_schema_success():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        content = {
            "tables": [
                {
                    "id": "tblLeads",
                    "name": "Leads",
                    "fields": [
                        {"id": "fld1", "name": "Nome", "type": "singleLineText"},
                        {"id": "fld2", "name": "Telefono", "type": "phoneNumber"},
                        {"id": "fld3", "name": "Note", "type": "multilineText"},
                    ],
                }
            ]
        }
        return httpx.Response(200, json=content)

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = AirtableAdapter(token="pat_test", http_client=client)

    # Verifica con nome tabella case-insensitive e tutti i campi presenti
    result = await adapter.validate_table_schema(
        base_id="appCRM",
        table_id_or_name="leads",
        required_fields=["Nome", "telefono"],
    )
    assert result.is_valid is True
    assert result.table_id == "tblLeads"
    assert result.table_name == "Leads"
    assert result.missing_fields == []
    assert "Note" in result.available_fields


@pytest.mark.asyncio
async def test_adapter_validate_table_schema_missing_fields():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        content = {
            "tables": [
                {
                    "id": "tblLeads",
                    "name": "Leads",
                    "fields": [
                        {"id": "fld1", "name": "Nome", "type": "singleLineText"},
                    ],
                }
            ]
        }
        return httpx.Response(200, json=content)

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = AirtableAdapter(token="pat_test", http_client=client)

    # Richiede "Telefono" che non esiste nella tabella
    result = await adapter.validate_table_schema(
        base_id="appCRM",
        table_id_or_name="Leads",
        required_fields=["Nome", "Telefono"],
    )
    assert result.is_valid is False
    assert result.missing_fields == ["Telefono"]
    assert "Telefono" in result.error_message


@pytest.mark.asyncio
async def test_adapter_validate_table_schema_table_not_found():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        content = {
            "tables": [
                {"id": "tbl1", "name": "Clienti", "fields": []}
            ]
        }
        return httpx.Response(200, json=content)

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = AirtableAdapter(token="pat_test", http_client=client)

    result = await adapter.validate_table_schema(
        base_id="appCRM",
        table_id_or_name="TabellaInesistente",
        required_fields=["Nome"],
    )
    assert result.is_valid is False
    assert "Tabella 'TabellaInesistente' non trovata" in result.error_message
    assert "'Clienti' (tbl1)" in result.error_message


@pytest.mark.asyncio
async def test_adapter_validate_table_schema_missing_scope():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "Insufficient permissions to read schema"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    adapter = AirtableAdapter(token="pat_test", http_client=client)

    result = await adapter.validate_table_schema(
        base_id="appCRM",
        table_id_or_name="Leads",
        required_fields=["Nome"],
    )
    assert result.is_valid is False
    assert "schema.bases:read" in result.error_message

