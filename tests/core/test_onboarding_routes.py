import os
import pytest
import httpx
import json
from unittest.mock import AsyncMock, patch

from src.models.schemas import RispostaOutput

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


PAYLOAD = {
    "verticale": "parrucchiere",
    "nome_attivita": "Studio Capelli Nora",
    "orari": "Mar-Sab 09:00-19:00",
    "tono": "gentile, pratico",
    "servizi": ["Taglio", "Colore"],
    "regole_escalation": ["Correzioni colore"],
    "whatsapp_collegato": False,
    "documenti_importati": False,
}


async def test_profilo_no_auth(async_client):
    resp = await async_client.post("/api/onboarding/profilo", json=PAYLOAD)
    assert resp.status_code == 401


async def test_verticali_con_auth(async_client, sample_org):
    r = await async_client.get("/api/onboarding/verticali", headers=_headers(sample_org["id"]))
    assert r.status_code == 200
    assert any(v["id"] == "ristorante" for v in r.json()["verticali"])


async def test_salva_e_leggi_profilo_org_scoped(async_client, sample_org, other_org):
    r = await async_client.post("/api/onboarding/profilo", json=PAYLOAD, headers=_headers(sample_org["id"]))
    assert r.status_code == 200
    assert r.json()["profilo"]["nome_attivita"] == "Studio Capelli Nora"
    assert r.json()["profilo"]["profilo"]["nome"] == "Studio Capelli Nora"

    mio = await async_client.get("/api/onboarding/profilo", headers=_headers(sample_org["id"]))
    assert mio.status_code == 200
    assert mio.json()["profilo"]["nome_attivita"] == "Studio Capelli Nora"

    # nessun leak cross-tenant: l'altra org non vede il profilo
    altro = await async_client.get("/api/onboarding/profilo", headers=_headers(other_org["id"]))
    assert altro.status_code == 200
    assert altro.json()["profilo"] is None


async def test_cross_tenant_non_sovrascrive(async_client, sample_org, other_org):
    await async_client.post(
        "/api/onboarding/profilo",
        json={**PAYLOAD, "nome_attivita": "Studio A"},
        headers=_headers(sample_org["id"]),
    )
    await async_client.post(
        "/api/onboarding/profilo",
        json={**PAYLOAD, "nome_attivita": "Studio B"},
        headers=_headers(other_org["id"]),
    )
    mio = await async_client.get("/api/onboarding/profilo", headers=_headers(sample_org["id"]))
    assert mio.json()["profilo"]["nome_attivita"] == "Studio A"


async def test_preview_org_scoped_e_usage_logged(async_client, repo, sample_org):
    risposta = RispostaOutput(
        risposta="Certo, per le 17 ci stiamo.",
        richiede_umano=False,
        motivo="",
        categoria="booking",
    )
    with patch("src.core.onboarding.vettorizza", return_value=[[0.1] * 384]), \
         patch("src.core.onboarding.genera_risposta_async", new=AsyncMock(return_value=risposta)) as mocked:
        r = await async_client.post("/api/onboarding/preview", json={
            "profilo": PAYLOAD,
            "messaggio": "Vorrei prenotare per le 17",
        }, headers=_headers(sample_org["id"]))
    assert r.status_code == 200
    assert r.json()["risposta"] == "Certo, per le 17 ci stiamo."
    mocked.assert_awaited_once()

    # la preview conta come uso AI (billing), org-scoped
    async with repo.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT metadata FROM usage_events WHERE organization_id = $1",
            sample_org["id"],
        )
    assert any(
        json.loads(r["metadata"]).get("task_type") == "onboarding_preview" for r in rows
    )