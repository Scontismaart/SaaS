from fastapi import APIRouter, HTTPException
from dotenv import load_dotenv

from src.models.schemas import MessaggioInput, RispostaOutput, MessaggioDashboard
from src.models.business_profile import TRATTORIA_DA_MARIO
from src.core.crew_runner import genera_risposta_async

load_dotenv()

router = APIRouter()

messaggi_dashboard: list[MessaggioDashboard] = []


@router.post("/messaggio", response_model=RispostaOutput)
async def incoming_message(msg: MessaggioInput):
    try:
        risposta = await genera_risposta_async(msg, TRATTORIA_DA_MARIO)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    messaggi_dashboard.append(
        MessaggioDashboard(
            id_conversazione=msg.id_conversazione,
            testo_messaggio=msg.testo,
            risposta=risposta,
            timestamp=msg.timestamp,
            gestito_da_ai=not risposta.richiede_umano,
        )
    )

    return risposta


@router.get("/dashboard")
async def dashboard():
    totali = len(messaggi_dashboard)
    gestiti_ai = sum(1 for m in messaggi_dashboard if m.gestito_da_ai)
    escalation = totali - gestiti_ai
    return {
        "totale_messaggi": totali,
        "gestiti_da_ai": gestiti_ai,
        "escalation_umano": escalation,
        "messaggi": messaggi_dashboard[-20:],
    }
