import os
import uuid
import pytest
import pytest_asyncio
import httpx

pytestmark = pytest.mark.usefixtures("reset_db")
from unittest.mock import MagicMock

API_KEY = "test-gdpr-api-key-12345"


@pytest.fixture(autouse=True)
def set_env():
    os.environ["DATABASE_URL"] = ""
    os.environ["API_KEY_SERVICE"] = API_KEY
    os.environ.pop("AIRTABLE_API_KEY", None)
    os.environ.pop("AIRTABLE_BASE_ID", None)
    os.environ.pop("SOFTR_WEBHOOK_URL", None)
    os.environ.pop("SOFTR_API_KEY", None)


@pytest.fixture
async def async_client(repo):
    from src.api.main import app
    app.state.repo = repo
    app.state.pool = MagicMock()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def org_id(pg_pool):
    oid = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'GDPR-Test')", oid)
    return oid


def _headers(org_id=None):
    h = {"X-API-Key": API_KEY}
    if org_id:
        h["X-Organization-Id"] = str(org_id)
    return h


# ── Task 7: DPA ────────────────────────────────────────────────

class TestDPA:
    async def test_dpa_endpoint_returns_html(self, async_client):
        resp = await async_client.get("/api/gdpr/dpa")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Data Processing Agreement" in resp.text

    async def test_dpa_endpoint_no_auth_required(self, async_client):
        resp = await async_client.get("/api/gdpr/dpa")
        assert resp.status_code == 200

    async def test_dpa_subprocessors_aligned_with_annex_b(self, async_client):
        resp = await async_client.get("/api/gdpr/dpa")
        assert resp.status_code == 200
        text = resp.text
        assert "Neon" not in text
        assert "Supabase" in text
        assert "Meta Platforms (WhatsApp Business API)" in text
        assert "OpenRouter / underlying LLM providers" in text
        assert "Google (Business Profile, Calendar)" in text
        assert "Stripe" in text
        assert "Sentry" in text
        assert "SMTP provider" in text
        assert "Airtable, Softr" in text

    async def test_dpa_retention_matches_real_policy(self, async_client):
        resp = await async_client.get("/api/gdpr/dpa")
        assert resp.status_code == 200
        text = resp.text
        assert "fixed for all tenants" in text
        assert "not yet configurable per tenant" in text
        assert "message_retention_days" not in text

    async def test_dpa_security_reflects_regex_redaction(self, async_client):
        resp = await async_client.get("/api/gdpr/dpa")
        assert resp.status_code == 200
        text = resp.text
        assert "whitelist" not in text
        assert "regex" in text

    async def test_dpa_has_breach_notification_and_no_placeholder_contact(self, async_client):
        resp = await async_client.get("/api/gdpr/dpa")
        assert resp.status_code == 200
        text = resp.text
        assert "48 hours" in text
        assert "dpo@example.com" not in text


# ── Task 8: Consent preference center ──────────────────────────

class TestConsentPrefs:
    async def test_get_consent_prefs_no_auth(self, async_client):
        resp = await async_client.get("/api/gdpr/consent-prefs")
        assert resp.status_code == 401

    async def test_get_consent_prefs_invalid_key(self, async_client):
        resp = await async_client.get("/api/gdpr/consent-prefs",
                                      headers={"X-API-Key": "invalid"})
        assert resp.status_code == 403

    async def test_get_consent_prefs_empty(self, async_client, org_id):
        resp = await async_client.get("/api/gdpr/consent-prefs",
                                      headers=_headers(org_id))
        assert resp.status_code == 200
        data = resp.json()
        assert data == []

    async def test_get_consent_prefs_with_contacts(self, async_client, org_id, repo):
        from src.whatsapp.repository import Repository as WRepo
        wrepo = WRepo(pool=repo.pool)
        contact = await wrepo.get_or_create_contact(org_id, "393401234567")
        await wrepo.record_consent_event(contact["id"], "opt_in", "manual_staff")
        resp = await async_client.get("/api/gdpr/consent-prefs",
                                      headers=_headers(org_id))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        entry = next(c for c in data if c["phone_number"] == "393401234567")
        assert entry["consent_status"] == "granted"

    async def test_put_consent_prefs_no_auth(self, async_client):
        resp = await async_client.put("/api/gdpr/consent-prefs",
                                      json={"phone_number": "393401234567", "consent_status": "withdrawn"})
        assert resp.status_code == 401

    async def test_put_consent_prefs_updates_contact(self, async_client, org_id, repo):
        from src.whatsapp.repository import Repository as WRepo
        wrepo = WRepo(pool=repo.pool)
        contact = await wrepo.get_or_create_contact(org_id, "393409876543")
        resp = await async_client.put("/api/gdpr/consent-prefs",
                                      json={"phone_number": "393409876543", "consent_status": "withdrawn"},
                                      headers=_headers(org_id))
        assert resp.status_code == 200
        status = await wrepo.get_contact_consent(contact["id"])
        assert status == "withdrawn"

    async def test_put_consent_prefs_invalid_status(self, async_client, org_id):
        resp = await async_client.put("/api/gdpr/consent-prefs",
                                      json={"phone_number": "393401234567", "consent_status": "invalid"},
                                      headers=_headers(org_id))
        assert resp.status_code == 422


