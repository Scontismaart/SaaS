import os
from unittest.mock import patch
import httpx
import pytest

API_KEY = "test-api-key-12345"
pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def set_env():
    os.environ["DATABASE_URL"] = ""
    os.environ["API_KEY_SERVICE"] = API_KEY


@pytest.fixture
async def async_client(repo, pg_pool, install_test_identity, sample_org):
    from src.api.main import app
    await pg_pool.execute(
        "UPDATE organizations SET subscription_status = 'active', plan = 'business' WHERE id = $1",
        sample_org["id"],
    )
    install_test_identity(app, API_KEY, default_org_id=sample_org["id"])
    app.state.repo = repo
    app.state.pool = pg_pool
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        try:
            yield c
        finally:
            app.dependency_overrides.clear()


def _headers(org_id):
    return {"X-API-Key": API_KEY, "X-Organization-Id": str(org_id)}


async def test_save_profile_syncs_rag_struttura(async_client, repo, sample_org):
    """Verifica che salvando il profilo con nuovi orari, il chunk RAG a Priorità 1 venga aggiornato/creato."""
    payload = {
        "verticale": "parrucchiere",
        "nome_attivita": "Salone Top Style",
        "orari": "Lun-Ven 09:00-19:00, Sabato 08:30-18:00",
        "descrizione": "Salone unisex all'avanguardia",
        "tono": "professionale_caloroso",
        "servizi": ["Taglio Uomo", "Colore"],
        "regole_escalation": ["Clienti arrabbiati", "Richieste sconti"],
        "lingue_supportate": ["it", "en"],
        "lingua_default": "it"
    }

    with patch("src.api.main.vettorizza", return_value=[[0.1] * 384]):
        resp = await async_client.post(
            "/api/onboarding/profilo",
            json=payload,
            headers=_headers(sample_org["id"])
        )
    assert resp.status_code == 200

    # Verifica che nei chunk attivi ci siano i nuovi orari con Priorità 1 (dati_struttura)
    chunks = await repo.list_all_active_chunks(sample_org["id"])
    orari_chunks = [c for c in chunks if "Lun-Ven 09:00-19:00" in c["content"]]
    assert len(orari_chunks) >= 1
    assert orari_chunks[0]["tipo"] == "dati_struttura"
