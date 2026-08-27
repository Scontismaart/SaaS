import os
import json
import threading
import uuid
import asyncpg
from datetime import date, datetime
from contextlib import asynccontextmanager
from dotenv import load_dotenv

dotenv_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
load_dotenv(dotenv_path=dotenv_path)

import logging
from src.core.logging_filter import configure_logging

configure_logging(level=logging.INFO)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException, File, UploadFile, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import JSONResponse

from src.core.notifications.email_service import start_worker, stop_worker as stop_email_worker
from src.core.crew_runner import genera_risposta
from src.core.llm_config import LLMRouteRequest, budget_ratio_from_billing, route_llm
from src.core.priorita import calcola_priorita, calcola_priorita_recensione
from src.core.conversation_store import store as conv_store

from src.core.scheduler import (
    imposta_fonte_dati,
    avvia_scheduler,
    ferma_scheduler,
    get_report_cache,
    set_report_cache,
)
from src.core.crew_runner_report import genera_report as genera_report_completo
from src.core.crew_runner_review import genera_risposta_recensione
from src.core.documenti.embeddings import vettorizza
from src.core.documenti.extractor import estrai_testo
from src.core.documenti.qa_agent import rispondi
from src.core.documenti.chunking import chunk_testo
from src.core.onboarding import (
    generate_preview,
    get_profile,
    list_verticals,
    save_profile,
)
from src.models.business_profile import PROFILI_DEMO
from src.models.schemas import (
    CaricaDocumentoInput,
    DomandaInput,
    RispostaDocumento,
    LINGUE_DISPONIBILI,
    MessaggioInput,
    RispostaOutput,
    RecensioneInput,
    RispostaRecensioneOutput,
    EventoDashboard,
    ReportOutput,
    OnboardingProfileInput,
    PreviewInput,
)
import sentry_sdk as _sentry_sdk
_sentry_dsn = os.getenv("SENTRY_DSN")
if _sentry_dsn:
    _sentry_sdk.init(
        dsn=_sentry_dsn,
        traces_sample_rate=0.1,
        profiles_sample_rate=0.1,
    )

from src.core.auth.csrf import validate_csrf_request
from src.core.auth.dependencies import get_repo, require_ruolo, close_http_client
from src.core.auth.routes import router as auth_router
from src.core.auth.register import router as register_router
from src.core.rate_limit import close_rate_limiter, get_rate_limiter, reset_memory_rate_limiter
from src.core.security.docs import is_production, require_docs_access
from src.core.db.repository import CoreRepository
from src.core.calendar import GoogleCalendarService
from src.core.calendar.routes import router as calendar_router
from src.core.auth.audit import audit_log
from src.core.billing.routes import router as billing_router
from src.core.billing.config import BillingConfig
from src.core.gdpr.routes import router as gdpr_router
from src.core.inbox.routes import router as inbox_router
from src.core.bookings.routes import router as bookings_router
from src.core.reviews.routes import router as reviews_router
from src.core.reviews.google_routes import router as reviews_google_router
from src.whatsapp.repository import Repository as WhatsAppRepository
from src.whatsapp.router import create_router as create_whatsapp_router
from src.whatsapp.config import AppConfig as WhatsAppAppConfig
from src.instagram.routes import router as instagram_account_router
from src.instagram.router import create_router as create_instagram_router
from src.instagram.repository import InstagramRepository


