from typing import Any

from src.core.crew_runner import genera_risposta_async
from src.core.documenti.rag_context import recupera_contesto_documenti
from src.models.schemas import (
    MessaggioInput,
    OnboardingProfileInput,
    PreviewInput,
    ProfiloAttivita,
    RispostaOutput,
)


VERTICAL_TEMPLATES: dict[str, dict[str, Any]] = {
    "ristorante": {
        "label": "Ristorante",
        "tono": "caldo, diretto, familiare",
        "servizi": [
            "Pranzo e cena",
            "Prenotazioni tavoli",
            "Menu e carta vini",
            "Eventi privati su richiesta",
        ],
        "escalation": [
            "Allergie o intolleranze specifiche",
            "Gruppi numerosi o eventi privati",
            "Reclami su esperienze passate",
            "Richieste non presenti nel menu caricato",
        ],
        "esempio": "Avete posto per 4 domani sera?",
    },
    "parrucchiere": {
        "label": "Parrucchiere / Barber",
        "tono": "curato, rassicurante, pratico",
        "servizi": [
            "Taglio donna e uomo",
            "Piega",
            "Colore e tonalizzante",
            "Trattamenti cute e capelli",
        ],
        "escalation": [
            "Correzioni colore o lavori tecnici complessi",
            "Reazioni cutanee o problemi dermatologici",
            "Preventivi senza consulenza",
            "Reclami su servizi precedenti",
        ],
        "esempio": "Quanto dura un colore e piega?",
    },
    "hotel_bnb": {
        "label": "Hotel / B&B",
        "tono": "accogliente, preciso, ospitale",
        "servizi": [
            "Check-in e check-out",
            "Camere e disponibilita",
            "Colazione",
            "Indicazioni e servizi locali",
        ],
        "escalation": [
            "Modifiche o cancellazioni prenotazioni",
            "Richieste di rimborso",
            "Problemi durante il soggiorno",
            "Richieste accessibilita specifiche",
        ],
        "esempio": "A che ora posso fare check-in?",
    },
    "centro_estetico": {
        "label": "Centro estetico",
        "tono": "delicato, professionale, chiaro",
        "servizi": [
            "Manicure e pedicure",
            "Ceretta",
            "Trattamenti viso",
            "Massaggi e percorsi corpo",
        ],
        "escalation": [
            "Gravidanza, allergie o condizioni mediche",
            "Trattamenti invasivi o controindicazioni",
            "Reazioni dopo un trattamento",
            "Richieste di diagnosi",
        ],
        "esempio": "Posso fare un trattamento viso se ho pelle sensibile?",
    },
    "studio_medico_dentista": {
        "label": "Studio medico / dentista",
        "tono": "calmo, istituzionale, prudente",
        "servizi": [
            "Prenotazione visite",
            "Informazioni su orari e sede",
            "Promemoria appuntamenti",
            "Indicazioni amministrative",
        ],
        "escalation": [
            "Sintomi, diagnosi o consigli clinici",
            "Dolore acuto o urgenze",
            "Farmaci, terapie o referti",
            "Dati sanitari sensibili",
        ],
        "esempio": "Ho dolore a un dente, cosa posso prendere?",
    },
}


def list_verticals() -> list[dict[str, Any]]:
    return [
        {
            "id": key,
            "label": value["label"],
            "tono": value["tono"],
            "servizi": value["servizi"],
            "escalation": value["escalation"],
            "esempio": value["esempio"],
        }
        for key, value in VERTICAL_TEMPLATES.items()
    ]


def build_business_profile(payload: OnboardingProfileInput) -> ProfiloAttivita:
    template = VERTICAL_TEMPLATES[payload.verticale]
    servizi = payload.servizi or template["servizi"]
    escalation = payload.regole_escalation or template["escalation"]
    tono = payload.tono or template["tono"]
    return ProfiloAttivita(
        nome=payload.nome_attivita,
        tipo_attivita=template["label"],
        tono=tono,
        orari=payload.orari,
        servizi_principali=servizi,
        note_speciali=escalation,
    )


async def get_profile(organization_id: str, repo) -> dict | None:
    """Profilo onboarding dell'org, oppure None se mai salvato.
    Org-scoped: il chiamante passa SEMPRE l'organization_id dell'utente."""
    return await repo.get_onboarding_profile(organization_id)


async def save_profile(
    organization_id: str,
    payload: OnboardingProfileInput,
    repo,
) -> dict:
    """Persiste il profilo onboarding dell'org e sincronizza
    organizations.business_profile (usato dal responder WhatsApp reale)."""
    profile = build_business_profile(payload)
    return await repo.save_onboarding_profile(
        organization_id,
        payload.verticale,
        payload.nome_attivita,
        payload.orari,
        payload.tono,
        payload.servizi,
        payload.regole_escalation,
        payload.whatsapp_collegato,
        payload.documenti_importati,
        profile.model_dump(),
    )


async def generate_preview(
    organization_id: str,
    payload: PreviewInput,
    repo,
    billing: dict | None = None,
) -> RispostaOutput:
    """Preview reale: costruisce il profilo dal payload del wizard e lo fa
    girare nel vero responder (crew + LLM), arricchito dal contesto RAG dei
    documenti dell'org. Se l'org non ha ancora documenti indicizzati il
    contesto e' vuoto e la preview procede comunque (nessun errore)."""
    profilo = build_business_profile(payload.profilo)

    contesto_documenti = await recupera_contesto_documenti(
        organization_id, payload.messaggio, repo
    )

    messaggio = MessaggioInput(testo=payload.messaggio)
    return await genera_risposta_async(
        messaggio,
        profilo,
        billing=billing,
        contesto_documenti=contesto_documenti,
    )