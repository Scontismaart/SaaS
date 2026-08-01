from datetime import datetime
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field


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