@asynccontextmanager
async def lifespan(app: FastAPI):
    from src.core.startup_guard import assert_production_safe
    assert_production_safe()
    # Config globale — settato incondizionatamente, prima di qualsiasi
    # dipendenza dal DB, cosi' e' disponibile anche in modalita' demo
    # (DATABASE_URL assente o DB irraggiungibile).
    app.state.billing_config = BillingConfig(
        stripe_trial_days=int(os.getenv("STRIPE_TRIAL_DAYS", "7")),
    )
    reset_memory_rate_limiter()
    start_worker()
    dsn = os.getenv("DATABASE_URL")
    if dsn:
        import asyncpg
        try:
            # Task18 Fase 4: max_size configurabile via env (scalabilità).
            # Default 5 come prima; con più worker/replica o carico alto,
            # aumenta senza toccare codice. Per picchi reali valutare un
            # pooler (Supavisor/pgBouncer) — vedi report task18.
            db_pool_max = int(os.getenv("DB_POOL_MAX_SIZE", "5"))
            # command_timeout: nessuna query web puo' restare appesa
            # all'infinito (difesa post-incidente pool scheduler).
            pool = await asyncpg.create_pool(
                dsn=dsn, min_size=1, max_size=db_pool_max, command_timeout=30
            )
            app.state.repo = CoreRepository(pool=pool)
            app.state.pool = pool
            logger.info("[startup] Database pool created successfully.")

            # Webhook WhatsApp reale: prima non era mai montato, quindi Meta non
            # poteva raggiungere l'app in nessun deploy. Serve il pool (per
            # persistere contatti/conversazioni/messaggi in arrivo), quindi lo
            # registriamo qui a runtime invece che a import time del modulo.
            wrepo = WhatsAppRepository(pool=pool)
            app.state.wrepo = wrepo
            whatsapp_app_config = WhatsAppAppConfig(
                app_secret=os.getenv("META_APP_SECRET", ""),
                encryption_key=os.getenv("ENCRYPTION_KEY", ""),
                postgres_dsn=dsn,
                verify_token=os.getenv("META_VERIFY_TOKEN", ""),
            )
            if whatsapp_app_config.app_secret and whatsapp_app_config.verify_token:
                whatsapp_router = create_whatsapp_router(whatsapp_app_config, wrepo)
                app.include_router(whatsapp_router)
                # Instagram DM: stessa app Meta (stesso app_secret/verify_token),
                # webhook dedicato /webhooks/instagram con lookup tenant su
                # instagram_accounts (migration 030).
                instagram_router = create_instagram_router(
                    whatsapp_app_config, wrepo, InstagramRepository(pool=pool)
                )
                app.include_router(instagram_router)
            else:
                logger.warning(
                    "[startup] META_APP_SECRET o META_VERIFY_TOKEN non configurati: "
                    "webhook WhatsApp/Instagram NON montati. Impostali in .env per riceverli."
                )

            from src.core.bookings import BookingService
            from src.whatsapp.service import WhatsAppService
            wservice = WhatsAppService(app_config=whatsapp_app_config, repo=wrepo)
            calendar_service = GoogleCalendarService(
                repo=CoreRepository(pool=pool),
                encryption_key=os.getenv("ENCRYPTION_KEY", ""),
            )
            app.state.calendar_service = calendar_service
            app.state.booking_service = BookingService(
                repo=CoreRepository(pool=pool),
                whatsapp_service=wservice,
                app_config=whatsapp_app_config,
                calendar_service=calendar_service,
            )
        except Exception as e:
            logger.warning("[startup] Database connection failed: %s. Running without pool.", e)
            app.state.repo = None
            app.state.pool = None
            app.state.wrepo = None
            from src.core.bookings import BookingService
            from src.core.bookings.memory_repo import InMemoryBookingRepo
            app.state.booking_service = BookingService(
                repo=InMemoryBookingRepo(),
                whatsapp_service=None, app_config=None,
            )
            _imposta_fonte_dati_per_scheduler()
            try:
                from src.core.documenti.embeddings import _modello
                asyncio.create_task(asyncio.to_thread(_modello))
            except Exception as e:
                logger.warning("[startup] Embedding model warmup warning: %s", e)
    else:
        app.state.repo = None
        app.state.pool = None
        app.state.wrepo = None
        from src.core.bookings import BookingService
        from src.core.bookings.memory_repo import InMemoryBookingRepo
        app.state.booking_service = BookingService(
            repo=InMemoryBookingRepo(),
            whatsapp_service=None, app_config=None,
        )
        _imposta_fonte_dati_per_scheduler()
    avvia_scheduler()
    yield
    ferma_scheduler()
    stop_email_worker()
    if app.state.pool:
        await app.state.pool.close()
    await close_http_client()
    await close_rate_limiter()


app = FastAPI(
    title="WhatsApp AI Responder - Demo API",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.get("/openapi.json", include_in_schema=False)
async def protected_openapi(request: Request):
    require_docs_access(request)
    return app.openapi()


@app.get("/docs", include_in_schema=False)
async def protected_docs(request: Request):
    require_docs_access(request)
    return get_swagger_ui_html(openapi_url="/openapi.json", title=f"{app.title} - Docs")


@app.get("/redoc", include_in_schema=False)
async def protected_redoc(request: Request):
    require_docs_access(request)
    return get_redoc_html(openapi_url="/openapi.json", title=f"{app.title} - ReDoc")

app.include_router(billing_router)
app.include_router(gdpr_router)
app.include_router(inbox_router)
app.include_router(bookings_router)
app.include_router(calendar_router)
app.include_router(reviews_router)
app.include_router(reviews_google_router)
app.include_router(instagram_account_router)
app.include_router(auth_router)
app.include_router(register_router)

cors_str = os.getenv("CORS_ORIGINS", "http://localhost:5173")
allow_origins = [o.strip() for o in cors_str.split(",") if o.strip()]
public_url = (os.getenv("PUBLIC_APP_URL") or "").strip().rstrip("/")
if public_url and public_url not in allow_origins:
    allow_origins.append(public_url)
if not allow_origins:
    raise RuntimeError(
        "CORS_ORIGINS e' impostata ma vuota dopo il parsing. "
        "Imposta una lista di origini valide separate da virgola, "
        "o rimuovi la variabile per usare il default locale."
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "X-Organization-Id", "X-API-Key", "X-CSRF-Token", "Content-Type"],
)

