import logging
import os
import httpx
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.core.auth.dependencies import require_ruolo
from src.whatsapp.repository import Repository as WhatsAppRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp-settings"])


def _get_wrepo(request: Request) -> WhatsAppRepository:
    pool = request.app.state.pool
    if pool is None:
        raise HTTPException(500, "Database non disponibile")
    return WhatsAppRepository(pool=pool)


class WhatsAppAccountRequest(BaseModel):
    phone_number_id: str = Field(min_length=1, max_length=64, description="Phone Number ID da Meta Business Suite")
    waba_id: str = Field(min_length=1, max_length=64, description="WhatsApp Business Account ID")
    access_token: str = Field(min_length=1, description="System User Access Token di Meta")
    display_phone_number: Optional[str] = Field(default=None, max_length=32)


class WhatsAppTestMessageRequest(BaseModel):
    to_phone: Optional[str] = Field(default=None, max_length=32, description="Numero di telefono destinatario del test (es. +393401234567)")


@router.get("/settings")
@router.get("/account")
async def get_whatsapp_settings(
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
):
    """Restituisce lo stato dell'account WhatsApp collegato e la disponibilità del webhook."""
    org_id = user["organization_id"]
    wrepo = _get_wrepo(request)
    cfg = await wrepo.get_tenant_config(org_id)
    
    secret_ok = bool(os.getenv("META_APP_SECRET"))
    verify_ok = bool(os.getenv("META_VERIFY_TOKEN"))
    webhook_active = secret_ok and verify_ok

    if not cfg:
        return {
            "connesso": False,
            "status": "disconnected",
            "phone_number_id": None,
            "waba_id": None,
            "display_phone_number": None,
            "verified_name": None,
            "webhook_active": webhook_active,
            "message": "Nessun numero WhatsApp collegato.",
        }

    return {
        "connesso": True,
        "status": "connected",
        "phone_number_id": cfg["phone_number_id"],
        "waba_id": cfg.get("waba_id"),
        "display_phone_number": cfg["phone_number_id"],
        "webhook_active": webhook_active,
        "message": "Canale WhatsApp Business operativo.",
    }


@router.post("/connect")
@router.post("/account")
async def connect_whatsapp_account(
    body: WhatsAppAccountRequest,
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager")),
):
    """Collega il numero WhatsApp Business dell'attività verificando le credenziali su Meta."""
    org_id = user["organization_id"]
    wrepo = _get_wrepo(request)
    phone_number_id = body.phone_number_id.strip()
    waba_id = body.waba_id.strip()
    access_token = body.access_token.strip()

    # Verifica preliminare su Meta Graph API
    verified_name = None
    display_phone_number = body.display_phone_number
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(6.0)) as client:
            res = await client.get(
                f"https://graph.facebook.com/v21.0/{phone_number_id}",
                params={"fields": "display_phone_number,verified_name,code_verification_status", "access_token": access_token},
            )
            if res.status_code == 200:
                data = res.json()
                verified_name = data.get("verified_name")
                if data.get("display_phone_number"):
                    display_phone_number = data.get("display_phone_number")
            elif res.status_code in (400, 401, 403):
                err_data = res.json().get("error", {})
                err_msg = err_data.get("message", "Credenziali non valide su Meta.")
                raise HTTPException(
                    status_code=400,
                    detail=f"Verifica Meta non riuscita: {err_msg}. Controlla Phone Number ID e Token.",
                )
    except httpx.RequestError as e:
        logger.warning("meta_graph_verification_timeout error=%s", e)
        # In caso di timeout o offline di Meta, procediamo se il token ha un formato plausibile
        if len(access_token) < 20:
            raise HTTPException(status_code=400, detail="Il formato del token d'accesso non sembra valido.")

    try:
        await wrepo.save_tenant_config(org_id, phone_number_id, waba_id, access_token)
    except Exception as e:
        logger.error("whatsapp_save_failed error=%s org_id=%s", e, org_id)
        raise HTTPException(status_code=500, detail="Impossibile salvare la configurazione WhatsApp.")

    # Tentativo di sottoscrizione automatica WABA al webhook dell'app
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            await client.post(
                f"https://graph.facebook.com/v21.0/{waba_id}/subscribed_apps",
                params={"access_token": access_token},
            )
    except Exception as e:
        logger.warning("waba_subscribed_apps_warning error=%s", e)

    return {
        "ok": True,
        "status": "connected",
        "message": "WhatsApp Business collegato con successo!",
        "phone_number_id": phone_number_id,
        "waba_id": waba_id,
        "verified_name": verified_name,
        "display_phone_number": display_phone_number or phone_number_id,
    }


