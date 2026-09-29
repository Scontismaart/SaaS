"""Airtable Integration API Routes (Invarianti 1, 2, 5, 9, 10).

Gestisce:
- Connessione e verifica preventiva PAT Airtable (POST /api/v1/integrations/airtable/connect)
- Stato delle connessioni per il tenant (GET /api/v1/integrations/airtable/status)
- Validazione preventiva dello schema tabella/campi (POST /api/v1/integrations/airtable/validate-schema)
- Disconnessione e revoca (DELETE /api/v1/integrations/airtable)
"""
from __future__ import annotations

import logging
from typing import Any
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from src.core.auth.dependencies import require_mfa

from src.api.dependencies import (
    get_airtable_service,
    get_airtable_webhook_service,
    require_ruolo,
)
from src.integrations.airtable.errors import (
    AirtableAuthError,
    AirtableError,
    AirtableMalformedWebhookError,
    AirtableMedicalPolicyError,
    AirtableNotFoundError,
    AirtableRateLimitError,
    AirtableUnknownIntegrationError,
    AirtableWebhookAuthError,
    AirtableWebhookOwnershipError,
    AirtableWebhookProcessingError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/integrations/airtable", tags=["airtable"])


class ConnectAirtableRequest(BaseModel):
    """Payload per connettere un Personal Access Token a una Base Airtable."""
    token: str = Field(description="Personal Access Token (PAT) Airtable")
    base_id: str = Field(description="Identificativo univoco della Base (appXXXXXXXXXXXXXX)")
    base_name: str = Field(default="", description="Nome visualizzato della Base (opzionale)")


class ValidateSchemaRequest(BaseModel):
    """Payload per la validazione preventiva dello schema prima del salvataggio."""
    base_id: str = Field(description="Identificativo univoco della Base")
    table_id_or_name: str = Field(description="Nome visualizzato o ID della tabella")
    required_fields: list[str] = Field(description="Lista dei campi mappati che devono esistere")


@router.post("/connect")
async def connect_airtable(
    req: ConnectAirtableRequest,
    request: Request,
    user: dict = Depends(require_ruolo("owner")),
    mfa: dict = Depends(require_mfa()),
):
    """Verifica e connette un account Airtable tramite PAT per l'organizzazione corrente.

    Invarianti:
    - Invariante 1 (Tenant Isolation): Eredita organization_id dal contesto utente autenticato.
    - Invariante 6 (GDPR Compliance): Interdizione tassativa (divieto totale) per organizzazioni del settore medico.
    - Invariante 10 (Sicurezza Segreti): Cifra il token a riposo e non lo restituisce mai in chiaro.
    """
    org_id = user.get("organization_id")
    if not org_id:
        raise HTTPException(401, "Nessuna organizzazione collegata")

    service = get_airtable_service(request)
    try:
        res = await service.connect_pat(
            organization_id=org_id,
            token=req.token,
            base_id=req.base_id,
            base_name=req.base_name,
            user_id=user.get("user_id"),
            auth_user_id=user.get("auth_user_id"),
        )
        return res
    except AirtableMedicalPolicyError as exc:
        raise HTTPException(status_code=403, detail=exc.message)
    except AirtableAuthError as exc:
        raise HTTPException(status_code=401, detail=exc.message)
    except AirtableNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message)
    except AirtableRateLimitError as exc:
        raise HTTPException(status_code=429, detail=exc.message)
    except AirtableError as exc:
        raise HTTPException(status_code=400, detail=exc.message)


@router.get("/status")
async def airtable_status(
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
):
    """Restituisce lo stato delle connessioni Airtable per l'organizzazione autenticata."""
    org_id = user.get("organization_id")
    if not org_id:
        raise HTTPException(401, "Nessuna organizzazione collegata")

    service = get_airtable_service(request)
    return await service.get_status(org_id)


