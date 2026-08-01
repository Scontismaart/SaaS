import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from google_auth_oauthlib.flow import Flow

from src.core.auth.dependencies import require_ruolo, require_mfa
from src.core.reviews.google_service import GoogleBusinessService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reviews/google", tags=["reviews-google"])

SCOPES = ["https://www.googleapis.com/auth/business.manage"]
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
    redirect_uri = os.environ["GOOGLE_REVIEWS_REDIRECT_URI"]
    return Flow.from_client_config(
        _get_client_config(),
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )


def _get_service(request: Request) -> GoogleBusinessService:
    svc = getattr(request.app.state, "reviews_service", None)
    if svc is None:
        svc = GoogleBusinessService(
            repo=request.app.state.repo,
            encryption_key=os.getenv("ENCRYPTION_KEY", ""),
        )
        request.app.state.reviews_service = svc
    return svc


class GoogleReviewsSettingsInput(BaseModel):
    account_name: str | None = None
    location_name: str | None = None


@router.get("/auth")
async def google_reviews_auth(
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
async def google_reviews_oauth2callback(request: Request):
    state = request.query_params.get("state", "")
    code = request.query_params.get("code")
    error = request.query_params.get("error")

    if error:
        logger.warning("business=oauth_error error=%s", error)
        return RedirectResponse(url=f"{FRONTEND_REDIRECT}?reviews_google=error&reason={error}")

    if not state or ":" not in state:
        return RedirectResponse(url=f"{FRONTEND_REDIRECT}?reviews_google=error&reason=invalid_state")

    org_id, nonce = state.split(":", 1)
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM oauth_nonces WHERE nonce = $1 AND organization_id = $2",
            nonce, org_id,
        )
        if not row:
            logger.warning("business=nonce_not_found org_id=%s", org_id)
            return RedirectResponse(url=f"{FRONTEND_REDIRECT}?reviews_google=error&reason=invalid_nonce")

        created_at = row["created_at"]
        if created_at and datetime.now(timezone.utc) - created_at > timedelta(minutes=NONCE_TTL_MINUTES):
            await conn.execute("DELETE FROM oauth_nonces WHERE nonce = $1", nonce)
            logger.warning("business=nonce_expired org_id=%s", org_id)
            return RedirectResponse(url=f"{FRONTEND_REDIRECT}?reviews_google=error&reason=nonce_expired")

        await conn.execute("DELETE FROM oauth_nonces WHERE nonce = $1", nonce)

    if not code:
        return RedirectResponse(url=f"{FRONTEND_REDIRECT}?reviews_google=error&reason=missing_code")

    flow = _make_flow()
    await asyncio.to_thread(flow.fetch_token, code=code)
    creds = flow.credentials

    if not creds.refresh_token:
        logger.error("business=no_refresh_token org_id=%s", org_id)
        return RedirectResponse(
            url=f"{FRONTEND_REDIRECT}?reviews_google=error&reason=no_refresh_token"
        )

    service = _get_service(request)
    enc_access = service.encrypt_secret(creds.token)
    enc_refresh = service.encrypt_secret(creds.refresh_token)

    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO google_business_credentials
               (organization_id, access_token, refresh_token, token_expiry, updated_at)
               VALUES ($1, $2, $3, $4, NOW())
               ON CONFLICT (organization_id) DO UPDATE SET
                   access_token = EXCLUDED.access_token,
                   refresh_token = EXCLUDED.refresh_token,
                   token_expiry = EXCLUDED.token_expiry,
                   updated_at = NOW()""",
            org_id,
            enc_access,
            enc_refresh,
            creds.expiry,
        )

    logger.info("business=connected org_id=%s", org_id)
    return RedirectResponse(url=f"{FRONTEND_REDIRECT}?reviews_google=connected")


@router.get("/status")
async def google_reviews_status(
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager")),
):
    org_id = user.get("organization_id")
    if not org_id:
        raise HTTPException(400, "X-Organization-Id header required")
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM google_business_credentials WHERE organization_id = $1",
            org_id,
        )
    if not row:
        return {"connected": False}
    return {
        "connected": True,
        "account_name": row["account_name"],
        "location_name": row["location_name"],
        "last_sync_at": row["last_sync_at"],
    }


@router.post("/sync")
async def google_reviews_sync(
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager")),
):
    org_id = user.get("organization_id")
    if not org_id:
        raise HTTPException(400, "X-Organization-Id header required")
    service = _get_service(request)
    try:
        nuove = await service.fetch_reviews(org_id)
    except Exception as e:
        logger.exception("business=sync_fail org_id=%s", org_id)
        raise HTTPException(502, detail=f"Sync Google reviews fallito: {e}")
    return {"nuove": nuove}


@router.patch("/settings")
async def google_reviews_settings(
    body: GoogleReviewsSettingsInput,
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
    if body.account_name is not None:
        sets.append(f"account_name = ${idx}")
        vals.append(body.account_name)
        idx += 1
    if body.location_name is not None:
        sets.append(f"location_name = ${idx}")
        vals.append(body.location_name)
        idx += 1
    if not sets:
        raise HTTPException(400, "Nessun campo da aggiornare")
    sets.append("updated_at = NOW()")
    sql = f"UPDATE google_business_credentials SET {', '.join(sets)} WHERE organization_id = $1"
    async with pool.acquire() as conn:
        await conn.execute(sql, org_id, *vals)
    return {"detail": "Impostazioni Google Business aggiornate"}


@router.delete("/disconnect")
async def google_reviews_disconnect(
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
            "DELETE FROM google_business_credentials WHERE organization_id = $1",
            org_id,
        )
    logger.info("business=disconnected org_id=%s", org_id)
    return {"detail": "Google Business disconnesso"}
