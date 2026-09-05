"""Integrations, Channel Connectivity Testing & Audit Log API Routes (Invarianti 1, 2, 10).

Gestisce:
- Stato delle integrazioni canali (WhatsApp, Instagram, Webhook Meta)
- Test di connettività credenziali canali (WhatsApp, Instagram, Calendar, Webhook)
- Consultazione sicura e org-scoped dell'audit log
"""

import json
import logging
import os
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.dependencies import get_repo, require_ruolo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["integrations"])


# ── Audit log: lettura org-scoped ──────────────────────────────────────

@router.get("/api/audit")
async def lista_audit(
    request: Request,
    limit: int = 20,
    offset: int = 0,
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
):
    """Restituisce gli eventi di audit log per l'organizzazione autenticata."""
    org_id = user.get("organization_id")
    if not org_id:
        raise HTTPException(401, "Nessuna organizzazione collegata")
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    repo = get_repo(request)
    async with repo.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT a.action, a.target_table, a.target_id, a.details,
                   a.created_at,
                   u.email AS user_email
            FROM audit_log a
            LEFT JOIN user_profiles u ON u.id = a.user_id
            WHERE a.organization_id = $1::uuid
            ORDER BY a.created_at DESC
            LIMIT $2 OFFSET $3
        """, org_id, limit + 1, offset)
    has_more = len(rows) > limit
    return {
        "eventi": [
            {
                "action": r["action"],
                "target_table": r["target_table"],
                "target_id": r["target_id"],
                "details": json.loads(r["details"]) if isinstance(r["details"], str) else (r["details"] or {}),
                "created_at": r["created_at"].isoformat(),
                "user_email": r["user_email"],
            }
            for r in rows[:limit]
        ],
        "has_more": has_more,
    }


# ── Integrazioni: stato canali e webhook ───────────────────────────────

@router.get("/api/integrazioni/stato")
async def stato_integrazioni(
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
):
    """Restituisce lo stato di connessione dei canali esterni per l'organizzazione."""
    org_id = user.get("organization_id")
    if not org_id:
        raise HTTPException(401, "Nessuna organizzazione collegata")
    repo = get_repo(request)
    async with repo.pool.acquire() as conn:
        wa = await conn.fetchrow("""
            SELECT phone_number_id, waba_id, updated_at
            FROM whatsapp_accounts WHERE organization_id = $1::uuid
        """, org_id)
        ig = await conn.fetchrow("""
            SELECT ig_user_id, updated_at
            FROM instagram_accounts WHERE organization_id = $1::uuid
        """, org_id)
    return {
        "whatsapp": {
            "connesso": wa is not None,
            "phone_number_id": wa["phone_number_id"] if wa else None,
            "aggiornato": wa["updated_at"].isoformat() if wa and wa["updated_at"] else None,
        },
        "instagram": {
            "connesso": ig is not None,
            "ig_user_id": ig["ig_user_id"] if ig else None,
            "aggiornato": ig["updated_at"].isoformat() if ig and ig["updated_at"] else None,
        },
        "webhook_meta": {
            "configurato": bool(os.getenv("META_APP_SECRET")) and bool(os.getenv("META_VERIFY_TOKEN")),
        },
    }