@router.post("/validate-schema")
async def validate_table_schema(
    req: ValidateSchemaRequest,
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager")),
):
    """Gate bloccante: valida l'esistenza della tabella e dei campi prima di salvare configurazioni."""
    org_id = user.get("organization_id")
    if not org_id:
        raise HTTPException(401, "Nessuna organizzazione collegata")

    service = get_airtable_service(request)
    try:
        res = await service.validate_schema_for_tenant(
            organization_id=org_id,
            base_id=req.base_id,
            table_id_or_name=req.table_id_or_name,
            required_fields=req.required_fields,
        )
        return res.model_dump()
    except AirtableNotFoundError as exc:
        raise HTTPException(404, detail=exc.message)
    except AirtableAuthError as exc:
        raise HTTPException(401, detail=exc.message)
    except AirtableError as exc:
        raise HTTPException(400, detail=exc.message)


@router.delete("")
async def disconnect_airtable(
    request: Request,
    base_id: str = Query(..., description="ID della Base Airtable da disconnettere"),
    user: dict = Depends(require_ruolo("owner")),
    mfa: dict = Depends(require_mfa()),
):
    """Rimuove la connessione Airtable specificata per l'organizzazione."""
    org_id = user.get("organization_id")
    if not org_id:
        raise HTTPException(401, "Nessuna organizzazione collegata")

    service = get_airtable_service(request)
    return await service.disconnect(
        organization_id=org_id,
        base_id=base_id,
        user_id=user.get("user_id"),
        auth_user_id=user.get("auth_user_id"),
    )


# ── WEBHOOK AIRTABLE (INVARIANTI 1, 3, 4, 5, 9, 10) ──────────────────────────


class SubscribeWebhookRequest(BaseModel):
    """Payload per registrare una sottoscrizione webhook Airtable per il tenant."""
    base_id: str = Field(description="Identificativo univoco della Base")
    webhook_id: str = Field(description="Identificativo univoco del webhook generato da Airtable (achXXXXXXXXXXXXXX)")
    mac_secret: str = Field(description="Segreto MAC (macSecretBase64) generato da Airtable")
    notification_url: str = Field(default="", description="URL di notifica configurato su Airtable")
    specification: dict[str, Any] | None = Field(default=None, description="Specifiche filtri evento Airtable")


@router.post("/webhook")
async def airtable_webhook_endpoint(
    request: Request,
    background_tasks: BackgroundTasks,
    webhook_service: Any = Depends(get_airtable_webhook_service),
):
    """Endpoint HTTP ufficiale per la ricezione delle notifiche webhook da Airtable.

    Meccanismo ufficiale Airtable (thin ping): la notifica contiene solo base.id,
    webhook.id e timestamp; la risposta attesa da Airtable e' 200/204 con BODY VUOTO.

    Conforme a:
    - Invariante 1 (Tenant Isolation): Identifica il tenant unicamente dal webhook_id registrato nel DB,
      ignorando qualsiasi parametro o payload non autenticato.
    - Invariante 3 (Webhook Latency): Ritorna HTTP 200 (body vuoto) in pochi millisecondi. Non esegue
      elaborazione pesante nel thread HTTP sincrono; delega il recupero dei payload e l'elaborazione
      a BackgroundTasks.
    - Invariante 4 (Idempotency Everywhere): Deduplica in modo atomico su (organization_id, webhook_id,
      external_event_id) dove external_event_id deriva dal timestamp della notifica ufficiale.
    - Invariante 10 (Sicurezza Segreti): Verifica crittograficamente l'header X-Airtable-Content-MAC
      (HMAC-SHA256 ufficiale) con il macSecretBase64 memorizzato alla creazione del webhook.
    """
    raw_body = await request.body()
    header_mac = request.headers.get("x-airtable-content-mac") or request.headers.get("X-Airtable-Content-MAC")

    try:
        event, sub, is_duplicate = await webhook_service.handle_incoming_notification(
            raw_body=raw_body,
            header_mac=header_mac,
        )

        if is_duplicate:
            logger.info(
                "Airtable webhook duplicato scartato (webhook_id=%s, org_id=%s, ext_id=%s)",
                sub.webhook_id, sub.organization_id, getattr(event, "external_event_id", None),
            )
            # Acknowledgment ufficiale: 200 con body vuoto anche per i duplicati, per evitare
            # retry storms lato Airtable su notifiche gia' elaborate.
            return Response(status_code=200)

        # Delega asincrona del processing pesante (Invariante 3): recupero payloads via cursore
        # e trasformazione dei record avvengono fuori dalla request HTTP.
        background_tasks.add_task(
            webhook_service.process_event_async,
            event_id=event.id,
            organization_id=sub.organization_id,
            base_id=sub.base_id,
            webhook_id=sub.webhook_id,
            payload=getattr(event, "payload", None) or {},
        )

        # Risposta ufficiale Airtable: 200 con body vuoto.
        return Response(status_code=200)

    except AirtableMalformedWebhookError as exc:
        raise HTTPException(status_code=400, detail=exc.message)
    except AirtableWebhookAuthError as exc:
        raise HTTPException(status_code=401, detail=exc.message)
    except AirtableUnknownIntegrationError as exc:
        raise HTTPException(status_code=404, detail=exc.message)
    except AirtableWebhookProcessingError as exc:
        raise HTTPException(status_code=500, detail=exc.message)
    except AirtableError as exc:
        raise HTTPException(status_code=400, detail=exc.message)


