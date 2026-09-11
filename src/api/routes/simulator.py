"""Simulator, Chat Playground & AI Review Responder API Routes (Invarianti 1, 5, 7, 8, 10).

Gestisce:
- Simulatore chat interattivo (/api/messaggio) con instradamento su ConversationOrchestrator
- Generazione risposte e bozze per recensioni clienti (/api/recensione)
- Accounting token e costi AI budget-aware (Invariante 8)
- Storico eventi demo in-memory e isolamento rigoroso tenant (Invariante 1)
"""

import asyncio
import logging
import uuid
from datetime import datetime
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.dependencies import (
    get_orchestrator,
    get_optional_organization_context,
    get_organization_context,
    get_repo,
    require_ruolo,
)
from src.api.routes.common import (
    check_feature_blocked_by_plan,
    get_billing_snapshot,
    get_shared_event_history,
    next_event_id,
    record_ai_usage,
    resolve_genera_risposta_recensione,
)
from src.core.conversation_store import store as conv_store
from src.core.priorita import calcola_priorita, calcola_priorita_recensione
from src.core.receptionist.models import OrchestrationInput
from src.models.business_profile import PROFILI_DEMO
from src.models.schemas import (
    EventoDashboard,
    MessaggioInput,
    RecensioneInput,
    RispostaOutput,
    RispostaRecensioneOutput,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["simulator"])


@router.post("/api/messaggio", response_model=RispostaOutput)
async def ricevi_messaggio(
    request: Request,
    messaggio: MessaggioInput,
    profilo_id: str = "trattoria_da_mario",
):
    """Simulatore messaggi per playground UI e test di interazione AI (Invarianti 1, 5, 7, 8)."""
    # Se l'utente è autenticato nella dashboard, usa il profilo reale
    # dell'organizzazione (business_profile/onboarding) e il semaforo DB.
    # Altrimenti fallback al profilo demo statico (PROFILI_DEMO).
    org_id = None
    profilo = None
    repo = getattr(request.app.state, "repo", None)
    try:
        user = await get_optional_organization_context(request)
        if user and user.get("source") != "anonymous" and user.get("organization_id"):
            org_id = user["organization_id"]
            if repo:
                org_data = await repo.get_organization(org_id)
                if org_data and org_data.get("business_profile"):
                    from src.whatsapp.inbound_processor import _profile_from_dict
                    profilo = _profile_from_dict(
                        org_data["business_profile"],
                        fallback_name=org_data.get("name", "Attività"),
                    )
    except Exception as e:
        logger.warning("Profilo organizzazione non caricato per il simulatore (fallback demo): %s", e)

    if profilo is None:
        profilo = PROFILI_DEMO.get(profilo_id)
        if profilo is None:
            raise HTTPException(status_code=404, detail=f"Profilo '{profilo_id}' non trovato")

    # Cronologia del simulatore: la chiave e' client-controlled, quindi per
    # le org autenticate va namespaced per evitare incroci tra tenant.
    chiave_conv = f"{org_id}:{messaggio.id_conversazione}" if org_id else messaggio.id_conversazione
    cronologia = conv_store.recupera_cronologia(chiave_conv)

    # Billing snapshot per il routing budget-aware (invariante 8)
    billing = await get_billing_snapshot(repo, org_id)

    # Core AI Receptionist Orchestrator (Fase 2)
    orchestrator = get_orchestrator(request)

    req = OrchestrationInput(
        organization_id=org_id,
        conversation_id=messaggio.id_conversazione,
        text=messaggio.testo,
        channel="demo" if not org_id else "whatsapp",
        sender_phone=messaggio.telefono_mittente or "",
        business_profile=profilo,
        cronologia=cronologia,
        billing_state=billing,
        is_simulation=True,
        record_billing_usage=bool(org_id),
    )

    try:
        out = await orchestrator.orchestrate(req)
    except Exception as e:
        logger.error("Error generating AI response in ricevi_messaggio: %s", e)
        raise HTTPException(status_code=502, detail="Impossibile generare la risposta al momento. Riprova più tardi.")

    conv_store.aggiungi(chiave_conv, messaggio.testo, out.response_text)

    risposta = RispostaOutput(
        risposta=out.response_text,
        richiede_umano=out.richiede_umano,
        motivo=out.motivo_richiesta_umano or "",
        categoria=out.intent or "generico",
        prenotazione=out.prenotazione,
    )

    prenotazione_id = None
    pren = out.prenotazione
    if pren and pren.data and pren.ora and pren.coperti and not org_id:
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

    # Solo il percorso demo anonimo alimenta lo storico demo condiviso:
    # le org autenticate hanno i propri dati su DB.
    if not org_id:
        storico = get_shared_event_history()
        storico.append(
            EventoDashboard(
                id=next_event_id("msg"),
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
                    "prenotazione_simulata": out.disponibilita_slot,
                    "guardrail": out.guardrail_action,
                },
            )
        )
    return risposta


@router.post("/api/recensione", response_model=RispostaRecensioneOutput)
async def ricevi_recensione(
    recensione: RecensioneInput,
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
):
    """Genera una risposta AI per una recensione ricevuta e ne persiste lo stato (Invarianti 1, 8, 10)."""
    repo = get_repo(request)
    org_id = user.get("organization_id")
    blocco = await check_feature_blocked_by_plan(repo, org_id, "recensioni")
    if blocco:
        raise HTTPException(status_code=403, detail=blocco)
    billing = await get_billing_snapshot(repo, org_id)

    # Lingue dell'org dal profilo onboarding: se non esiste ancora (onboarding
    # non completato) si usano i default ["it"]/"it", nessun errore.
    profilazione = await repo.get_onboarding_profile(org_id) or {}
    lingue = profilazione.get("lingue_supportate") or None
    lingua_default = profilazione.get("lingua_default") or None

    genera_risposta_recensione = resolve_genera_risposta_recensione()
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
            logger.error("[recensione] Persistenza fallita org=%s external_id=%s: %s", org_id, recensione.external_id, e)
            raise HTTPException(status_code=502, detail="Impossibile salvare la recensione, riprova.")

    await record_ai_usage(
        repo,
        org_id,
        "review",
        recensione.testo,
        billing,
        {"fonte": recensione.fonte, "stelle": recensione.valutazione_stelle},
    )

    storico = get_shared_event_history()
    storico.append(
        EventoDashboard(
            id=next_event_id("rec"),
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
