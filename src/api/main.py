import os
import json
import time
import threading
import uuid
from collections import defaultdict
from datetime import datetime
from contextlib import asynccontextmanager
from dotenv import load_dotenv

dotenv_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
load_dotenv(dotenv_path=dotenv_path)

from fastapi import FastAPI, HTTPException, File, UploadFile, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.core.crew_runner import genera_risposta
from src.core.priorita import calcola_priorita, calcola_priorita_recensione
from src.core.conversation_store import store as conv_store
from src.core.prenotazioni import (
    aggiorna_impostazioni_disponibilita,
    crea_prenotazione_dashboard,
    elenco_prenotazioni,
    get_impostazioni_disponibilita,
    prossimi_giorni_semaforo,
    salva_prenotazione_ai,
    semaforo_giorno,
    verifica_disponibilita,
)
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
from src.models.business_profile import PROFILI_DEMO
from src.models.schemas import (
    CaricaDocumentoInput,
    ConfiguraEmailInput,
    DomandaInput,
    ImpostazioniDisponibilitaInput,
    PrenotazioneManualeInput,
    RispostaDocumento,
    MessaggioInput,
    RispostaOutput,
    RecensioneInput,
    RispostaRecensioneOutput,
    EventoDashboard,
    DisponibilitaSlot,
    PrenotazioneCalendario,
    ReportOutput,
)
from src.core.auth.dependencies import require_ruolo, close_http_client
from src.core.db.repository import CoreRepository
from src.core.auth.audit import audit_log
from src.core.billing.routes import router as billing_router
from src.core.gdpr.routes import router as gdpr_router
from src.core.inbox.routes import router as inbox_router
from src.whatsapp.repository import Repository as WhatsAppRepository
from src.whatsapp.router import create_router as create_whatsapp_router
from src.whatsapp.config import AppConfig as WhatsAppAppConfig


@asynccontextmanager
async def lifespan(app: FastAPI):
    dsn = os.getenv("DATABASE_URL")
    if dsn:
        import asyncpg
        pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=5)
        app.state.repo = CoreRepository(pool=pool)
        app.state.pool = pool

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
    else:
        app.state.repo = None
        app.state.pool = None
        app.state.wrepo = None
    init_email_store()
    _imposta_fonte_dati_per_scheduler()
    imposta_pool(app.state.pool)
    avvia_scheduler()
    yield
    ferma_scheduler()
    if app.state.pool:
        await app.state.pool.close()
    await close_http_client()


app = FastAPI(title="WhatsApp AI Responder - Demo API", lifespan=lifespan)

app.include_router(billing_router)
app.include_router(gdpr_router)
app.include_router(inbox_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
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
rate_windows: dict[str, list[float]] = defaultdict(list)


def _rate_limit_check(key: str, now: float) -> bool:
    """True se key ha superato il limite nella finestra corrente."""
    window = rate_windows[key]
    window[:] = [t for t in window if t > now - RATE_LIMIT_WINDOW]
    if len(window) >= RATE_LIMIT_LIMIT:
        return True
    window.append(now)
    return False


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
    profilo = PROFILI_DEMO.get(profilo_id)
    if profilo is None:
        raise HTTPException(status_code=404, detail=f"Profilo '{profilo_id}' non trovato")

    cronologia = conv_store.recupera_cronologia(messaggio.id_conversazione)

    try:
        risposta = genera_risposta(messaggio, profilo, cronologia)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Errore nella generazione della risposta: {e}")

    conv_store.aggiungi(messaggio.id_conversazione, messaggio.testo, risposta.risposta)

    prenotazione_salvata = None
    if risposta.categoria == "prenotazione" and risposta.prenotazione:
        try:
            risposta, prenotazione_salvata = salva_prenotazione_ai(
                risposta.prenotazione,
                risposta,
                messaggio.id_conversazione,
            )
        except Exception:
            pass

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


@app.get("/api/prenotazioni", response_model=list[PrenotazioneCalendario])
def ottieni_prenotazioni(user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    return elenco_prenotazioni()


@app.post("/api/prenotazioni", response_model=PrenotazioneCalendario)
def crea_prenotazione(prenotazione: PrenotazioneManualeInput, user: dict = Depends(require_ruolo("owner", "manager"))):
    if not prenotazione.data or not prenotazione.ora or not prenotazione.coperti:
        raise HTTPException(status_code=400, detail="Data, ora e coperti sono obbligatori.")

    disponibilita = verifica_disponibilita(prenotazione.data, prenotazione.ora, prenotazione.coperti)
    if prenotazione.coperti > disponibilita.coperti_liberi:
        raise HTTPException(
            status_code=409,
            detail={
                "messaggio": "Slot al completo per il numero di coperti richiesto.",
                "disponibilita": disponibilita.model_dump(),
            },
        )

    return crea_prenotazione_dashboard(prenotazione)


@app.get("/api/prenotazioni/disponibilita", response_model=DisponibilitaSlot)
def ottieni_disponibilita(data: str, ora: str, coperti: int | None = None, user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    return verifica_disponibilita(data, ora, coperti)


@app.get("/api/prenotazioni/semaforo", response_model=list[DisponibilitaSlot])
def ottieni_semaforo(data: str | None = None, user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    if data:
        return semaforo_giorno(data)
    return prossimi_giorni_semaforo()


@app.get("/api/prenotazioni/impostazioni")
def ottieni_impostazioni_prenotazioni(user: dict = Depends(require_ruolo("owner", "manager"))):
    return get_impostazioni_disponibilita()


@app.put("/api/prenotazioni/impostazioni")
async def salva_impostazioni_prenotazioni(impostazioni: ImpostazioniDisponibilitaInput, request: Request, user: dict = Depends(require_ruolo("owner", "manager"))):
    risultato = aggiorna_impostazioni_disponibilita(
        capienze_orarie=impostazioni.capienze_orarie,
        coperti_massimi_per_slot=impostazioni.coperti_massimi_per_slot,
        fasce_orarie=impostazioni.fasce_orarie,
    )
    await _audit(request, user, "impostazioni_prenotazioni_modificate", target_table="booking_settings",
                 details=impostazioni.model_dump())
    return risultato


@app.post("/api/recensione", response_model=RispostaRecensioneOutput)
def ricevi_recensione(recensione: RecensioneInput, user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    try:
        output = genera_risposta_recensione(
            testo=recensione.testo,
            stelle=recensione.valutazione_stelle,
            autore=recensione.autore,
        )
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Errore nella generazione della bozza risposta: {e}",
        )

    _storico_eventi.append(
        EventoDashboard(
            id=_prossimo_id("rec"),
            tipo_evento="recensione",
            timestamp=datetime.now(),
            priorita=calcola_priorita_recensione(recensione.valutazione_stelle, output),
            testo_originale=recensione.testo,
            risposta_ai=output.bozza_risposta,
            # La bozza e' stata generata dall'AI: l'eventuale revisione urgente
            # resta indicata nei dettagli e nella priorita, non come escalation.
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

    return output


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
def health_check():
    return {
        "status": "ok",
        "modello_configurato": os.getenv("OPENROUTER_MODEL", "non impostato"),
        "chiave_presente": bool(os.getenv("OPENROUTER_API_KEY")),
    }
