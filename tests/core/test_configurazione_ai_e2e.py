import os
from unittest.mock import patch
import httpx
import pytest

from src.core.documenti.rag_context import recupera_contesto_documenti
from src.agents.responder_agent import crea_responder_agent

API_KEY = "test-api-key-12345"
pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("API_KEY_SERVICE", API_KEY)
    monkeypatch.setenv("MISTRAL_API_KEY", "mock-mistral-ci-key")


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


async def test_configurazione_ai_salvataggio_completo_e_rag_sync(async_client, repo, sample_org, other_org):
    """Verifica che:
    1. Il salvataggio del profilo da 'Configurazione AI' persista identità, tono, multilingua e regole.
    2. Gli orari di apertura vengano sincronizzati come chunk RAG a Priorità 1 (Dati struttura).
    3. Il prompt del responder rifletta il nuovo nome, settore e regole.
    4. Ci sia rigoroso isolamento multi-tenant (Org B non vede le impostazioni di Org A).
    """
    payload = {
        "verticale": "centro_estetico",
        "nome_attivita": "Oasi del Benessere SPA",
        "orari": "Mar-Sab: 10:00 - 20:00 (Lunedì e Domenica chiuso)",
        "descrizione": "Centro estetico e SPA specializzato in massaggi rilassanti e trattamenti viso anti-age.",
        "tono": "formale_elegante",
        "servizi": [],  # La nuova vista non usa la textarea di servizi grezzi
        "regole_escalation": [
            "Donne in gravidanza per trattamenti specifici",
            "Richieste pacchetti matrimonio personalizzati"
        ],
        "lingue_supportate": ["it", "en", "fr"],
        "lingua_default": "it"
    }

    with patch("src.api.main.vettorizza", return_value=[[0.1] * 384]):
        resp = await async_client.post(
            "/api/onboarding/profilo",
            json=payload,
            headers=_headers(sample_org["id"]),
        )
    assert resp.status_code == 200
    res_data = resp.json()["profilo"]
    assert res_data["nome_attivita"] == "Oasi del Benessere SPA"
    assert res_data["verticale"] == "centro_estetico"
    assert res_data["tono"] == "formale_elegante"
    assert len(res_data["regole_escalation"]) == 2

    # 1. Verifica sincronizzazione RAG Dati Struttura (Priorità 1)
    with patch("src.core.documenti.rag_context.vettorizza", return_value=[[0.1] * 384]):
        ctx = await recupera_contesto_documenti(str(sample_org["id"]), "quando siete aperti?", repo)
    assert "Mar-Sab: 10:00 - 20:00" in ctx.testo
    assert any(c["tipo"] == "dati_struttura" for c in ctx.chunks)

    # 2. Verifica prompt del responder per il verticale centro estetico
    bp = await repo.get_org_business_profile(sample_org["id"])
    from src.whatsapp.inbound_processor import _profile_from_dict
    profilo_obj = _profile_from_dict(bp)
    with patch("src.agents.responder_agent.crea_llm", return_value="openai/mock-model"):
        agent = crea_responder_agent(profilo_obj)
    backstory = agent.backstory

    assert "Oasi del Benessere SPA" in backstory
    assert "Centro Estetico" in backstory or "Estetico" in backstory
    assert "Donne in gravidanza" in backstory
    assert "Mar-Sab: 10:00 - 20:00" in backstory

    # 3. Verifica isolamento multi-tenant
    resp_other = await async_client.get(
        "/api/onboarding/profilo",
        headers=_headers(other_org["id"]),
    )
    assert resp_other.status_code == 200
    other_prof = resp_other.json().get("profilo") or {}
    assert other_prof.get("nome_attivita") != "Oasi del Benessere SPA"


async def test_bidirezionalita_orari_conoscenza_e_configurazione_ai(async_client, repo, sample_org):
    """Verifica che aggiornando gli orari da Dati struttura in Conoscenza,
    il business profile venga aggiornato e reso disponibile alla Configurazione AI."""
    with patch("src.api.main.vettorizza", return_value=[[0.1] * 384]):
        put_res = await async_client.put(
            "/api/conoscenza/dati-struttura",
            json={
                "servizi": [
                    {"nome": "Massaggio Relax", "prezzo": 60.0, "durata_minuti": 50, "operatore": "Sara"}
                ],
                "orari": "Tutti i giorni: 08:00 - 22:00"
            },
            headers=_headers(sample_org["id"]),
        )
    assert put_res.status_code == 200

    # Recupera il profilo tramite l'endpoint usato da Configurazione AI
    get_res = await async_client.get(
        "/api/onboarding/profilo",
        headers=_headers(sample_org["id"]),
    )
    assert get_res.status_code == 200
    prof = get_res.json()["profilo"]
    assert prof["orari"] == "Tutti i giorni: 08:00 - 22:00"
