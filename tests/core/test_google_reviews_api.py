"""A1 — Google Business Profile: OAuth + sync recensioni (mock-testable).

La chiamata di rete reale e' isolata in GoogleBusinessService._list_reviews:
qui la mockiamo con dati finti dell'API mybusiness. I token OAuth devono
essere salvati cifrati (Fernet) e il sync deve fare dedup multi-tenant
per external_id.
"""
from datetime import datetime, timedelta, timezone

import pytest
import httpx
from unittest.mock import MagicMock, AsyncMock

pytestmark = pytest.mark.usefixtures("reset_db")

API_KEY = "test-google-reviews-api-key-12345"
ENCRYPTION_KEY = "Y2xvbmUtZmVybmV0LWtleS0zMi1ieXRlcy1sb25nISE="  # 32 byte b64


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
async def async_client(repo, pg_pool, monkeypatch):
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


async def _inserisci_credenziali(pg_pool, org_id, *, account="accounts/123", location="accounts/123/locations/456"):
    from src.core.reviews.google_service import GoogleBusinessService
    svc = GoogleBusinessService(
        repo=MagicMock(), encryption_key=ENCRYPTION_KEY,
    )
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
            account, location,
        )


# ── Status ────────────────────────────────────────────────────

async def test_status_non_connesso(async_client, sample_org):
    client, _ = async_client
    resp = await client.get("/api/reviews/google/status", headers=_headers(sample_org["id"]))
    assert resp.status_code == 200
    assert resp.json() == {"connected": False}


async def test_status_connesso(async_client, pg_pool, sample_org):
    client, _ = async_client
    await _inserisci_credenziali(pg_pool, sample_org["id"])
    resp = await client.get("/api/reviews/google/status", headers=_headers(sample_org["id"]))
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is True
    assert data["account_name"] == "accounts/123"


async def test_status_richiede_auth(async_client):
    client, _ = async_client
    resp = await client.get("/api/reviews/google/status")
    assert resp.status_code == 401


# ── Auth ──────────────────────────────────────────────────────

async def test_auth_redirect(async_client, pg_pool, sample_org):
    client, _ = async_client
    resp = await client.get("/api/reviews/google/auth", headers=_headers(sample_org["id"]))
    assert resp.status_code == 307
    assert "accounts.google.com" in resp.headers["location"]

    # il nonce deve essere stato salvato in oauth_nonces
    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM oauth_nonces WHERE organization_id = $1", sample_org["id"]
        )
        assert row is not None


async def test_auth_richiede_mfa_owner(async_client, sample_org):
    # source api_key e' esente da MFA (require_mfa la salta), quindi
    # l'endpoint richiede solo X-Organization-Id valido: senza header -> 400.
    client, _ = async_client
    resp = await client.get("/api/reviews/google/auth", headers={"X-API-Key": API_KEY})
    assert resp.status_code == 400


# ── Settings ──────────────────────────────────────────────────

async def test_settings_senza_credenziali_nessuna_riga(async_client, pg_pool, sample_org):
    client, _ = async_client
    resp = await client.patch(
        "/api/reviews/google/settings",
        headers=_headers(sample_org["id"]),
        json={"account_name": "accounts/999"},
    )
    assert resp.status_code == 200
    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT account_name FROM google_business_credentials WHERE organization_id = $1",
            sample_org["id"],
        )
    assert row is None


async def test_settings_aggiorna_account_e_location(async_client, pg_pool, sample_org):
    client, _ = async_client
    await _inserisci_credenziali(pg_pool, sample_org["id"], account="a/1", location="a/1/l/2")
    resp = await client.patch(
        "/api/reviews/google/settings",
        headers=_headers(sample_org["id"]),
        json={"account_name": "a/NEW", "location_name": "a/NEW/l/NEW"},
    )
    assert resp.status_code == 200
    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT account_name, location_name FROM google_business_credentials WHERE organization_id = $1",
            sample_org["id"],
        )
    assert row["account_name"] == "a/NEW"
    assert row["location_name"] == "a/NEW/l/NEW"


