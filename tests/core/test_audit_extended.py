"""Test suite per la copertura completa del registro di audit.

Verifica che tutte le azioni sensibili tracciate:
- prenotazione.creata_manualmente
- prenotazione.no_show
- prenotazione.completata
- inbox.ticket_claimed
- inbox.ticket_resolved
- account.password_cambiata
- account.email_cambiata
producano un record in audit_log recuperabile tramite GET /api/audit.
"""

import os
import uuid
import httpx
import pytest

from src.core.bookings.service import BookingService
from src.whatsapp.repository import Repository as WhatsAppRepository

API_KEY = "test-audit-api-key"

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("reset_db")]


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("API_KEY_SERVICE", API_KEY)
    monkeypatch.setenv("SUPABASE_URL", "https://myproj.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-test-key")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setenv("DEMO_MODE", "false")


@pytest.fixture
async def app_setup(repo, pg_pool):
    from src.api.main import app

    app.state.repo = repo
    app.state.pool = pg_pool
    app.state.booking_service = BookingService(repo=repo)
    app.state.wrepo = WhatsAppRepository(pool=pg_pool)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, app, repo, pg_pool

    app.dependency_overrides.clear()


async def _create_org_and_owner(pg_pool, email="owner@test.com"):
    org_id = uuid.uuid4()
    auth_user_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO organizations (id, name) VALUES ($1, 'Ristorante Audit')",
            org_id,
        )
        await conn.execute(
            "INSERT INTO auth.users (id, email) VALUES ($1, $2)",
            auth_user_id, email,
        )
        profile = await conn.fetchrow(
            "SELECT * FROM user_profiles WHERE auth_user_id = $1", auth_user_id
        )
        await conn.execute(
            "INSERT INTO organization_memberships (organization_id, user_id, ruolo) "
            "VALUES ($1, $2, 'owner')",
            org_id, profile["id"],
        )
    return org_id, profile["id"], auth_user_id, email


def _override_auth(app, org_id, user_id, auth_user_id, email="owner@test.com", ruolo="owner"):
    from src.core.auth.dependencies import get_organization_context

    async def fake_get_organization_context():
        return {
            "auth_user_id": str(auth_user_id),
            "organization_id": str(org_id),
            "ruolo": ruolo,
            "source": "jwt",
            "user_id": str(user_id),
            "email": email,
        }

    app.dependency_overrides[get_organization_context] = fake_get_organization_context