# ── Task 9: Data rights (export + delete) ──────────────────────

class TestDataRights:
    async def test_export_no_auth(self, async_client):
        resp = await async_client.get("/api/gdpr/export")
        assert resp.status_code == 401

    async def test_export_returns_download_url(self, async_client, org_id, repo):
        from src.whatsapp.repository import Repository as WRepo
        wrepo = WRepo(pool=repo.pool)
        contact = await wrepo.get_or_create_contact(org_id, "393401111111")
        cvid = (await wrepo.get_or_create_conversation(org_id, contact["id"]))["id"]
        content = {"type": "text", "text": {"body": "Test"}}
        await wrepo.upsert_message(uuid.uuid4(), org_id, cvid, "wam_export_1",
                                   "outbound", "text", content, "Test", "sent")

        resp = await async_client.get("/api/gdpr/export", headers=_headers(org_id))
        assert resp.status_code == 200
        data = resp.json()
        assert "download_url" in data
        assert "expires_in_minutes" in data
        assert data["expires_in_minutes"] == 15

    async def test_download_with_valid_token(self, async_client, org_id, repo):
        from src.whatsapp.repository import Repository as WRepo
        wrepo = WRepo(pool=repo.pool)
        contact = await wrepo.get_or_create_contact(org_id, "393402222222")

        resp = await async_client.get("/api/gdpr/export", headers=_headers(org_id))
        assert resp.status_code == 200
        download_url = resp.json()["download_url"]

        download_resp = await async_client.get(download_url.replace("http://test", ""))
        assert download_resp.status_code == 200
        data = download_resp.json()
        assert data["organization_id"] == str(org_id)
        assert len(data["contacts"]) >= 1

    async def test_download_expired_token_returns_410(self, async_client, org_id, repo):
        from datetime import datetime, timezone
        await repo.save_export_token(
            "expired_test_token", org_id, {"test": True},
            datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        resp = await async_client.get("/api/gdpr/download/expired_test_token")
        assert resp.status_code == 410

    async def test_download_nonexistent_token_returns_404(self, async_client):
        resp = await async_client.get("/api/gdpr/download/nonexistent")
        assert resp.status_code == 404

    async def test_token_survives_restart(self, async_client, org_id, repo):
        """Il token vive nel DB, non in memoria: una nuova istanza repo
        (simula restart del processo) deve riuscire a consumarlo."""
        from datetime import datetime, timedelta, timezone
        await repo.save_export_token(
            "persist_token", org_id, {"pippo": 1},
            datetime.now(timezone.utc) + timedelta(minutes=15),
        )
        fresh_repo = type(repo)(pool=repo.pool)
        esito = await fresh_repo.consume_export_token("persist_token")
        assert esito is not None
        status, data = esito
        assert status == "ok"
        assert data == {"pippo": 1}

    async def test_download_token_is_one_shot(self, async_client, org_id, repo):
        """Il consumo e' atomico: il secondo download dello stesso token
        deve fallire (404), anche via una nuova istanza repo."""
        resp = await async_client.get("/api/gdpr/export", headers=_headers(org_id))
        assert resp.status_code == 200
        download_url = resp.json()["download_url"].replace("http://test", "")

        first = await async_client.get(download_url)
        assert first.status_code == 200

        second = await async_client.get(download_url)
        assert second.status_code == 404

    async def test_export_rate_limit(self, async_client, org_id, repo):
        """Rate limit sulla generazione token: oltre la soglia (default 5/ora)
        l'export risponde 429. Reset del contatore per isolare il test."""
        from src.core.gdpr import routes as gdpr_routes
        gdpr_routes._export_rate_windows.clear()
        statuses = []
        for _ in range(6):
            resp = await async_client.get("/api/gdpr/export", headers=_headers(org_id))
            statuses.append(resp.status_code)
        assert statuses[:5] == [200] * 5
        assert statuses[5] == 429

    async def test_delete_no_auth(self, async_client):
        resp = await async_client.post("/api/gdpr/delete")
        assert resp.status_code == 401

    async def test_delete_hard_deletes_org(self, async_client, org_id, repo):
        resp = await async_client.post("/api/gdpr/delete", headers=_headers(org_id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deleted"
        async with repo.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT id FROM organizations WHERE id = $1", org_id)
        assert row is None

    async def test_retention_policy_endpoint(self, async_client, org_id):
        resp = await async_client.get("/api/gdpr/retention-policy", headers=_headers(org_id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["retention_days"] == 60
        assert data["purge_after_days"] == 30


# ── DPA/ToS acceptance (migration 035) ────────────────────────

class TestDpaAcceptance:
    async def test_acceptance_status_no_auth(self, async_client):
        resp = await async_client.get("/api/gdpr/acceptance-status")
        assert resp.status_code == 401

    async def test_acceptance_status_not_accepted(self, async_client, org_id):
        resp = await async_client.get("/api/gdpr/acceptance-status",
                                      headers=_headers(org_id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["dpa_accepted"] is False
        assert data["tos_accepted"] is False
        assert data["needs_acceptance"] is True
        assert data["current_version"] == "2026-07"

    async def test_accept_sets_timestamp_and_version(self, async_client, org_id, repo):
        resp = await async_client.post("/api/gdpr/accept",
                                       json={"dpa": True, "tos": True},
                                       headers=_headers(org_id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["dpa_accepted"] is True
        assert data["dpa_version"] == "2026-07"
        row = await repo.get_dpa_acceptance(org_id)
        assert row["dpa_accepted_at"] is not None
        assert row["tos_accepted_at"] is not None

    async def test_status_after_accept(self, async_client, org_id):
        resp = await async_client.post("/api/gdpr/accept", json={},
                                       headers=_headers(org_id))
        assert resp.status_code == 200
        resp = await async_client.get("/api/gdpr/acceptance-status",
                                      headers=_headers(org_id))
        data = resp.json()
        assert data["dpa_accepted"] is True
        assert data["needs_acceptance"] is False

    async def test_428_gate_blocks_unaccepted_org(self, async_client, org_id):
        resp = await async_client.get(
            "/api/dashboard",
            headers={"Authorization": "Bearer dummy",
                     "X-Organization-Id": str(org_id)},
        )
        assert resp.status_code == 428
        assert resp.json()["dpa_required"] is True

    async def test_428_gate_bypass_when_accepted(self, async_client, org_id, repo, monkeypatch):
        monkeypatch.setenv("SUPABASE_URL", "")
        await repo.accept_dpa(org_id, "2026-07")
        resp = await async_client.get(
            "/api/dashboard",
            headers={"Authorization": "Bearer dummy",
                     "X-Organization-Id": str(org_id)},
        )
        # Il middleware passa; poi il handler fallisce la verifica JWT
        # (Bearer fittizio) con 403 — ma comunque NON 428.
        assert resp.status_code != 428

    async def test_428_gate_exempts_gdpr_paths(self, async_client, org_id, monkeypatch):
        monkeypatch.setenv("SUPABASE_URL", "")
        resp = await async_client.get(
            "/api/gdpr/acceptance-status",
            headers={"Authorization": "Bearer dummy",
                     "X-Organization-Id": str(org_id)},
        )
        # Arriva al handler (API key assente -> 401 da require_ruolo),
        # non viene bloccato dal gate 428.
        assert resp.status_code != 428