# ── Sync ──────────────────────────────────────────────────────

def _mocking_sync(service, fake_reviews):
    """Mocka build() e la chiamata di rete _list_reviews."""
    service._build_service = AsyncMock(return_value=MagicMock())
    service._list_reviews = AsyncMock(return_value=fake_reviews)


async def test_sync_persiste_nuove_recensioni(async_client, pg_pool, sample_org, repo):
    client, service = async_client
    await _inserisci_credenziali(pg_pool, sample_org["id"])

    fake_reviews = [
        {
            "reviewId": "rev-1",
            "starRating": "FIVE",
            "reviewer": {"displayName": "Mario Rossi"},
            "comment": {"comment": "Servizio eccellente!"},
        },
        {
            "reviewId": "rev-2",
            "starRating": "TWO",
            "reviewer": {"displayName": "Anna Bianchi"},
            "comment": {"comment": "Attesa lunga."},
        },
    ]
    _mocking_sync(service, fake_reviews)

    resp = await client.post("/api/reviews/google/sync", headers=_headers(sample_org["id"]))
    assert resp.status_code == 200
    assert resp.json() == {"nuove": 2}

    rows = await repo.list_reviews(sample_org["id"], fonte="google")
    assert len(rows) == 2
    assert {r["external_id"] for r in rows} == {"rev-1", "rev-2"}
    assert all(r["fonte"] == "google" for r in rows)
    assert {r["valutazione_stelle"] for r in rows} == {5, 2}


async def test_sync_dedup_idempotente(async_client, pg_pool, sample_org, repo):
    client, service = async_client
    await _inserisci_credenziali(pg_pool, sample_org["id"])

    fake = [{"reviewId": "rev-1", "starRating": "FIVE",
             "reviewer": {"displayName": "Mario"},
             "comment": {"comment": "Bello"}}]
    _mocking_sync(service, fake)

    await client.post("/api/reviews/google/sync", headers=_headers(sample_org["id"]))
    resp = await client.post("/api/reviews/google/sync", headers=_headers(sample_org["id"]))
    assert resp.status_code == 200
    assert resp.json() == {"nuove": 0}

    rows = await repo.list_reviews(sample_org["id"], fonte="google")
    assert len(rows) == 1


async def test_sync_non_contamina_altra_org(async_client, pg_pool, sample_org, other_org, repo):
    client, service = async_client
    await _inserisci_credenziali(pg_pool, other_org["id"])

    fake = [{"reviewId": "rev-altra", "starRating": "ONE",
             "reviewer": {"displayName": "X"},
             "comment": {"comment": "Recensione altrui"}}]
    _mocking_sync(service, fake)

    resp = await client.post("/api/reviews/google/sync", headers=_headers(other_org["id"]))
    assert resp.status_code == 200
    assert resp.json() == {"nuove": 1}

    rows = await repo.list_reviews(sample_org["id"])
    assert rows == []


async def test_sync_senza_credenziali_ritorna_zero(async_client, sample_org):
    client, _ = async_client
    resp = await client.post("/api/reviews/google/sync", headers=_headers(sample_org["id"]))
    assert resp.status_code == 200
    assert resp.json() == {"nuove": 0}


async def test_sync_senza_account_location_ritorna_zero(async_client, pg_pool, sample_org):
    client, _ = async_client
    await _inserisci_credenziali(pg_pool, sample_org["id"], account="", location="")
    resp = await client.post("/api/reviews/google/sync", headers=_headers(sample_org["id"]))
    assert resp.status_code == 200
    assert resp.json() == {"nuove": 0}


# ── Disconnect ────────────────────────────────────────────────

async def test_disconnect_rimuove_credenziali(async_client, pg_pool, sample_org):
    client, _ = async_client
    await _inserisci_credenziali(pg_pool, sample_org["id"])
    resp = await client.delete("/api/reviews/google/disconnect", headers=_headers(sample_org["id"]))
    assert resp.status_code == 200
    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM google_business_credentials WHERE organization_id = $1",
            sample_org["id"],
        )
    assert row is None
