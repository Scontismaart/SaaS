import os
import json
import time
import threading
import uuid
import asyncpg
from collections import defaultdict
from datetime import datetime
from contextlib import asynccontextmanager
from dotenv import load_dotenv

dotenv_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
load_dotenv(dotenv_path=dotenv_path)

from fastapi import FastAPI, HTTPException, File, UploadFile, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.core.notifications.email_service import start_worker, stop_worker as stop_email_worker
from src.core.crew_runner import genera_risposta
from src.core.priorita import calcola_priorita, calcola_priorita_recensione
from src.core.conversation_store import store as conv_store

from src.core.scheduler import (
    imposta_fonte_dati,
    imposta_pool,
    avvia_scheduler,
    ferma_scheduler,
    get_report_cache,
    set_report_cache,
)
from src.core.crew_runner_report import genera_report as genera_report_completo
from src.core.crew_runner_review import genera_risposta_recensione
from src.core.email_config_store import carica_config, elenca_config, elimina_config, inizializza as init_email_store
from src.core.documenti.vector_store import aggiungi, conteggio, elenco_fonti, elimina_documento
from src.core.documenti.extractor import estrai_testo
from src.core.documenti.qa_agent import rispondi
from src.core.documenti.chunking import chunk_testo
from src.core.onboarding import (
    generate_preview,
    get_active_profile,
    get_active_profile_record,
    list_verticals,
    save_profile,
)
from src.models.business_profile import PROFILI_DEMO
from src.models.schemas import (
    CaricaDocumentoInput,
    ConfiguraEmailInput,
    DomandaInput,
    RispostaDocumento,
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

from src.core.auth.dependencies import get_repo, require_ruolo, close_http_client
from src.core.db.repository import CoreRepository
from src.core.calendar import GoogleCalendarService
from src.core.calendar.routes import router as calendar_router
from src.core.auth.audit import audit_log
from src.core.billing.routes import router as billing_router
from src.core.billing.config import BillingConfig
from src.core.gdpr.routes import router as gdpr_router
from src.core.inbox.routes import router as inbox_router
from src.core.bookings.routes import router as bookings_router
from src.whatsapp.repository import Repository as WhatsAppRepository
from src.whatsapp.router import create_router as create_whatsapp_router
from src.whatsapp.config import AppConfig as WhatsAppAppConfig


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Config globale — settato incondizionatamente, prima di qualsiasi
    # dipendenza dal DB, cosi' e' disponibile anche in modalita' demo
    # (DATABASE_URL assente o DB irraggiungibile).
    app.state.billing_config = BillingConfig(
        stripe_trial_days=int(os.getenv("STRIPE_TRIAL_DAYS", "7")),
    )
    start_worker()
    dsn = os.getenv("DATABASE_URL")
    if dsn:
        import asyncpg
        try:
            pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=5)
            app.state.repo = CoreRepository(pool=pool)
            app.state.pool = pool
            print("[startup] Database pool created successfully.")

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
            else:
                print(
                    "[startup] META_APP_SECRET o META_VERIFY_TOKEN non configurati: "
                    "webhook WhatsApp NON montato. Impostali in .env per riceverli."
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
            print(f"[startup] Database connection failed: {e}. Running without pool.")
            app.state.repo = None
            app.state.pool = None
            app.state.wrepo = None
            from src.core.bookings.memory_repo import InMemoryBookingRepo
            app.state.booking_service = BookingService(
                repo=InMemoryBookingRepo(),
                whatsapp_service=None, app_config=None,
            )
            init_email_store()
            _imposta_fonte_dati_per_scheduler()
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
        init_email_store()
        _imposta_fonte_dati_per_scheduler()
    imposta_pool(app.state.pool)
    avvia_scheduler()
    yield
    ferma_scheduler()
    stop_email_worker()
    if app.state.pool:
        await app.state.pool.close()
    await close_http_client()


app = FastAPI(title="WhatsApp AI Responder - Demo API", lifespan=lifespan)

app.include_router(billing_router)
app.include_router(gdpr_router)
app.include_router(inbox_router)
app.include_router(bookings_router)
app.include_router(calendar_router)

cors_str = os.getenv("CORS_ORIGINS", "http://localhost:5173")
allow_origins = [o.strip() for o in cors_str.split(",") if o.strip()]
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
    allow_headers=["Authorization", "X-Organization-Id", "X-API-Key", "Content-Type"],
)

# ── Rate limiting ──────────────────────────────────────────────
# LIMITAZIONE NOTA: lo stato (rate_windows) e' un dict in-memory locale a
# QUESTO processo. Se l'app viene eseguita con piu' worker (es. `uvicorn
# --workers N` o piu' repliche/pod), ogni processo mantiene il proprio
# contatore indipendente: un tenant potrebbe quindi superare il limite
# effettivo fino a un fattore N senza che nessun singolo processo se ne
# accorga. Per un rate limiting corretto in un deployment multi-processo
# o multi-istanza serve uno store condiviso (es. Redis) — vedi sezione
# "Futuro" nel design doc (docs/superpowers/specs/2026-07-24-auth-authorization-design.md).
RATE_LIMIT_LIMIT = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
LLM_GLOBAL_RATE_LIMIT = int(os.getenv("LLM_GLOBAL_RATE_LIMIT", "200"))
LLM_GLOBAL_RATE_WINDOW = int(os.getenv("LLM_GLOBAL_RATE_WINDOW_SECONDS", "60"))
LLM_ROUTES = {"/api/messaggio", "/api/recensione", "/api/documenti/chiedi"}
rate_windows: dict[str, list[float]] = defaultdict(list)