class TestAuditExtended:
    async def test_audit_prenotazione_creata_manualmente(self, app_setup):
        client, app, repo, pg_pool = app_setup
        org_id, user_id, auth_user_id, email = await _create_org_and_owner(pg_pool)
        _override_auth(app, org_id, user_id, auth_user_id, email)

        res = await client.post(
            "/api/bookings",
            json={
                "nome_cliente": "Mario Rossi",
                "telefono": "+393331234567",
                "data": "2026-09-15",
                "ora": "20:00",
                "coperti": 4,
                "note": "Tavolo all'aperto",
            },
        )
        assert res.status_code == 200
        booking_data = res.json()

        audit_res = await client.get("/api/audit")
        assert audit_res.status_code == 200
        eventi = audit_res.json()["eventi"]

        creata_ev = next((e for e in eventi if e["action"] == "prenotazione.creata_manualmente"), None)
        assert creata_ev is not None
        assert creata_ev["target_table"] == "bookings"
        assert creata_ev["target_id"] == str(booking_data["id"])
        assert creata_ev["details"]["cliente"] == "Mario Rossi"

    async def test_audit_prenotazione_no_show(self, app_setup):
        client, app, repo, pg_pool = app_setup
        org_id, user_id, auth_user_id, email = await _create_org_and_owner(pg_pool)
        _override_auth(app, org_id, user_id, auth_user_id, email)

        booking_id = uuid.uuid4()
        async with pg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO bookings (id, organization_id, nome_cliente, data, ora, coperti, stato)
                VALUES ($1, $2, 'Luca Bianchi', '2026-09-15', '20:00', 2, 'confermata')
                """,
                booking_id, org_id,
            )

        res = await client.post(f"/api/bookings/{booking_id}/mark-no-show")
        assert res.status_code == 200

        audit_res = await client.get("/api/audit")
        assert audit_res.status_code == 200
        eventi = audit_res.json()["eventi"]

        no_show_ev = next((e for e in eventi if e["action"] == "prenotazione.no_show"), None)
        assert no_show_ev is not None
        assert no_show_ev["target_table"] == "bookings"
        assert no_show_ev["target_id"] == str(booking_id)
        assert no_show_ev["details"]["stato"] == "no_show"

    async def test_audit_prenotazione_completata(self, app_setup):
        client, app, repo, pg_pool = app_setup
        org_id, user_id, auth_user_id, email = await _create_org_and_owner(pg_pool)
        _override_auth(app, org_id, user_id, auth_user_id, email)

        booking_id = uuid.uuid4()
        async with pg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO bookings (id, organization_id, nome_cliente, data, ora, coperti, stato)
                VALUES ($1, $2, 'Giulia Verdi', '2026-09-15', '20:00', 2, 'confermata')
                """,
                booking_id, org_id,
            )

        res = await client.post(f"/api/bookings/{booking_id}/mark-completed")
        assert res.status_code == 200

        audit_res = await client.get("/api/audit")
        assert audit_res.status_code == 200
        eventi = audit_res.json()["eventi"]

        completata_ev = next((e for e in eventi if e["action"] == "prenotazione.completata"), None)
        assert completata_ev is not None
        assert completata_ev["target_table"] == "bookings"
        assert completata_ev["target_id"] == str(booking_id)
        assert completata_ev["details"]["stato"] == "completata"

    async def test_audit_inbox_ticket_claimed_and_resolved(self, app_setup):
        client, app, repo, pg_pool = app_setup
        org_id, user_id, auth_user_id, email = await _create_org_and_owner(pg_pool)
        _override_auth(app, org_id, user_id, auth_user_id, email)

        conv_id = uuid.uuid4()
        contact_id = uuid.uuid4()
        async with pg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO contacts (id, organization_id, phone_number) VALUES ($1, $2, '+393339998877')",
                contact_id, org_id,
            )
            await conn.execute(
                """
                INSERT INTO conversations (id, organization_id, contact_id, ticket_status, version)
                VALUES ($1, $2, $3, 'PENDING_STAFF', 1)
                """,
                conv_id, org_id, contact_id,
            )

        # 1. Claim ticket
        res_claim = await client.post(f"/api/inbox/claim/{conv_id}", json={"expected_version": 1})
        assert res_claim.status_code == 200

        audit_res = await client.get("/api/audit")
        assert audit_res.status_code == 200
        eventi = audit_res.json()["eventi"]

        claimed_ev = next((e for e in eventi if e["action"] == "inbox.ticket_claimed"), None)
        assert claimed_ev is not None
        assert claimed_ev["target_table"] == "conversations"
        assert claimed_ev["target_id"] == str(conv_id)
        assert claimed_ev["details"]["assigned_to"] == str(user_id)

        # 2. Resolve ticket
        res_resolve = await client.post(f"/api/inbox/resolve/{conv_id}")
        assert res_resolve.status_code == 200

        audit_res2 = await client.get("/api/audit")
        eventi2 = audit_res2.json()["eventi"]

        resolved_ev = next((e for e in eventi2 if e["action"] == "inbox.ticket_resolved"), None)
        assert resolved_ev is not None
        assert resolved_ev["target_table"] == "conversations"
        assert resolved_ev["target_id"] == str(conv_id)
        assert resolved_ev["details"]["ticket_status"] == "RESOLVED"

    async def test_audit_account_password_and_email_cambiata(self, app_setup, monkeypatch):
        client, app, repo, pg_pool = app_setup
        org_id, user_id, auth_user_id, email = await _create_org_and_owner(pg_pool)
        _override_auth(app, org_id, user_id, auth_user_id, email)

        from unittest.mock import AsyncMock

        monkeypatch.setattr(
            "src.core.auth.dependencies.verify_supabase_jwt",
            AsyncMock(return_value={"sub": str(auth_user_id), "email": email}),
        )
        monkeypatch.setattr(repo, "get_auth_access_allowed", AsyncMock(return_value=True))

        from src.core.auth import routes

        async def _fake_update_user(token, payload):
            if "password" in payload:
                return {"id": str(auth_user_id), "email": email}
            if "email" in payload:
                return {"id": str(auth_user_id), "email": email, "new_email": payload["email"]}
            return {"id": str(auth_user_id), "email": email}

        monkeypatch.setattr(routes, "_supabase_update_user", _fake_update_user)

        async def _fake_get_user(token):
            return {"id": str(auth_user_id), "email": email}

        async def _fake_login(user_email, password):
            return {"access_token": "ok"}

        monkeypatch.setattr(routes, "_supabase_get_user", _fake_get_user)
        monkeypatch.setattr(routes.bff, "login", _fake_login)

        headers = {
            "Cookie": "wa_at=test-session-jwt; wa_csrf=csrf-test-token",
            "X-CSRF-Token": "csrf-test-token",
            "Origin": "http://test",
        }

        # 1. Cambio password
        res_pwd = await client.post(
            "/api/auth/password",
            json={"password": "SuperNuovaPass123!", "current_password": "CurrentPass123!"},
            headers=headers,
        )
        assert res_pwd.status_code == 200

        audit_res = await client.get("/api/audit")
        assert audit_res.status_code == 200
        eventi = audit_res.json()["eventi"]

        pwd_ev = next((e for e in eventi if e["action"] == "account.password_cambiata"), None)
        assert pwd_ev is not None
        assert pwd_ev["target_table"] == "user_profiles"
        assert pwd_ev["target_id"] == str(user_id)
        assert pwd_ev["details"]["email"] == email

        # 2. Cambio email
        res_email = await client.post(
            "/api/auth/email",
            json={"email": "nuovamail@test.com"},
            headers=headers,
        )
        assert res_email.status_code == 200

        audit_res2 = await client.get("/api/audit")
        eventi2 = audit_res2.json()["eventi"]

        email_ev = next((e for e in eventi2 if e["action"] == "account.email_cambiata"), None)
        assert email_ev is not None
        assert email_ev["target_table"] == "user_profiles"
        assert email_ev["target_id"] == str(user_id)
        assert email_ev["details"]["new_email"] == "nuovamail@test.com"
        assert email_ev["details"]["conferma_richiesta"] is True
