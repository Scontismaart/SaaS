"""A3 — API di gestione recensioni (list/get/approva/analytics).

Il CRUD e la lock "FOR UPDATE" esistono gia' nel repository; qui si testa
che siano esposti via HTTP in modo multi-tenant sicuro (org scoping su ogni
endpoint) e che il flusso one-click di approvazione funzioni end-to-end.
"""
import os
import uuid

import pytest
import httpx
from unittest.mock import MagicMock

pytestmark = pytest.mark.usefixtures("reset_db")

API_KEY = "test-reviews-api-key-12345"


@pytest.fixture(autouse=True)
def set_env():
    os.environ["DATABASE_URL"] = ""
    os.environ["API_KEY_SERVICE"] = API_KEY


@pytest.fixture
async def async_client(repo):
    from src.api.main import app
    app.state.repo = repo
    app.state.pool = MagicMock()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _headers(org_id):
    return {
        "X-API-Key": API_KEY,
        "X-Organization-Id": str(org_id),
    }


async def _crea_recensione(repo, org_id, *, testo="Bella recensione",
                           stelle=5, fonte="google", autore="Mario",
                           stato="bozza_generata", bozza="Grazie del feedback!"):
    return await repo.create_review(
        organization_id=org_id,
        testo=testo,
        valutazione_stelle=stelle,
        fonte=fonte,
        autore=autore,
        bozza_risposta=bozza,
        stato=stato,
    )


# ── List ──────────────────────────────────────────────────────

async def test_list_recensioni_vuoto(async_client, repo, sample_org):
    resp = await async_client.get("/api/recensioni", headers=_headers(sample_org["id"]))
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data.get("recensioni"), list)
    assert data["recensioni"] == []


async def test_list_recensioni_con_filtro_stato(async_client, repo, sample_org):
    await _crea_recensione(repo, sample_org["id"], stato="bozza_generata")
    resp = await async_client.get(
        "/api/recensioni",
        params={"stato": "bozza_generata"},
        headers=_headers(sample_org["id"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["recensioni"]) == 1
    assert data["recensioni"][0]["stato"] == "bozza_generata"


async def test_list_recensioni_non_vede_altre_org(async_client, repo, sample_org, other_org):
    await _crea_recensione(repo, other_org["id"], testo="Recensione altrui")
    resp = await async_client.get("/api/recensioni", headers=_headers(sample_org["id"]))
    assert resp.status_code == 200
    assert resp.json()["recensioni"] == []


async def test_list_recensioni_richiede_auth(async_client):
    resp = await async_client.get("/api/recensioni")
    assert resp.status_code == 401


# ── Get singola ───────────────────────────────────────────────

async def test_get_recensione(async_client, repo, sample_org):
    r = await _crea_recensione(repo, sample_org["id"])
    resp = await async_client.get(f"/api/recensioni/{r['id']}", headers=_headers(sample_org["id"]))
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(r["id"])
    assert data["testo"] == "Bella recensione"


async def test_get_recensione_altra_org_404(async_client, repo, sample_org, other_org):
    r = await _crea_recensione(repo, other_org["id"])
    resp = await async_client.get(f"/api/recensioni/{r['id']}", headers=_headers(sample_org["id"]))
    assert resp.status_code == 404


async def test_get_recensione_inesistente_404(async_client, sample_org):
    resp = await async_client.get(
        f"/api/recensioni/{uuid.uuid4()}",
        headers=_headers(sample_org["id"]),
    )
    assert resp.status_code == 404


# ── Approva (one-click) ───────────────────────────────────────

async def test_approva_recensione(async_client, repo, sample_org):
    r = await _crea_recensione(repo, sample_org["id"], stato="bozza_generata")
    resp = await async_client.post(
        f"/api/recensioni/{r['id']}/approva",
        headers=_headers(sample_org["id"]),
    )
    assert resp.status_code == 200
    assert resp.json()["stato"] == "approvata"


async def test_approva_recensione_altra_org_404(async_client, repo, sample_org, other_org):
    r = await _crea_recensione(repo, other_org["id"])
    resp = await async_client.post(
        f"/api/recensioni/{r['id']}/approva",
        headers=_headers(sample_org["id"]),
    )
    assert resp.status_code == 404


async def test_approva_recensione_inesistente_404(async_client, sample_org):
    resp = await async_client.post(
        f"/api/recensioni/{uuid.uuid4()}/approva",
        headers=_headers(sample_org["id"]),
    )
    assert resp.status_code == 404


async def test_approva_recensione_idempotente_gia_pubblicata(async_client, repo, sample_org):
    r = await _crea_recensione(repo, sample_org["id"], stato="pubblicata")
    resp = await async_client.post(
        f"/api/recensioni/{r['id']}/approva",
        headers=_headers(sample_org["id"]),
    )
    assert resp.status_code == 200
    assert resp.json()["stato"] == "pubblicata"


# ── Analytics ─────────────────────────────────────────────────

async def test_recensioni_analytics(async_client, repo, sample_org):
    await _crea_recensione(repo, sample_org["id"], testo="Ottimo!", stelle=5, fonte="google")
    await _crea_recensione(repo, sample_org["id"], testo="Terribile", stelle=1,
                           fonte="tripadvisor", stato="bozza_generata")
    resp = await async_client.get("/api/recensioni/analytics", headers=_headers(sample_org["id"]))
    assert resp.status_code == 200
    data = resp.json()
    assert "sentiment_trend" in data
    assert "star_distribution" in data
    assert "source_distribution" in data
