from datetime import datetime
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator

# Lingue supportate dal bot (task 14): lista chiusa, vocabolario massimo.
# IT e' sempre inclusa ed e' la lingua di default; il Titolare restringe la
# lista dal wizard onboarding. Il rilevamento lingua e' delegato al LLM nel
# system prompt (nessuna libreria), la policy dipende dal verticale.
LINGUE_DISPONIBILI = frozenset({"it", "en", "fr", "de", "es"})
LINGUA_DEFAULT = "it"


class CanaleMessaggio(str, Enum):
    DEMO = "demo"
    WHATSAPP = "whatsapp"
    INSTAGRAM = "instagram"


class MessaggioInput(BaseModel):
    testo: str
    canale: CanaleMessaggio = Field(default=CanaleMessaggio.DEMO)
    timestamp: datetime = Field(default_factory=datetime.now)
    id_conversazione: str = Field(default="demo-001")


class DatiPrenotazione(BaseModel):
    nome_cliente: str = Field(default="")
    telefono: str = Field(default="")
    data: str = Field(default="")
    ora: str = Field(default="")
    coperti: int | None = Field(default=None)
    note: str = Field(default="")


class PrenotazioneManualeInput(DatiPrenotazione):
    stato: str = Field(default="Confermato")
    origine: str = Field(default="Dashboard")


class PrenotazioneCalendario(BaseModel):
    id: str
    nome_cliente: str = ""
    telefono: str = ""
    data: str = ""
    ora: str = ""
    coperti: int | None = None
    note: str = ""
    stato: str = "In attesa"
    origine: str = "Dashboard"
    richiede_intervento: bool = False


class DisponibilitaSlot(BaseModel):
    data: str
    ora: str
    coperti_massimi: int
    coperti_prenotati: int
    coperti_liberi: int
    stato: Literal["verde", "giallo", "rosso"]
    alternative: list[str] = Field(default_factory=list)


class ImpostazioniDisponibilitaInput(BaseModel):
    capienze_orarie: dict[str, int] = Field(default_factory=dict)
    # Campi mantenuti per compatibilita con le configurazioni precedenti.
    coperti_massimi_per_slot: int = Field(default=40, ge=0, le=500)
    fasce_orarie: list[str] = Field(default_factory=list)


class RispostaOutput(BaseModel):
    risposta: str
    richiede_umano: bool
    motivo: str
    categoria: str = Field(default="generico")
    prenotazione: DatiPrenotazione | None = Field(default=None)


class Priorita(str, Enum):
    ALTA = "alta"
    MEDIA = "media"
    BASSA = "bassa"


class ProfiloAttivita(BaseModel):
    nome: str
    tipo_attivita: str
    tono: str
    orari: str
    servizi_principali: list[str] = Field(default_factory=list)
    note_speciali: list[str] = Field(default_factory=list)
    # Multilingua (task 14): lingue supportate dall'attivita' e lingua di
    # default. verticale (opzionale) serve al prompt per decidere la policy
    # su lingue non supportate: best-effort ovunque, escalation a umano per
    # studio_medico_dentista (conseguenze cliniche degli errori di traduzione).
    lingue_supportate: list[str] = Field(default_factory=lambda: [LINGUA_DEFAULT])
    lingua_default: str = LINGUA_DEFAULT
    verticale: str | None = None


VerticaleOnboarding = Literal[
    "ristorante",
    "parrucchiere",
    "hotel_bnb",
    "centro_estetico",
    "studio_medico_dentista",
]


class OnboardingProfileInput(BaseModel):
    id: str | None = None
    verticale: VerticaleOnboarding
    nome_attivita: str = Field(min_length=2, max_length=120)
    orari: str = Field(min_length=2, max_length=1000)
    tono: str = Field(default="", max_length=400)
    servizi: list[str] = Field(default_factory=list)
    regole_escalation: list[str] = Field(default_factory=list)
    whatsapp_collegato: bool = False
    documenti_importati: bool = False
    # Multilingua (task 14): lista chiusa, "it" sempre inclusa e di default.
    lingue_supportate: list[str] = Field(default_factory=lambda: [LINGUA_DEFAULT])
    lingua_default: str = LINGUA_DEFAULT

    @field_validator("lingue_supportate")
    @classmethod
    def _lingue_supportate_valide(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("almeno una lingua supportata")
        sconosciute = set(value) - LINGUE_DISPONIBILI
        if sconosciute:
            raise ValueError(f"lingue non supportate: {sorted(sconosciute)}")
        if LINGUA_DEFAULT not in value:
            raise ValueError("'it' e' sempre inclusa tra le lingue supportate")
        return list(dict.fromkeys(value))

    @field_validator("lingua_default")
    @classmethod
    def _lingua_default_valida(cls, value: str) -> str:
        if value not in LINGUE_DISPONIBILI:
            raise ValueError(f"lingua di default non supportata: {value}")
        return value

    @model_validator(mode="after")
    def _lingua_default_tra_supportate(self):
        if self.lingua_default not in self.lingue_supportate:
            raise ValueError(
                f"lingua di default '{self.lingua_default}' non e' tra le lingue supportate"
            )
        return self


class PreviewInput(BaseModel):
    profilo: OnboardingProfileInput
    messaggio: str = Field(min_length=1, max_length=1000)


class WhatsAppBusinessProfile(BaseModel):
    nome: str | None = None
    tipo_attivita: str | None = None
    tono: str | None = None
    orari: str | None = None
    servizi_principali: list[str] | None = None
    note_speciali: list[str] | None = None
    # Multilingua (task 14): stessi campi di ProfiloAttivita, opzionali per
    # compatibilita' con i business_profile salvati prima della migration 033.
    lingue_supportate: list[str] | None = None
    lingua_default: str | None = None
    verticale: str | None = None


VALID_STATI_RECENSIONE = frozenset({
    "nuova", "bozza_generata", "approvata", "pubblicata", "errore", "conflitto",
})

class RecensioneInput(BaseModel):
    testo: str
    valutazione_stelle: int | None = Field(default=None, ge=1, le=5)
    fonte: str = Field(default="manuale")
    autore: str = Field(default="")
    external_id: str | None = Field(default=None)


class RispostaRecensioneOutput(BaseModel):
    id: str
    stato: str
    bozza_risposta: str
    sentiment: str
    richiede_revisione_urgente: bool
    motivo: str
    categoria: str


class ConfiguraEmailInput(BaseModel):
    indirizzo: str


class DomandaInput(BaseModel):
    domanda: str
    k: int = 5


class CaricaDocumentoInput(BaseModel):
    testo: str
    nome: str = "documento.txt"


class RispostaDocumento(BaseModel):
    risposta: str
    fonti: list[dict] = Field(default_factory=list)


class EventoDashboard(BaseModel):
    id: str
    tipo_evento: Literal["messaggio", "recensione"]
    timestamp: datetime
    priorita: Priorita
    testo_originale: str
    risposta_ai: str
    gestito_da_ai: bool
    dettagli: dict = Field(default_factory=dict)


class StatisticheReport(BaseModel):
    periodo: str
    totale_messaggi: int = 0
    gestiti_da_ai: int = 0
    girati_a_umano: int = 0
    categorie: dict[str, int] = Field(default_factory=dict)
    esempi_per_categoria: dict[str, list[str]] = Field(default_factory=dict)


class ReportOutput(BaseModel):
    data: str
    statistiche: StatisticheReport
    analisi_testuale: str
    suggerimenti: list[str] = Field(default_factory=list)
    generato_il: str