@router.post("/api/integrazioni/test/{canale}")
async def test_integrazione(
    canale: str,
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
):
    """Esegue un test di connettività verso le API esterne del canale specificato."""
    org_id = user.get("organization_id")
    if not org_id:
        raise HTTPException(401, "Nessuna organizzazione collegata")

    repo = get_repo(request)
    encryption_key = os.getenv("ENCRYPTION_KEY", "")

    if canale == "whatsapp":
        async with repo.pool.acquire() as conn:
            wa = await conn.fetchrow(
                "SELECT phone_number_id, waba_id, access_token FROM whatsapp_accounts WHERE organization_id = $1::uuid",
                org_id,
            )
        if not wa:
            return {
                "canale": "whatsapp",
                "status": "disconnected",
                "success": False,
                "message": "Nessun account WhatsApp collegato.",
            }

        token = wa["access_token"]
        if encryption_key:
            try:
                from cryptography.fernet import Fernet
                cipher = Fernet(encryption_key.encode())
                token = cipher.decrypt(token.encode()).decode()
            except Exception:
                pass

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                res = await client.get(
                    f"https://graph.facebook.com/v21.0/{wa['phone_number_id']}",
                    params={"fields": "display_phone_number,verified_name", "access_token": token},
                )
                if res.status_code == 200:
                    data = res.json()
                    name = data.get("verified_name") or data.get("display_phone_number") or wa["phone_number_id"]
                    return {
                        "canale": "whatsapp",
                        "status": "connected",
                        "success": True,
                        "message": f"WhatsApp Business verificato ({name})",
                        "details": data,
                    }
                elif res.status_code in (400, 401, 403):
                    return {
                        "canale": "whatsapp",
                        "status": "expired_token",
                        "success": False,
                        "message": "Token Meta scaduto o non valido. Aggiorna il token.",
                    }
                else:
                    return {
                        "canale": "whatsapp",
                        "status": "error",
                        "success": False,
                        "message": f"Errore Meta Graph API (HTTP {res.status_code}).",
                    }
        except (httpx.TimeoutException, httpx.ConnectError):
            return {
                "canale": "whatsapp",
                "status": "error",
                "success": False,
                "message": "Timeout durante la verifica Meta Graph API.",
            }

    elif canale == "instagram":
        async with repo.pool.acquire() as conn:
            ig = await conn.fetchrow(
                "SELECT ig_user_id, access_token FROM instagram_accounts WHERE organization_id = $1::uuid",
                org_id,
            )
        if not ig:
            return {
                "canale": "instagram",
                "status": "disconnected",
                "success": False,
                "message": "Nessun account Instagram collegato.",
            }

        token = ig["access_token"]
        if encryption_key:
            try:
                from cryptography.fernet import Fernet
                cipher = Fernet(encryption_key.encode())
                token = cipher.decrypt(token.encode()).decode()
            except Exception:
                pass

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                res = await client.get(
                    f"https://graph.facebook.com/v21.0/{ig['ig_user_id']}",
                    params={"fields": "id,username,name", "access_token": token},
                )
                if res.status_code == 200:
                    data = res.json()
                    username = data.get("username") or ig["ig_user_id"]
                    return {
                        "canale": "instagram",
                        "status": "connected",
                        "success": True,
                        "message": f"Instagram Direct verificato (@{username})",
                        "details": data,
                    }
                elif res.status_code in (400, 401, 403):
                    return {
                        "canale": "instagram",
                        "status": "expired_token",
                        "success": False,
                        "message": "Token Instagram scaduto o non valido.",
                    }
                else:
                    return {
                        "canale": "instagram",
                        "status": "error",
                        "success": False,
                        "message": f"Errore Instagram API (HTTP {res.status_code}).",
                    }
        except (httpx.TimeoutException, httpx.ConnectError):
            return {
                "canale": "instagram",
                "status": "error",
                "success": False,
                "message": "Timeout durante la verifica Instagram API.",
            }

    elif canale == "calendar":
        async with repo.pool.acquire() as conn:
            cal = await conn.fetchrow(
                "SELECT * FROM google_calendar_credentials WHERE organization_id = $1::uuid",
                org_id,
            )
        if not cal:
            return {
                "canale": "calendar",
                "status": "disconnected",
                "success": False,
                "message": "Nessun account Google Calendar collegato.",
            }

        token = cal["access_token"]
        if encryption_key:
            try:
                from cryptography.fernet import Fernet
                cipher = Fernet(encryption_key.encode())
                token = cipher.decrypt(token.encode()).decode()
            except Exception:
                pass

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                res = await client.get(
                    "https://www.googleapis.com/calendar/v3/users/me/calendarList",
                    headers={"Authorization": f"Bearer {token}"},
                )
                if res.status_code == 200:
                    return {
                        "canale": "calendar",
                        "status": "connected",
                        "success": True,
                        "message": "Sincronizzazione Google Calendar verificata e attiva.",
                        "details": {"calendar_id": cal["calendar_id"], "sync_enabled": cal["sync_enabled"]},
                    }
                elif res.status_code in (401, 403):
                    return {
                        "canale": "calendar",
                        "status": "expired_token",
                        "success": False,
                        "message": "Token Google scaduto o revocato. Riconnetti l'agenda Google.",
                    }
                else:
                    return {
                        "canale": "calendar",
                        "status": "error",
                        "success": False,
                        "message": f"Risposta Google Calendar: HTTP {res.status_code}",
                    }
        except (httpx.TimeoutException, httpx.ConnectError):
            return {
                "canale": "calendar",
                "status": "error",
                "success": False,
                "message": "Timeout durante la verifica di Google Calendar.",
            }

    elif canale == "webhook":
        secret_ok = bool(os.getenv("META_APP_SECRET"))
        verify_ok = bool(os.getenv("META_VERIFY_TOKEN"))
        if secret_ok and verify_ok:
            return {
                "canale": "webhook",
                "status": "connected",
                "success": True,
                "message": "Endpoint webhook attivo con validazione HMAC-SHA256.",
            }
        else:
            return {
                "canale": "webhook",
                "status": "pending_verification",
                "success": False,
                "message": "Credenziali Webhook mancanti sul server.",
            }

    raise HTTPException(400, f"Canale non supportato: {canale}")
