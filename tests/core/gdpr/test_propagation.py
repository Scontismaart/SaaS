import os
import pytest
import pytest_asyncio
import httpx


@pytest.fixture(autouse=True)
def _clean_env():
    keys = ["AIRTABLE_API_KEY", "AIRTABLE_BASE_ID", "SOFTR_WEBHOOK_URL", "SOFTR_API_KEY"]
    saved = {k: os.environ.pop(k, None) for k in keys}
    yield
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v


@pytest.mark.asyncio
async def test_propagate_delete_airtable_missing_config():
    from src.core.gdpr.propagation import propagate_delete_to_airtable
    result = await propagate_delete_to_airtable("org_123")
    assert result is False


@pytest.mark.asyncio
async def test_propagate_delete_softr_missing_config():
    from src.core.gdpr.propagation import propagate_delete_to_softr
    result = await propagate_delete_to_softr("org_123")
    assert result is False


@pytest.mark.asyncio
async def test_propagate_delete_airtable_success(respx_mock):
    from src.core.gdpr.propagation import propagate_delete_to_airtable
    os.environ["AIRTABLE_API_KEY"] = "test_key"
    os.environ["AIRTABLE_BASE_ID"] = "test_base"
    respx_mock.delete("https://api.airtable.com/v0/test_base/organizations/org_123").respond(200)
    result = await propagate_delete_to_airtable("org_123")
    assert result is True


@pytest.mark.asyncio
async def test_propagate_delete_softr_success(respx_mock):
    from src.core.gdpr.propagation import propagate_delete_to_softr
    os.environ["SOFTR_WEBHOOK_URL"] = "https://hooks.softr.app/delete"
    respx_mock.post("https://hooks.softr.app/delete").respond(200)
    result = await propagate_delete_to_softr("org_123")
    assert result is True


@pytest.mark.asyncio
async def test_propagate_hard_delete_calls_both(respx_mock):
    from src.core.gdpr.propagation import propagate_hard_delete
    os.environ["AIRTABLE_API_KEY"] = "test_key"
    os.environ["AIRTABLE_BASE_ID"] = "test_base"
    os.environ["SOFTR_WEBHOOK_URL"] = "https://hooks.softr.app/delete"
    respx_mock.delete("https://api.airtable.com/v0/test_base/organizations/org_123").respond(200)
    respx_mock.post("https://hooks.softr.app/delete").respond(200)
    results = await propagate_hard_delete("org_123")
    assert results == {"airtable": True, "softr": True}
