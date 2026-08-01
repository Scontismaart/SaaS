import os
import uuid
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from google_auth_oauthlib.flow import Flow

from src.core.auth.dependencies import require_ruolo, require_mfa

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/calendar", tags=["calendar"])

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
NONCE_TTL_MINUTES = 10
FRONTEND_REDIRECT = os.getenv("FRONTEND_URL", "/settings")


def _get_client_config():
    return {
        "web": {
            "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def _make_flow():
    redirect_uri = os.environ["GOOGLE_REDIRECT_URI"]
    return Flow.from_client_config(
        _get_client_config(),
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )


class CalendarSettingsInput(BaseModel):
    sync_enabled: bool | None = None
    calendar_id: str | None = None


@router.get("/auth")
async def calendar_auth(
    request: Request,
    user: dict = Depends(require_ruolo("owner")),
    mfa: dict = Depends(require_mfa()),
):
    org_id = user.get("organization_id")
    if not org_id:
        raise HTTPException(400, "X-Organization-Id header required")

    nonce = uuid.uuid4().hex
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO oauth_nonces (nonce, organization_id, created_at) VALUES ($1, $2, NOW())",
            nonce, org_id,
        )

    flow = _make_flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=f"{org_id}:{nonce}",
    )
    return RedirectResponse(url=auth_url)


@router.get("/oauth2callback")
async def calendar_oauth2callback(request: Request):
    state = request.query_params.get("state", "")
    code = request.query_params.get("code")
    error = request.query_params.get("error")

    if error:
        logger.warning("calendar=oauth_error error=%s", error)
        return RedirectResponse(url=f"{FRONTEND_REDIRECT}?calendar=error&reason={error}")

    if not state or ":" not in state:
        return RedirectResponse(url=f"{FRONTEND_REDIRECT}?calendar=error&reason=invalid_state")

    org_id, nonce = state.split(":", 1)
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM oauth_nonces WHERE nonce = $1 AND organization_id = $2",
            nonce, org_id,
        )
        if not row:
            logger.warning("calendar=nonce_not_found org_id=%s nonce=%s", org_id, nonce)
            return RedirectResponse(url=f"{FRONTEND_REDIRECT}?calendar=error&reason=invalid_nonce")

        created_at = row["created_at"]
        if created_at and datetime.now(timezone.utc) - created_at > timedelta(minutes=NONCE_TTL_MINUTES):
            await conn.execute("DELETE FROM oauth_nonces WHERE nonce = $1", nonce)
            logger.warning("calendar=nonce_expired org_id=%s", org_id)
            return RedirectResponse(url=f"{FRONTEND_REDIRECT}?calendar=error&reason=nonce_expired")

        await conn.execute("DELETE FROM oauth_nonces WHERE nonce = $1", nonce)

    if not code:
        return RedirectResponse(url=f"{FRONTEND_REDIRECT}?calendar=error&reason=missing_code")

    flow = _make_flow()
    # fetch_token e' una chiamata di rete sincrona bloccante: offload su
    # thread per non freeze-are l'event loop FastAPI.
    import asyncio as _asyncio
    await _asyncio.to_thread(flow.fetch_token, code=code)
    creds = flow.credentials

    # Google non rilascia refresh_token se la app e' in stato "Testing"
    # in Google Cloud Console e l'utente non e' un test user (o se non si
    # usa prompt=consent — che qui forziamo in /auth). Senza refresh_token
    # il sync e' inservibile: rifiuta subito invece di salvare credenziali
    # mute che crasheranno al primo refresh.
    if not creds.refresh_token:
        logger.error("calendar=no_refresh_token org_id=%s", org_id)
        return RedirectResponse(
            url=f"{FRONTEND_REDIRECT}?calendar=error&reason=no_refresh_token"
        )

    # Cifra i token con la stessa Fernet del service. Il DB NON salva mai
    # token in chiaro: _get_credentials assume formato Fernet, quindi ogni
    # scrittura DEVE passare da qui.
    calendar_service = getattr(request.app.state, "calendar_service", None)
    if calendar_service is None:
        logger.error("calendar=service_unavailable org_id=%s", org_id)
        return RedirectResponse(url=f"{FRONTEND_REDIRECT}?calendar=error&reason=server_error")

    enc_access = calendar_service.encrypt_secret(creds.token)
    enc_refresh = calendar_service.encrypt_secret(creds.refresh_token)

    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO google_calendar_credentials
               (organization_id, access_token, refresh_token, token_expiry, updated_at)
               VALUES ($1, $2, $3, $4, NOW())
               ON CONFLICT (organization_id) DO UPDATE SET
                   access_token = EXCLUDED.access_token,
                   refresh_token = EXCLUDED.refresh_token,
                   token_expiry = EXCLUDED.token_expiry,
                   sync_enabled = true,
                   updated_at = NOW()""",
            org_id,
            enc_access,
            enc_refresh,
            creds.expiry,
        )

    logger.info("calendar=connected org_id=%s", org_id)
    return RedirectResponse(url=f"{FRONTEND_REDIRECT}?calendar=connected")


@router.get("/status")
async def calendar_status(
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager")),
):
    org_id = user.get("organization_id")
    if not org_id:
        raise HTTPException(400, "X-Organization-Id header required")
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM google_calendar_credentials WHERE organization_id = $1",
            org_id,
        )
    if not row:
        return {"connected": False}
    return {
        "connected": True,
        "calendar_id": row["calendar_id"],
        "sync_enabled": row["sync_enabled"],
        "last_sync_at": row["last_sync_at"],
    }


@router.delete("/disconnect")
async def calendar_disconnect(
    request: Request,
    user: dict = Depends(require_ruolo("owner")),
    mfa: dict = Depends(require_mfa()),
):
    org_id = user.get("organization_id")
    if not org_id:
        raise HTTPException(400, "X-Organization-Id header required")
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM google_calendar_credentials WHERE organization_id = $1",
            org_id,
        )
        await conn.execute(
            "UPDATE bookings SET google_event_id = NULL WHERE organization_id = $1",
            org_id,
        )
    logger.info("calendar=disconnected org_id=%s", org_id)
    return {"detail": "Google Calendar disconnesso"}


@router.patch("/settings")
async def calendar_settings(
    body: CalendarSettingsInput,
    request: Request,
    user: dict = Depends(require_ruolo("owner")),
    mfa: dict = Depends(require_mfa()),
):
    org_id = user.get("organization_id")
    if not org_id:
        raise HTTPException(400, "X-Organization-Id header required")
    pool = request.app.state.pool
    sets = []
    vals = []
    idx = 2
    if body.sync_enabled is not None:
        sets.append(f"sync_enabled = ${idx}")
        vals.append(body.sync_enabled)
        idx += 1
    if body.calendar_id is not None:
        sets.append(f"calendar_id = ${idx}")
        vals.append(body.calendar_id)
        idx += 1
    if not sets:
        raise HTTPException(400, "Nessun campo da aggiornare")
    sets.append("updated_at = NOW()")
    sql = f"UPDATE google_calendar_credentials SET {', '.join(sets)} WHERE organization_id = $1"
    async with pool.acquire() as conn:
        await conn.execute(sql, org_id, *vals)
    return {"detail": "Impostazioni calendario aggiornate"}
