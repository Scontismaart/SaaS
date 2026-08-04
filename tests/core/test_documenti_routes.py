import os
import pytest
import httpx
from unittest.mock import patch

API_KEY = "test-api-key-12345"

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def set_env():
    os.environ["DATABASE_URL"] = ""
    os.environ["API_KEY_SERVICE"] = API_KEY


@pytest.fixture
async def async_client(repo, pg_pool):
    from src.api.main import app
    app.state.repo = repo
    app.state.pool = pg_pool
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _headers(org_id):
    return {"X-API-Key": API_KEY, "X-Organization-Id": str(org_id)}


class _FakeLLM:
    def call(self, prompt):
        return "La pizza margherita costa 8 euro."


async def test_chiedi_no_auth(async_client):
    resp = await async_client.post("/api/documenti/chiedi", json={"domanda": "quanto costa?"})
    assert resp.status_code == 401


async def test_carica_e_chiedi_org_scoped(async_client, sample_org, other_org):
    with patch("src.api.main.vettorizza", return_value=[[0.1] * 384]):
        resp = await async_client.post("/api/documenti/carica", json={
            "testo": "Pizza margherita: 8 euro. Pizza diavola: 9 euro.",
            "nome": "menu.pdf",
        }, headers=_headers(sample_org["id"]))
    assert resp.status_code == 200
    doc_id = resp.json()["id"]

    elenco = await async_client.get("/api/documenti/elenco", headers=_headers(sample_org["id"]))
    assert elenco.status_code == 200
    assert any(d["id"] == doc_id for d in elenco.json()["documenti"])
    altra = await async_client.get("/api/documenti/elenco", headers=_headers(other_org["id"]))
    assert altra.status_code == 200
    assert all(d["id"] != doc_id for d in altra.json()["documenti"])

    with patch("src.core.documenti.qa_agent.vettorizza", return_value=[[0.1] * 384]), \
         patch("src.core.documenti.qa_agent.crea_llm", return_value=_FakeLLM()):
        r = await async_client.post("/api/documenti/chiedi", json={"domanda": "quanto costa la pizza?"},
                                    headers=_headers(sample_org["id"]))
    assert r.status_code == 200
    assert r.json()["risposta"] == "La pizza margherita costa 8 euro."


async def test_delete_cross_tenant_non_tocca_org_altrui(async_client, sample_org, other_org):
    with patch("src.api.main.vettorizza", return_value=[[0.1] * 384]):
        resp = await async_client.post("/api/documenti/carica", json={
            "testo": "Documento segreto dell'org A",
            "nome": "segreti.txt",
        }, headers=_headers(sample_org["id"]))
    assert resp.status_code == 200
    doc_id = resp.json()["id"]

    resp_b = await async_client.delete(f"/api/documenti/{doc_id}", headers=_headers(other_org["id"]))
    assert resp_b.status_code == 404

    resp_a = await async_client.delete(f"/api/documenti/{doc_id}", headers=_headers(sample_org["id"]))
    assert resp_a.status_code == 200


async def test_carica_file_org_scoped(async_client, sample_org, other_org):
    with patch("src.api.main.vettorizza", return_value=[[0.1] * 384]):
        resp = await async_client.post(
            "/api/documenti/carica-file",
            files={"file": ("menu.txt", b"Antipasto della casa: 12 euro", "text/plain")},
            headers=_headers(sample_org["id"]),
        )
    assert resp.status_code == 200
    doc_id = resp.json()["id"]
    altra = await async_client.get("/api/documenti/elenco", headers=_headers(other_org["id"]))
    assert all(d["id"] != doc_id for d in altra.json()["documenti"])