@router.post("/disconnect")
@router.delete("/account")
async def disconnect_whatsapp_account(
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager")),
):
    """Disconnette il numero WhatsApp Business dell'organizzazione."""
    org_id = user["organization_id"]
    wrepo = _get_wrepo(request)
    deleted = await wrepo.delete_tenant_config(org_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Nessun account WhatsApp collegato da disconnettere.")
    return {"ok": True, "deleted": True, "message": "Numero WhatsApp disconnesso con successo."}


@router.post("/send-test")
async def send_test_message(
    body: WhatsAppTestMessageRequest,
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
):
    """Invia un messaggio reale o verifica la capacità di invio su WhatsApp."""
    org_id = user["organization_id"]
    wrepo = _get_wrepo(request)
    cfg = await wrepo.get_tenant_config(org_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Nessun account WhatsApp collegato.")

    raw_token = cfg["access_token"]
    try:
        token = wrepo.decrypt_token(raw_token)
    except Exception:
        token = raw_token

    phone_number_id = cfg["phone_number_id"]
    to_phone = (body.to_phone or "").strip().replace(" ", "").replace("-", "")

    if to_phone:
        # Invio messaggio reale tramite Cloud API
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(6.0)) as client:
                res = await client.post(
                    f"https://graph.facebook.com/v21.0/{phone_number_id}/messages",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "messaging_product": "whatsapp",
                        "recipient_type": "individual",
                        "to": to_phone,
                        "type": "text",
                        "text": {
                            "body": "👋 Ciao! Questo è un messaggio di prova inviato da Melpis AI. Il tuo canale WhatsApp Business è configurato e operativo!"
                        },
                    },
                )
                if res.status_code == 200:
                    data = res.json()
                    msg_id = data.get("messages", [{}])[0].get("id", "ok")
                    return {
                        "success": True,
                        "status": "sent",
                        "message": f"Messaggio di test inviato con successo a {to_phone}!",
                        "message_id": msg_id,
                    }
                else:
                    err_info = res.json().get("error", {})
                    err_msg = err_info.get("message", f"Errore Meta HTTP {res.status_code}")
                    return {
                        "success": False,
                        "status": "error",
                        "message": f"Meta ha risposto: {err_msg}",
                        "details": err_info,
                    }
        except httpx.RequestError as e:
            return {
                "success": False,
                "status": "timeout",
                "message": f"Timeout durante l'invio a Meta: {e}",
            }
    else:
        # Verifica di raggiungibilità Graph API
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                res = await client.get(
                    f"https://graph.facebook.com/v21.0/{phone_number_id}",
                    params={"fields": "display_phone_number,verified_name", "access_token": token},
                )
                if res.status_code == 200:
                    d = res.json()
                    name = d.get("verified_name") or d.get("display_phone_number") or phone_number_id
                    return {
                        "success": True,
                        "status": "connected",
                        "message": f"Canale WhatsApp verificato e pronto ({name}).",
                    }
                else:
                    return {
                        "success": False,
                        "status": "error",
                        "message": f"Verifica Meta non riuscita (HTTP {res.status_code}).",
                    }
        except httpx.RequestError:
            return {
                "success": False,
                "status": "timeout",
                "message": "Impossibile contattare Meta Graph API.",
            }