# ── Rate limiting ──────────────────────────────────────────────
RATE_LIMIT_LIMIT = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
LLM_GLOBAL_RATE_LIMIT = int(os.getenv("LLM_GLOBAL_RATE_LIMIT", "200"))
LLM_GLOBAL_RATE_WINDOW = int(os.getenv("LLM_GLOBAL_RATE_WINDOW_SECONDS", "60"))
LLM_ROUTES = {"/api/messaggio", "/api/recensione", "/api/documenti/chiedi"}


async def _rate_limit_check(key: str, limit: int | None = None,
                            window_seconds: int | None = None) -> bool:
    """True se key ha superato il limite nella finestra corrente.
    Se limit/window_seconds sono None, usa i valori globali."""
    if limit is None:
        limit = RATE_LIMIT_LIMIT
    if window_seconds is None:
        window_seconds = RATE_LIMIT_WINDOW
    limiter = await get_rate_limiter()
    return await limiter.hit(key, limit, window_seconds)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; img-src 'self' data:; connect-src 'self'; base-uri 'self'; form-action 'self'",
    )
    return response


@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):
    trace_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
    request.state.trace_id = trace_id
    response = await call_next(request)
    response.headers["X-Trace-ID"] = trace_id
    return response


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path in ("/api/health", "/webhooks/whatsapp", "/webhooks/instagram", "/api/billing/webhook"):
        return await call_next(request)

    # Limite per tenant (o IP se non autenticato)
    tenant = request.headers.get("X-Organization-Id") or request.client.host
    if await _rate_limit_check(f"tenant:{tenant}"):
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit superato per l'organizzazione. Riprova tra poco."},
        )

    # Limite per utente/credenziale (Bearer JWT o X-API-Key), indipendente dal tenant:
    # evita che un singolo utente saturi la finestra condivisa dell'organizzazione.
    user_token = request.headers.get("Authorization") or request.headers.get("X-API-Key")
    if user_token and await _rate_limit_check(f"user:{user_token}"):
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit superato per l'utente. Riprova tra poco."},
        )

    # Audit 3.3: cap aggregato su TUTTE le chiamate LLM, indipendentemente
    # dal tenant/utente — protegge il budget OpenRouter condiviso da un
    # "noisy neighbor" fatto di molti tenant piccoli.
    if request.url.path in LLM_ROUTES:
        if await _rate_limit_check("llm:global", LLM_GLOBAL_RATE_LIMIT, LLM_GLOBAL_RATE_WINDOW):
            return JSONResponse(
                status_code=429,
                content={"detail": "Limite globale chiamate AI raggiunto. Riprova tra poco."},
            )

    return await call_next(request)


@app.middleware("http")
async def csrf_middleware(request: Request, call_next):
    ok, detail = validate_csrf_request(request)
    if not ok:
        return JSONResponse(status_code=403, content={"detail": detail})
    return await call_next(request)


async def _audit(request: Request, user: dict, action: str, target_table: str | None = None,
                  target_id: str | None = None, details: dict | None = None) -> None:
    """Registra un'azione sensibile in audit_log. No-op sicuro se repo o
    organization_id non disponibili (es. demo senza DATABASE_URL, o
    chiamata via service_role senza X-Organization-Id)."""
    repo = getattr(request.app.state, "repo", None)
    organization_id = user.get("organization_id")
    if repo is None or not organization_id:
        return
    try:
        await audit_log(
            repo,
            organization_id=organization_id,
            action=action,
            user_id=user.get("user_id"),
            auth_user_id=user.get("auth_user_id"),
            target_table=target_table,
            target_id=target_id,
            details=details,
        )
    except Exception as e:
        # L'audit non deve mai far fallire la richiesta principale.
        logger.warning("[audit_log] scrittura fallita per action=%s: %s", action, e)


_storico_eventi: list[EventoDashboard] = []
_prossimo_id_evento: int = 0

def _prossimo_id(tipo: str) -> str:
    global _prossimo_id_evento
    _prossimo_id_evento += 1
    return f"{tipo}-{datetime.now().strftime('%Y%m%d')}-{_prossimo_id_evento}"


def _imposta_fonte_dati_per_scheduler():
    imposta_fonte_dati(lambda: _storico_eventi)


async def _get_billing_snapshot(repo, organization_id: str | None) -> dict | None:
    if repo is None or not organization_id:
        return None
    try:
        return await repo.get_organization_billing(organization_id)
    except Exception as e:
        logger.warning("[llm_routing] billing snapshot non disponibile org=%s: %s", organization_id, e)
        return None


