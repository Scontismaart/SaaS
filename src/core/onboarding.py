import json
import re
import uuid
from pathlib import Path
from typing import Any

from src.models.schemas import (
    OnboardingProfileInput,
    PreviewInput,
    ProfiloAttivita,
    RispostaOutput,
)


PROFILE_STORE = Path("data/onboarding_profiles.json")


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


def _ensure_store_dir() -> None:
    PROFILE_STORE.parent.mkdir(parents=True, exist_ok=True)


def _read_store() -> dict[str, Any]:
    if not PROFILE_STORE.exists():
        return {"active_profile_id": None, "profiles": {}}
    try:
        return json.loads(PROFILE_STORE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"active_profile_id": None, "profiles": {}}


def _write_store(data: dict[str, Any]) -> None:
    _ensure_store_dir()
    PROFILE_STORE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


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


def save_profile(payload: OnboardingProfileInput) -> dict[str, Any]:
    store = _read_store()
    profile_id = payload.id or f"{payload.verticale}-{uuid.uuid4().hex[:8]}"
    profile = build_business_profile(payload)
    record = {
        "id": profile_id,
        "verticale": payload.verticale,
        "nome_attivita": payload.nome_attivita,
        "orari": payload.orari,
        "tono": payload.tono,
        "servizi": payload.servizi,
        "regole_escalation": payload.regole_escalation,
        "whatsapp_collegato": payload.whatsapp_collegato,
        "documenti_importati": payload.documenti_importati,
        "profilo": profile.model_dump(),
    }
    store.setdefault("profiles", {})[profile_id] = record
    store["active_profile_id"] = profile_id
    _write_store(store)
    return record


def get_active_profile() -> ProfiloAttivita | None:
    store = _read_store()
    profile_id = store.get("active_profile_id")
    if not profile_id:
        return None
    record = store.get("profiles", {}).get(profile_id)
    if not record:
        return None
    return ProfiloAttivita(**record["profilo"])


def get_active_profile_record() -> dict[str, Any] | None:
    store = _read_store()
    profile_id = store.get("active_profile_id")
    if not profile_id:
        return None
    return store.get("profiles", {}).get(profile_id)


def reset_profiles() -> None:
    _write_store({"active_profile_id": None, "profiles": {}})


def generate_preview(payload: PreviewInput) -> RispostaOutput:
    profile = build_business_profile(payload.profilo)
    text = payload.messaggio.lower()
    escalation_terms = " ".join(profile.note_speciali).lower()
    matched_escalation = any(
        term in text or term in escalation_terms
        for term in [
            "allerg",
            "dolore",
            "farmac",
            "refert",
            "rimborso",
            "reclamo",
            "gravid",
            "diagnosi",
            "urgen",
            "15 persone",
            "evento",
        ]
    )
    if matched_escalation:
        return RispostaOutput(
            risposta=(
                "Grazie per averci scritto. Per questa richiesta ti metto in "
                "contatto con una persona dello staff, cosi ricevi una risposta corretta."
            ),
            richiede_umano=True,
            motivo="regola_escalation_verticale",
            categoria="escalation",
        )
    if re.search(r"\b(orari|aperti|chiusi|check-in|check in|check-out|dove)\b", text):
        return RispostaOutput(
            risposta=f"Certo. {profile.nome} segue questi orari: {profile.orari}",
            richiede_umano=False,
            motivo="informazione_presente_nel_profilo",
            categoria="informazioni",
        )
    servizi = ", ".join(profile.servizi_principali[:3])
    return RispostaOutput(
        risposta=(
            f"Certo, posso aiutarti. Da {profile.nome} gestiamo: {servizi}. "
            "Dimmi giorno e preferenza, oppure scrivici cosa ti serve."
        ),
        richiede_umano=False,
        motivo="richiesta_generica_gestibile",
        categoria="generico",
    )