def _rate_limit_check(key: str, now: float, limit: int | None = None,
                       window_seconds: int | None = None) -> bool:
    """True se key ha superato il limite nella finestra corrente.
    Se limit/window_seconds sono None, usa i valori globali."""
    if limit is None:
        limit = RATE_LIMIT_LIMIT
    if window_seconds is None:
        window_seconds = RATE_LIMIT_WINDOW
    window = rate_windows[key]
    window[:] = [t for t in window if t > now - window_seconds]
    if len(window) >= limit:
        return True
    window.append(now)
    return False


@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):
    trace_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
    request.state.trace_id = trace_id
    response = await call_next(request)
    response.headers["X-Trace-ID"] = trace_id
    return response


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path in ("/api/health", "/webhooks/whatsapp", "/api/billing/webhook"):
        return await call_next(request)
    now = time.time()

    # Limite per tenant (o IP se non autenticato)
    tenant = request.headers.get("X-Organization-Id") or request.client.host
    if _rate_limit_check(f"tenant:{tenant}", now):
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit superato per l'organizzazione. Riprova tra poco."},
        )

    # Limite per utente/credenziale (Bearer JWT o X-API-Key), indipendente dal tenant:
    # evita che un singolo utente saturi la finestra condivisa dell'organizzazione.
    user_token = request.headers.get("Authorization") or request.headers.get("X-API-Key")
    if user_token and _rate_limit_check(f"user:{user_token}", now):
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit superato per l'utente. Riprova tra poco."},
        )

    # Audit 3.3: cap aggregato su TUTTE le chiamate LLM, indipendentemente
    # dal tenant/utente — protegge il budget OpenRouter condiviso da un
    # "noisy neighbor" fatto di molti tenant piccoli.
    if request.url.path in LLM_ROUTES:
        if _rate_limit_check("llm:global", now, LLM_GLOBAL_RATE_LIMIT, LLM_GLOBAL_RATE_WINDOW):
            return JSONResponse(
                status_code=429,
                content={"detail": "Limite globale chiamate AI raggiunto. Riprova tra poco."},
            )

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
            auth_user_id=user.get("auth_user_id"),
            target_table=target_table,
            target_id=target_id,
            details=details,
        )
    except Exception as e:
        # L'audit non deve mai far fallire la richiesta principale.
        print(f"[audit_log] scrittura fallita per action={action}: {e}")


_storico_eventi: list[EventoDashboard] = []
_prossimo_id_evento: int = 0

def _prossimo_id(tipo: str) -> str:
    global _prossimo_id_evento
    _prossimo_id_evento += 1
    return f"{tipo}-{datetime.now().strftime('%Y%m%d')}-{_prossimo_id_evento}"


def _imposta_fonte_dati_per_scheduler():
    imposta_fonte_dati(lambda: _storico_eventi)


@app.post("/api/messaggio", response_model=RispostaOutput)
def ricevi_messaggio(messaggio: MessaggioInput, profilo_id: str = "trattoria_da_mario"):
    profilo = get_active_profile() or PROFILI_DEMO.get(profilo_id)
    if profilo is None:
        raise HTTPException(status_code=404, detail=f"Profilo '{profilo_id}' non trovato")

    cronologia = conv_store.recupera_cronologia(messaggio.id_conversazione)

    try:
        risposta = genera_risposta(messaggio, profilo, cronologia)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Errore nella generazione della risposta: {e}")

    conv_store.aggiungi(messaggio.id_conversazione, messaggio.testo, risposta.risposta)

    prenotazione_salvata = None
    pren = risposta.prenotazione
    if pren and pren.data and pren.ora and pren.coperti:
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
            prenotazione_salvata = crea_prenotazione_dashboard(demo_input)
        except Exception as e:
            print(f"[demo] Booking save failed: {e}")

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
                "prenotazione_id": prenotazione_salvata.id if prenotazione_salvata else None,
            },
        )
    )
    return risposta