@router.post("/webhooks/subscribe")
async def subscribe_webhook(
    req: SubscribeWebhookRequest,
    request: Request,
    user: dict = Depends(require_ruolo("owner")),
    mfa: dict = Depends(require_mfa()),
    webhook_service: Any = Depends(get_airtable_webhook_service),
    connection_service: Any = Depends(get_airtable_service),
):
    """Registra una sottoscrizione webhook Airtable per l'organizzazione autenticata.

    Autorizzazione Base (Invariante 1): la sottoscrizione e' consentita solo per Base
    effettivamente connesse dall'organizzazione autenticata: un tenant non puo' registrare
    webhook verso Base di altri tenant, ne' appropriarsi di webhook_id registrati altrove.
    """
    org_id = user.get("organization_id")
    if not org_id:
        raise HTTPException(401, "Nessuna organizzazione collegata")

    # Base ownership check: la Base deve essere connessa e attiva per QUESTO tenant.
    try:
        await connection_service.get_adapter_for_tenant(org_id, req.base_id)
    except AirtableNotFoundError as exc:
        raise HTTPException(
            status_code=403,
            detail="Base Airtable non connessa per questa organizzazione: "
                   "connettere la Base prima di registrare un webhook.",
        ) from exc

    try:
        sub = await webhook_service.register_webhook(
            organization_id=org_id,
            base_id=req.base_id,
            webhook_id=req.webhook_id,
            mac_secret=req.mac_secret,
            notification_url=req.notification_url,
            specification=req.specification,
        )
    except AirtableWebhookOwnershipError as exc:
        raise HTTPException(status_code=403, detail=exc.message) from exc
    except AirtableError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return {
        "success": True,
        "webhook_id": sub.webhook_id,
        "base_id": sub.base_id,
        "is_active": sub.is_active,
    }


@router.get("/webhooks/events")
async def list_webhook_events(
    request: Request,
    base_id: str | None = Query(None, description="Filtra per Base Airtable"),
    limit: int = Query(50, ge=1, le=100),
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
    webhook_service: Any = Depends(get_airtable_webhook_service),
):
    """Elenca gli eventi webhook registrati per l'organizzazione corrente (Invariante 1)."""
    org_id = user.get("organization_id")
    if not org_id:
        raise HTTPException(401, "Nessuna organizzazione collegata")

    events = await webhook_service.list_events(organization_id=org_id, base_id=base_id, limit=limit)
    return [e.model_dump() for e in events]