async def _record_ai_usage(repo, organization_id: str | None, task_type: str,
                           user_text: str, billing: dict | None,
                           metadata: dict | None = None) -> None:
    if repo is None or not organization_id:
        return
    try:
        route = route_llm(
            LLMRouteRequest(
                task_type=task_type,
                user_text=user_text,
                remaining_budget_ratio=budget_ratio_from_billing(billing),
            )
        )
        await repo.record_usage(
            organization_id,
            "ai_response",
            quantity=1,
            metadata={
                "task_type": task_type,
                "model": route.model,
                "tier": route.tier,
                "reason": route.reason,
                **(metadata or {}),
            },
        )
    except Exception as e:
        logger.warning("[llm_routing] usage logging fallito org=%s: %s", organization_id, e)


@app.post("/api/messaggio", response_model=RispostaOutput)
async def ricevi_messaggio(
    request: Request,
    messaggio: MessaggioInput,
    profilo_id: str = "trattoria_da_mario",
):
    # Se l'utente è autenticato nella dashboard, usa il profilo reale
    # dell'organizzazione (business_profile/onboarding) e il semaforo DB.
    # Altrimenti fallback al profilo demo statico (PROFILI_DEMO).
    org_id = None
    profilo = None
    try:
        from src.core.auth.dependencies import get_organization_context
        user = await get_organization_context(request)
        if user and user.get("source") != "anonymous" and user.get("organization_id"):
            org_id = user["organization_id"]
            repo = getattr(request.app.state, "repo", None)
            if repo:
                org_data = await repo.get_organization(org_id)
                if org_data and org_data.get("business_profile"):
                    from src.whatsapp.inbound_processor import _profile_from_dict
                    profilo = _profile_from_dict(
                        org_data["business_profile"],
                        fallback_name=org_data.get("name", "Attività"),
                    )
    except Exception as e:
        logger.debug("Fallback to static demo profile: %s", e)

    if profilo is None:
        profilo = PROFILI_DEMO.get(profilo_id)
        if profilo is None:
            raise HTTPException(status_code=404, detail=f"Profilo '{profilo_id}' non trovato")

    cronologia = conv_store.recupera_cronologia(messaggio.id_conversazione)

    # Pre-fetch disponibilità da semaforo (DB reale se org autenticata, demo altrimenti)
    from src.agents.prompts import estrai_date_da_testo, formatta_disponibilita
    contesto_disp = ""
    try:
        date_candidate = estrai_date_da_testo(messaggio.testo)
        if date_candidate:
            all_slots = []
            booking_svc = getattr(request.app.state, "booking_service", None)
            for d in date_candidate[:3]:
                if org_id and booking_svc:
                    slots = await booking_svc.semaforo_giorno(org_id, d)
                else:
                    from src.core.prenotazioni import semaforo_giorno
                    slots = semaforo_giorno(d)
                all_slots.extend([s.model_dump() if hasattr(s, "model_dump") else s for s in slots])
            if all_slots:
                contesto_disp = formatta_disponibilita(all_slots)
    except Exception as e:
        logger.warning("Semaforo pre-fetch failed in ricevi_messaggio: %s", e)

    tentativi = conv_store.tentativi_prenotazione(messaggio.id_conversazione)

    from src.core.crew_runner import genera_risposta_async
    try:
        risposta = await genera_risposta_async(
            messaggio, profilo,
            cronologia=cronologia,
            contesto_disponibilita=contesto_disp,
            tentativi_falliti=tentativi,
        )
    except Exception as e:
        logger.error("Error generating AI response in ricevi_messaggio: %s", e)
        raise HTTPException(status_code=502, detail="Impossibile generare la risposta al momento. Riprova più tardi.")

    conv_store.aggiungi(messaggio.id_conversazione, messaggio.testo, risposta.risposta)

    prenotazione_id = None
    pren = risposta.prenotazione
    if pren and pren.data and pren.ora and pren.coperti:
        booking_svc = getattr(request.app.state, "booking_service", None)
        if org_id and booking_svc:
            try:
                created = await booking_svc.create_booking(
                    org_id=org_id,
                    nome_cliente=pren.nome_cliente or "Cliente Dashboard",
                    telefono=pren.telefono or "",
                    data=pren.data,
                    ora=pren.ora,
                    coperti=pren.coperti,
                    note=pren.note,
                    origine="Dashboard",
                    richiede_intervento=risposta.richiede_umano,
                    id_conversazione=messaggio.id_conversazione,
                )
                prenotazione_id = created.get("id") if isinstance(created, dict) else getattr(created, "id", None)
            except Exception as e:
                logger.warning("[dashboard] Real booking save failed: %s", e)
        else:
            from src.core.prenotazioni import crea_prenotazione_dashboard
            from src.models.schemas import PrenotazioneManualeInput
            try:
                demo_input = PrenotazioneManualeInput(
                    nome_cliente=pren.nome_cliente or "Cliente",
                    telefono=pren.telefono or "",
                    data=pren.data,
                    ora=pren.ora,
                    coperti=pren.coperti,
                    note=pren.note,
                    stato="In attesa" if risposta.richiede_umano else "Confermato da IA",
                    origine="WhatsApp",
                )
                creata = crea_prenotazione_dashboard(demo_input)
                prenotazione_id = getattr(creata, "id", None)
            except Exception as e:
                logger.warning("[demo] Booking save failed: %s", e)

    _storico_eventi.append(
        EventoDashboard(
            id=_prossimo_id("msg"),
            tipo_evento="messaggio",
            timestamp=messaggio.timestamp,
            priorita=calcola_priorita(risposta),
            testo_originale=messaggio.testo,
            risposta_ai=risposta.risposta,
            gestito_da_ai=not risposta.richiede_umano,
            dettagli={
                "categoria": risposta.categoria,
                "richiede_umano": risposta.richiede_umano,
                "motivo": risposta.motivo,
                "prenotazione_id": prenotazione_id,
            },
        )
    )
    return risposta


