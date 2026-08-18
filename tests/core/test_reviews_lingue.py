"""Multilingua (task 14): propagazione lingue org alle bozze recensioni.

Due path reali: POST /api/recensione (API) e fetch_reviews (sync Google).
In entrambi i casi la lingua dell'org (profilo onboarding) deve arrivare fino
al runner; senza profilo onboarding si passano i default, senza errori.
"""

import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.core import onboarding
from src.models.schemas import OnboardingProfileInput


pytestmark = pytest.mark.usefixtures("reset_db")

API_KEY = "test-reviews-lingue-api-key-12345"
ENCRYPTION_KEY = "Y2xvbmUtZmVybmV0LWtleS0zMi1ieXRlcy1sb25nISE="


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("API_KEY_SERVICE", API_KEY)
    monkeypatch.setenv("ENCRYPTION_KEY", ENCRYPTION_KEY)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-test.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret-test")
    monkeypatch.setenv("GOOGLE_REVIEWS_REDIRECT_URI", "http://test/api/reviews/google/oauth2callback")
    monkeypatch.setenv("FRONTEND_URL", "http://test/settings")


@pytest.fixture
async def async_client(repo, pg_pool):
    from src.api.main import app
    from src.core.reviews.google_service import GoogleBusinessService
    app.state.repo = repo
    app.state.pool = pg_pool
    service = GoogleBusinessService(repo=repo, encryption_key=ENCRYPTION_KEY)
    app.state.reviews_service = service
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, service


def _headers(org_id):
    return {
        "X-API-Key": API_KEY,
        "X-Organization-Id": str(org_id),
    }


def _profilo_onboarding(**overrides):
    data = {
        "verticale": "ristorante",
        "nome_attivita": "Trattoria Da Mario",
        "orari": "Lun-Dom 12-23",
        "tono": "caldo, diretto",
        "servizi": ["Pranzo", "Cena"],
        "regole_escalation": ["Allergie"],
    }
    data.update(overrides)
    return OnboardingProfileInput(**data)


class _FakeBozza:
    id = str(uuid.uuid4())
    stato = "bozza_generata"
    bozza_risposta = "Grazie per la recensione!"
    sentiment = "positiva"
    richiede_revisione_urgente = False
    motivo = ""
    categoria = "generico"


# ── /api/recensione ───────────────────────────────────────────

async def test_api_recensione_propaga_le_lingue_dell_org(async_client, repo, sample_org):
    client, _ = async_client
    await onboarding.save_profile(
        sample_org["id"],
        _profilo_onboarding(lingue_supportate=["it", "de"], lingua_default="de"),
        repo,
    )

    captured = {}

    def fake_genera(**kwargs):
        captured.update(kwargs)
        return _FakeBozza()

    with patch("src.api.main.genera_risposta_recensione", side_effect=fake_genera):
        resp = await client.post(
            "/api/recensione",
            json={"testo": "Ottimo servizio!"},
            headers=_headers(sample_org["id"]),
        )

    assert resp.status_code == 200
    assert captured["lingue_supportate"] == ["it", "de"]
    assert captured["lingua_default"] == "de"


async def test_api_recensione_senza_profilo_usa_default(async_client, repo, sample_org):
    client, _ = async_client
    captured = {}

    def fake_genera(**kwargs):
        captured.update(kwargs)
        return _FakeBozza()

    with patch("src.api.main.genera_risposta_recensione", side_effect=fake_genera):
        resp = await client.post(
            "/api/recensione",
            json={"testo": "Ottimo servizio!"},
            headers=_headers(sample_org["id"]),
        )

    assert resp.status_code == 200
    # org senza onboarding: nessuna lingua, i default li applica il runner
    assert captured["lingue_supportate"] is None
    assert captured["lingua_default"] is None


# ── Sync Google (fetch_reviews) ───────────────────────────────

async def _inserisci_credenziali(pg_pool, org_id):
    from src.core.reviews.google_service import GoogleBusinessService
    svc = GoogleBusinessService(repo=MagicMock(), encryption_key=ENCRYPTION_KEY)
    async with pg_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO google_business_credentials
               (organization_id, access_token, refresh_token, token_expiry,
                account_name, location_name)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            org_id,
            svc.encrypt_secret("access-token"),
            svc.encrypt_secret("refresh-token"),
            datetime.now(timezone.utc) + timedelta(hours=1),
            "accounts/123",
            "accounts/123/locations/456",
        )


async def test_sync_google_propaga_le_lingue_dell_org(async_client, pg_pool, sample_org, repo):
    client, service = async_client
    await _inserisci_credenziali(pg_pool, sample_org["id"])
    await onboarding.save_profile(
        sample_org["id"],
        _profilo_onboarding(lingue_supportate=["it", "en"], lingua_default="en"),
        repo,
    )

    service._build_service = AsyncMock(return_value=MagicMock())
    service._list_reviews = AsyncMock(
        return_value=[
            {
                "reviewId": "rev-1",
                "starRating": "FIVE",
                "reviewer": {"displayName": "Mario"},
                "comment": {"comment": "Great place!"},
            }
        ]
    )
    captured = {}
    service._genera_bozza = AsyncMock(
        side_effect=lambda *a, **kw: captured.update(kw) or _FakeBozza()
    )

    resp = await client.post("/api/reviews/google/sync", headers=_headers(sample_org["id"]))
    assert resp.status_code == 200
    assert resp.json() == {"nuove": 1}
    assert captured["lingue_supportate"] == ["it", "en"]
    assert captured["lingua_default"] == "en"


async def test_sync_google_senza_profilo_usa_default(async_client, pg_pool, sample_org):
    client, service = async_client
    await _inserisci_credenziali(pg_pool, sample_org["id"])

    service._build_service = AsyncMock(return_value=MagicMock())
    service._list_reviews = AsyncMock(
        return_value=[
            {
                "reviewId": "rev-1",
                "starRating": "FIVE",
                "reviewer": {"displayName": "Mario"},
                "comment": {"comment": "Great place!"},
            }
        ]
    )
    captured = {}
    service._genera_bozza = AsyncMock(
        side_effect=lambda *a, **kw: captured.update(kw) or _FakeBozza()
    )

    resp = await client.post("/api/reviews/google/sync", headers=_headers(sample_org["id"]))
    assert resp.status_code == 200
    # nessun profilo onboarding: None, il runner applica i default
    assert captured["lingue_supportate"] is None
    assert captured["lingua_default"] is None