@app.get("/api/onboarding/verticali")
def onboarding_verticali(user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    return {"verticali": list_verticals()}


@app.get("/api/onboarding/profilo")
def onboarding_profilo(user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    return {"profilo": get_active_profile_record()}


@app.post("/api/onboarding/profilo")
def onboarding_salva_profilo(
    profilo: OnboardingProfileInput,
    user: dict = Depends(require_ruolo("owner", "manager")),
):
    return {"profilo": save_profile(profilo)}


@app.post("/api/onboarding/preview", response_model=RispostaOutput)
def onboarding_preview(
    richiesta: PreviewInput,
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
):
    return generate_preview(richiesta)


@app.post("/api/recensione", response_model=RispostaRecensioneOutput)
async def ricevi_recensione(recensione: RecensioneInput, request: Request, user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    import asyncio
    try:
        output = await asyncio.to_thread(
            lambda: genera_risposta_recensione(
                testo=recensione.testo,
                stelle=recensione.valutazione_stelle,
                autore=recensione.autore,
            )
        )
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Errore nella generazione della bozza risposta: {e}",
        )

    stato = "bozza_generata"
    review_id = str(uuid.uuid4())
    org_id = user.get("organization_id")

    if org_id:
        repo = get_repo(request)
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
                print(f"[recensione] Conflitto univoco senza riga trovata org={org_id} external_id={recensione.external_id}")
                raise HTTPException(status_code=502, detail="Impossibile salvare la recensione, riprova.")
            review_id = str(esistente["id"])
            stato = esistente["stato"]
        except Exception as e:
            # Prima era "except Exception: pass": errore ingoiato senza log,
            # id fittizio (uuid locale) mai persistito restituito al chiamante,
            # che poi falliva silenziosamente su /approva. Ora logghiamo e
            # segnaliamo l'errore invece di mentire sul successo.
            print(f"[recensione] Persistenza fallita org={org_id} external_id={recensione.external_id}: {e}")
            raise HTTPException(status_code=502, detail="Impossibile salvare la recensione, riprova.")

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
        raise HTTPException(
            status_code=502,
            detail=f"Errore nella generazione del report: {e}",
        )

    set_report_cache(oggi, report)
    return report


@app.get("/api/report/stato")
def stato_report(user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    oggi = datetime.now().strftime("%Y-%m-%d")
    report = get_report_cache(oggi)
    return {"disponibile": report is not None, "id": f"report-{oggi}" if report else None}


@app.get("/api/email/config")
def elenca_configurazioni(user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    return {"configurazioni": elenca_config()}


@app.delete("/api/email/config/{indirizzo}")
async def rimuovi_configurazione(indirizzo: str, request: Request, user: dict = Depends(require_ruolo("owner", "manager"))):
    if elimina_config(indirizzo):
        await _audit(request, user, "email_config_rimossa", target_table="email_configs", details={"indirizzo": indirizzo})
        return {"detail": f"Configurazione per {indirizzo} rimossa."}
    raise HTTPException(status_code=404, detail="Configurazione non trovata.")


@app.post("/api/email/test")
def test_email(user: dict = Depends(require_ruolo("owner", "manager"))):
    return {"detail": "Integrazione email rimossa. Funzionalita' deprecata.", "trovate": 0}


@app.post("/api/documenti/indicizza")
def indicizza_documenti(user: dict = Depends(require_ruolo("owner", "manager"))):
    return {"detail": "Indicizzazione email rimossa. Funzionalita' deprecata.", "trovate": 0, "indicizzate": 0}


@app.post("/api/documenti/chiedi", response_model=RispostaDocumento)
def chiedi_documenti(domanda: DomandaInput, user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    return rispondi(domanda.domanda, k=domanda.k)


@app.get("/api/documenti/conteggio")
def conteggio_documenti(user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    return {"chunk_indicizzati": conteggio()}


@app.get("/api/documenti/elenco")
def elenco_documenti(user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    return {"documenti": elenco_fonti()}


@app.post("/api/documenti/carica")
def carica_documento(doc: CaricaDocumentoInput, user: dict = Depends(require_ruolo("owner", "manager"))):
    if not doc.testo.strip():
        raise HTTPException(status_code=400, detail="Testo vuoto.")

    chunks = chunk_testo(doc.testo)
    documento_id = uuid.uuid4().hex[:16]
    caricato_il = datetime.now().isoformat(timespec="seconds")
    metadati = [{"fonte": doc.nome, "tipo": "upload", "document_id": documento_id, "caricato_il": caricato_il}] * len(chunks)
    aggiunti = aggiungi(chunks, metadati)

    return {"detail": f"Indicizzati {aggiunti} chunk da '{doc.nome}'.", "indicizzati": aggiunti, "id": documento_id}


@app.post("/api/documenti/carica-file")
async def carica_file_documento(file: UploadFile = File(...), user: dict = Depends(require_ruolo("owner", "manager"))):
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

    chunks = chunk_testo(testo)
    documento_id = uuid.uuid4().hex[:16]
    caricato_il = datetime.now().isoformat(timespec="seconds")
    metadati = [{"fonte": nome, "tipo": "documento", "document_id": documento_id, "caricato_il": caricato_il}] * len(chunks)
    aggiunti = aggiungi(chunks, metadati)
    return {"detail": f"Indicizzati {aggiunti} chunk da '{nome}'.", "indicizzati": aggiunti, "nome": nome, "id": documento_id}


@app.delete("/api/documenti/{documento_id}")
async def elimina_documento_api(documento_id: str, request: Request, user: dict = Depends(require_ruolo("owner", "manager"))):
    eliminati = elimina_documento(documento_id)
    if not eliminati:
        raise HTTPException(status_code=404, detail="Documento non trovato.")
    await _audit(request, user, "documento_eliminato", target_table="documents", details={"documento_id": documento_id, "chunk_eliminati": eliminati})
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