@app.get("/api/onboarding/verticali")
def onboarding_verticali(user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    return {
        "verticali": list_verticals(),
        "lingue_disponibili": sorted(LINGUE_DISPONIBILI),
    }


@app.get("/api/onboarding/profilo")
async def onboarding_profilo(request: Request, user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    org_id = user.get("organization_id")
    if not org_id:
        raise HTTPException(
            status_code=401,
            detail="Nessuna organizzazione collegata: inserisci API key e Organization ID.",
        )
    repo = get_repo(request)
    return {"profilo": await get_profile(org_id, repo)}


@app.post("/api/onboarding/profilo")
async def onboarding_salva_profilo(
    profilo: OnboardingProfileInput,
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager")),
):
    org_id = user.get("organization_id")
    if not org_id:
        raise HTTPException(
            status_code=401,
            detail="Nessuna organizzazione collegata: inserisci API key e Organization ID.",
        )
    repo = get_repo(request)
    profilo_salvato = await save_profile(org_id, profilo, repo)
    await _audit(request, user, "profilo.aggiornato",
                 target_table="onboarding_profiles",
                 details={"nome_attivita": profilo.nome_attivita, "tono": profilo.tono})
    return {"profilo": profilo_salvato}


# ── Impostazioni organizzazione: fuso orario ───────────────────────────

_TIMEZONE_COMUNI = [
    "Europe/Rome", "Europe/London", "Europe/Paris", "Europe/Berlin",
    "Europe/Madrid", "America/New_York", "America/Chicago",
    "America/Los_Angeles", "America/Sao_Paulo", "Asia/Dubai",
    "Asia/Singapore", "Asia/Tokyo", "Australia/Sydney", "UTC",
]


@app.get("/api/impostazioni/organizzazione")
async def get_impostazioni_organizzazione(
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
):
    org_id = user.get("organization_id")
    if not org_id:
        raise HTTPException(401, "Nessuna organizzazione collegata")
    repo = get_repo(request)
    async with repo.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT timezone, name FROM organizations WHERE id = $1::uuid", org_id
        )
    if not row:
        raise HTTPException(404, "Organizzazione non trovata")
    return {
        "timezone": row["timezone"] or "Europe/Rome",
        "nome": row["name"],
        "timezone_disponibili": _TIMEZONE_COMUNI,
    }


@app.put("/api/impostazioni/organizzazione")
async def put_impostazioni_organizzazione(
    body: dict,
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager")),
):
    org_id = user.get("organization_id")
    if not org_id:
        raise HTTPException(401, "Nessuna organizzazione collegata")
    tz = (body.get("timezone") or "").strip()
    if tz not in _TIMEZONE_COMUNI:
        raise HTTPException(422, "Fuso orario non valido")
    repo = get_repo(request)
    async with repo.pool.acquire() as conn:
        await conn.execute(
            "UPDATE organizations SET timezone = $2, updated_at = NOW() WHERE id = $1::uuid",
            org_id, tz,
        )
    await _audit(request, user, "org.timezone_updated",
                 target_table="organizations", details={"timezone": tz})
    return {"ok": True, "timezone": tz}

# ── Audit log: lettura org-scoped ──────────────────────────────────────

@app.get("/api/audit")
async def lista_audit(
    request: Request,
    limit: int = 20,
    offset: int = 0,
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
):
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

@app.get("/api/integrazioni/stato")
async def stato_integrazioni(
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
):
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


@app.post("/api/onboarding/preview", response_model=RispostaOutput)
async def onboarding_preview(
    richiesta: PreviewInput,
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
):
    org_id = user.get("organization_id")
    if not org_id:
        raise HTTPException(
            status_code=401,
            detail="Nessuna organizzazione collegata: inserisci API key e Organization ID.",
        )
    repo = get_repo(request)
    billing = await _get_billing_snapshot(repo, org_id)
    output = await generate_preview(org_id, richiesta, repo, billing=billing)
    await _record_ai_usage(
        repo,
        org_id,
        "onboarding_preview",
        richiesta.messaggio,
        billing,
        {"verticale": richiesta.profilo.verticale},
    )
    return output


@app.post("/api/recensione", response_model=RispostaRecensioneOutput)
async def ricevi_recensione(recensione: RecensioneInput, request: Request, user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    import asyncio
    repo = get_repo(request)
    org_id = user.get("organization_id")
    billing = await _get_billing_snapshot(repo, org_id)
    # Lingue dell'org dal profilo onboarding: se non esiste ancora (onboarding
    # non completato) si usano i default ["it"]/"it", nessun errore.
    profilazione = await repo.get_onboarding_profile(org_id) or {}
    lingue = profilazione.get("lingue_supportate") or None
    lingua_default = profilazione.get("lingua_default") or None
    try:
        output = await asyncio.to_thread(
            lambda: genera_risposta_recensione(
                testo=recensione.testo,
                stelle=recensione.valutazione_stelle,
                autore=recensione.autore,
                billing=billing,
                lingue_supportate=lingue,
                lingua_default=lingua_default,
            )
        )
    except Exception as e:
        logger.error("Error generating review draft: %s", e)
        raise HTTPException(
            status_code=502,
            detail="Impossibile generare la bozza di risposta. Riprova più tardi.",
        )

    stato = "bozza_generata"
    review_id = str(uuid.uuid4())
    if org_id:
        try:
            review = await repo.create_review(
                organization_id=org_id,
                testo=recensione.testo,
                valutazione_stelle=recensione.valutazione_stelle,
                fonte=recensione.fonte,
                autore=recensione.autore,
                external_id=recensione.external_id,
                bozza_risposta=output.bozza_risposta,
                sentiment=output.sentiment,
                categoria=output.categoria,
                richiede_revisione_urgente=output.richiede_revisione_urgente,
                stato=stato,
            )
            review_id = str(review["id"])
        except asyncpg.UniqueViolationError:
            # external_id gia' presente per questa org: non e' un errore,
            # e' il dedup che doveva funzionare. Riusiamo la riga esistente
            # invece di restituire un id fittizio mai salvato.
            esistente = await repo.get_review_by_external_id(org_id, recensione.external_id)
            if esistente is None:
                logger.error("[recensione] Conflitto univoco senza riga trovata org=%s external_id=%s", org_id, recensione.external_id)
                raise HTTPException(status_code=502, detail="Impossibile salvare la recensione, riprova.")
            review_id = str(esistente["id"])
            stato = esistente["stato"]
        except Exception as e:
            # Prima era "except Exception: pass": errore ingoiato senza log,
            # id fittizio (uuid locale) mai persistito restituito al chiamante,
            # che poi falliva silenziosamente su /approva. Ora logghiamo e
            # segnaliamo l'errore invece di mentire sul successo.
            logger.error("[recensione] Persistenza fallita org=%s external_id=%s: %s", org_id, recensione.external_id, e)
            raise HTTPException(status_code=502, detail="Impossibile salvare la recensione, riprova.")

    await _record_ai_usage(
        repo,
        org_id,
        "review",
        recensione.testo,
        billing,
        {"fonte": recensione.fonte, "stelle": recensione.valutazione_stelle},
    )

    _storico_eventi.append(
        EventoDashboard(
            id=_prossimo_id("rec"),
            tipo_evento="recensione",
            timestamp=datetime.now(),
            priorita=calcola_priorita_recensione(recensione.valutazione_stelle, output),
            testo_originale=recensione.testo,
            risposta_ai=output.bozza_risposta,
            gestito_da_ai=True,
            dettagli={
                "sentiment": output.sentiment,
                "stelle": recensione.valutazione_stelle,
                "fonte": recensione.fonte,
                "autore": recensione.autore,
                "richiede_revisione_urgente": output.richiede_revisione_urgente,
                "motivo": output.motivo,
                "categoria": output.categoria,
            },
        )
    )

    return RispostaRecensioneOutput(
        id=review_id,
        stato=stato,
        bozza_risposta=output.bozza_risposta,
        sentiment=output.sentiment,
        richiede_revisione_urgente=output.richiede_revisione_urgente,
        motivo=output.motivo,
        categoria=output.categoria,
    )


@app.get("/api/dashboard", response_model=list[EventoDashboard])
def ottieni_dashboard(user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    return _storico_eventi


@app.get("/api/dashboard/prioritari", response_model=list[EventoDashboard])
def ottieni_eventi_prioritari(limite: int = 5, user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    prioritari = [e for e in _storico_eventi if e.priorita != "bassa"]
    prioritari.sort(
        key=lambda e: (0 if e.priorita == "alta" else 1, e.timestamp),
        reverse=False,
    )
    return prioritari[:limite]


@app.get("/api/report", response_model=ReportOutput)
def ottieni_report(forza: bool = False, user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    oggi = datetime.now().strftime("%Y-%m-%d")

    if not forza:
        cached = get_report_cache(oggi)
        if cached:
            return cached

    try:
        report = genera_report_completo(_storico_eventi)
    except Exception as e:
        logger.error("Error generating daily report: %s", e)
        raise HTTPException(
            status_code=502,
            detail="Impossibile generare il report. Riprova più tardi.",
        )

    set_report_cache(oggi, report)
    return report


@app.get("/api/report/stato")
def stato_report(user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    oggi = datetime.now().strftime("%Y-%m-%d")
    report = get_report_cache(oggi)
    return {"disponibile": report is not None, "id": f"report-{oggi}" if report else None}


@app.get("/api/report/settimanale")
async def report_settimanale(
    forza: bool = False,
    request: Request = None,
    user: dict = Depends(require_ruolo("owner", "manager")),
):
    """Genera (e invia via email) il report settimanale per l'organizzazione
    dell'utente. Idempotente: non reinvia se gia' inviato per lo stesso
    periodo, a meno che forza=true."""
    from src.core.report.weekly_report import genera_e_invia_report_settimanale

    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=503, detail="Database non disponibile")

    org_id = user.get("organization_id")
    if not org_id:
        raise HTTPException(status_code=400, detail="Organizzazione non trovata")

    try:
        risultato = await genera_e_invia_report_settimanale(pool, str(org_id), forza=forza)
    except Exception as e:
        logger.error("Errore generazione report settimanale: %s", e)
        raise HTTPException(status_code=502, detail="Errore durante la generazione o invio del report settimanale")

    return risultato


@app.get("/api/report/csv")
async def export_csv_prenotazioni(
    da: str = None,
    a: str = None,
    request: Request = None,
    user: dict = Depends(require_ruolo("owner", "manager")),
):
    """Export CSV delle prenotazioni completate nel periodo.
    Default: ultima settimana (lunedi-domenica precedente)."""
    from src.core.report.csv_export import get_prenotazioni_completate, genera_csv
    from src.core.report.weekly_report import _calcola_periodo_settimanale
    from fastapi.responses import Response

    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=503, detail="Database non disponibile")

    org_id = user.get("organization_id")
    if not org_id:
        raise HTTPException(status_code=400, detail="Organizzazione non trovata")

    # Date del periodo: default = settimana precedente
    if da and a:
        try:
            inizio = date.fromisoformat(da)
            fine = date.fromisoformat(a)
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato date non valido (YYYY-MM-DD)")
    else:
        inizio, fine = _calcola_periodo_settimanale()

    prenotazioni = await get_prenotazioni_completate(pool, str(org_id), inizio, fine)
    csv_bytes = genera_csv(prenotazioni)

    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="prenotazioni-{inizio.isoformat()}.csv"',
        },
    )


@app.post("/api/documenti/chiedi", response_model=RispostaDocumento)
async def chiedi_documenti(domanda: DomandaInput, request: Request, user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    repo = get_repo(request)
    billing = await _get_billing_snapshot(repo, user.get("organization_id"))
    output = await rispondi(user["organization_id"], domanda.domanda, repo, k=domanda.k, billing=billing)
    await _record_ai_usage(
        repo,
        user.get("organization_id"),
        "document_qa",
        domanda.domanda,
        billing,
        {"k": domanda.k, "fonti": output.get("fonti", [])},
    )
    return output


@app.get("/api/documenti/conteggio")
async def conteggio_documenti(request: Request, user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    repo = get_repo(request)
    return {"chunk_indicizzati": await repo.count_chunks(user["organization_id"])}


@app.get("/api/documenti/elenco")
async def elenco_documenti(request: Request, user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    repo = get_repo(request)
    return {"documenti": await repo.list_sources(user["organization_id"])}


@app.get("/api/ui/summary")
async def ui_summary(request: Request, user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    """Conteggi org-scoped per il polling del frontend (task18 Fase 3).

    Sostituisce le chiamate pesanti di aggiornaNotifiche (bookings,
    documenti/elenco, inbox/tickets, recensioni) con un unico COUNT al DB.
    org-scoped: l'organization_id viene dalla membership JWT server-side.
    """
    repo = get_repo(request)
    return await repo.get_ui_summary(user["organization_id"])


@app.post("/api/documenti/carica")
async def carica_documento(doc: CaricaDocumentoInput, request: Request, user: dict = Depends(require_ruolo("owner", "manager"))):
    if not doc.testo.strip():
        raise HTTPException(status_code=400, detail="Testo vuoto.")

    repo = get_repo(request)
    chunks = chunk_testo(doc.testo)
    if not chunks:
        raise HTTPException(status_code=400, detail="Testo senza contenuto indicizzabile.")

    record = await repo.create_document(user["organization_id"], doc.nome, tipo="upload", fonte="dashboard")
    embeds = vettorizza(chunks, tipo="passage")
    for i, (chunk, emb) in enumerate(zip(chunks, embeds)):
        await repo.add_chunk(
            user["organization_id"], record["id"], i, chunk, emb,
            {"fonte": doc.nome, "tipo": "upload", "document_id": str(record["id"])},
        )
    # Nuova knowledge base -> le risposte FAQ in cache potrebbero essere
    # superate (prezzi/orari cambiati): invalidazione (task 12).
    try:
        await repo.faq_cache_invalidate(user["organization_id"])
    except Exception as exc:  # pragma: no cover - la cache non deve rompere l'upload
        logger.warning("faq_cache invalidation failed org=%s: %s", user["organization_id"], exc)
    return {"detail": f"Indicizzati {len(chunks)} chunk da '{doc.nome}'.", "indicizzati": len(chunks), "id": str(record["id"])}


@app.post("/api/documenti/carica-file")
async def carica_file_documento(request: Request, file: UploadFile = File(...), user: dict = Depends(require_ruolo("owner", "manager"))):
    nome = file.filename or "documento"
    contenuto = await file.read()
    if not contenuto:
        raise HTTPException(status_code=400, detail="Il file è vuoto.")
    if len(contenuto) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Il file supera il limite di 20 MB.")
    try:
        testo = estrai_testo(contenuto, nome, file.content_type or "")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    repo = get_repo(request)
    chunks = chunk_testo(testo)
    if not chunks:
        raise HTTPException(status_code=400, detail="Nessun testo indicizzabile estratto dal file.")

    record = await repo.create_document(user["organization_id"], nome, tipo="documento", fonte=nome)
    embeds = vettorizza(chunks, tipo="passage")
    for i, (chunk, emb) in enumerate(zip(chunks, embeds)):
        await repo.add_chunk(
            user["organization_id"], record["id"], i, chunk, emb,
            {"fonte": nome, "tipo": "documento", "document_id": str(record["id"])},
        )
    try:
        await repo.faq_cache_invalidate(user["organization_id"])
    except Exception as exc:  # pragma: no cover - la cache non deve rompere l'upload
        logger.warning("faq_cache invalidation failed org=%s: %s", user["organization_id"], exc)
    return {"detail": f"Indicizzati {len(chunks)} chunk da '{nome}'.", "indicizzati": len(chunks), "nome": nome, "id": str(record["id"])}


@app.delete("/api/documenti/{documento_id}")
async def elimina_documento_api(documento_id: str, request: Request, user: dict = Depends(require_ruolo("owner", "manager"))):
    repo = get_repo(request)
    eliminati = await repo.delete_document(user["organization_id"], documento_id)
    if not eliminati:
        raise HTTPException(status_code=404, detail="Documento non trovato.")
    await _audit(request, user, "documento_eliminato", target_table="documents", details={"documento_id": documento_id, "chunk_eliminati": eliminati})
    try:
        await repo.faq_cache_invalidate(user["organization_id"])
    except Exception as exc:  # pragma: no cover - la cache non deve rompere l'eliminazione
        logger.warning("faq_cache invalidation failed org=%s: %s", user["organization_id"], exc)
    return {"detail": "Documento rimosso dalla knowledge base.", "chunk_eliminati": eliminati}


@app.get("/api/health")
async def health_check(request: Request):
    """Health check profondo: verifica che il DB sia effettivamente
    raggiungibile, non solo che il processo sia vivo. Se il DB e' giu',
    ritorna 503 cosi' un orchestratore (Docker/Kubernetes) puo' rilevare
    che il container non e' pronto a servire traffico."""
    checks: dict[str, str] = {}
    healthy = True

    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        checks["database"] = "non configurato (DATABASE_URL assente)"
    else:
        try:
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            checks["database"] = "ok"
        except Exception as e:
            checks["database"] = f"errore: {e}"
            healthy = False

    checks["openrouter_key_presente"] = "ok" if os.getenv("OPENROUTER_API_KEY") else "mancante"
    if not os.getenv("OPENROUTER_API_KEY"):
        healthy = False

    payload = {
        "status": "ok" if healthy else "degraded",
        "modello_configurato": os.getenv("OPENROUTER_MODEL", "non impostato"),
        "checks": checks,
    }
    if not healthy:
        return JSONResponse(status_code=503, content=payload)
    return payload
