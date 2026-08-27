import os
import pytest
from datetime import datetime

from src.models.business_profile import PROFILI_DEMO
from src.models.schemas import MessaggioInput
from src.core.crew_runner import genera_risposta
from src.agents.prompts import (
    costruisci_system_prompt,
    estrai_date_da_testo,
    formatta_disponibilita,
)

REQUIRES_OPENROUTER = pytest.mark.skipif(
    not os.getenv("OPENROUTER_API_KEY"),
    reason="Richiede OPENROUTER_API_KEY per invocare la crew LLM reale",
)


def test_estrai_date_da_testo():
    """Verifica che estrai_date_da_testo estragga correttamente date relative e assolute."""
    oggi = datetime.now().date().isoformat()
    assert oggi in estrai_date_da_testo("vorrei prenotare per stasera")
    assert oggi in estrai_date_da_testo("avete posto per oggi?")
    assert len(estrai_date_da_testo("domani a pranzo per 4")) == 1
    assert len(estrai_date_da_testo("ci vediamo 2026-10-15")) == 1
    assert estrai_date_da_testo("ci vediamo 2026-10-15")[0] == "2026-10-15"


@REQUIRES_OPENROUTER
def test_scenario_1_mancano_ora_e_coperti():
    """Scenario 1: cliente scrive 'vorrei prenotare per stasera' (manca ora e coperti)
    -> assistente chiede entrambi, non fa escalation."""
    profilo = PROFILI_DEMO["trattoria_da_mario"]
    msg = MessaggioInput(testo="vorrei prenotare per stasera")

    risposta = genera_risposta(msg, profilo, cronologia=[])
    assert risposta.richiede_umano is False
    assert risposta.categoria == "prenotazione"
    # L'assistente deve chiedere ora e/o coperti
    testo_risposta = risposta.risposta.lower()
    assert any(k in testo_risposta for k in ["ora", "orario", "persone", "quanti", "quante", "coperti"])


@REQUIRES_OPENROUTER
def test_scenario_2_slot_pieno_propone_alternative():
    """Scenario 2: cliente chiede orario che risulta pieno nel semaforo
    -> assistente non crea la prenotazione, propone alternative reali dal semaforo."""
    profilo = PROFILI_DEMO["trattoria_da_mario"]
    msg = MessaggioInput(testo="Vorrei un tavolo per 4 stasera alle 20:00 a nome Mario")

    # Simuliamo disponibilità con slot 20:00 rosso e alternative 19:00 e 21:00
    slots_demo = [
        {"data": datetime.now().strftime("%Y-%m-%d"), "ora": "19:00", "coperti_massimi": 40, "coperti_prenotati": 10, "coperti_liberi": 30, "stato": "verde", "alternative": []},
        {"data": datetime.now().strftime("%Y-%m-%d"), "ora": "20:00", "coperti_massimi": 40, "coperti_prenotati": 40, "coperti_liberi": 0, "stato": "rosso", "alternative": ["19:00", "21:00"]},
        {"data": datetime.now().strftime("%Y-%m-%d"), "ora": "21:00", "coperti_massimi": 40, "coperti_prenotati": 15, "coperti_liberi": 25, "stato": "verde", "alternative": []},
    ]
    contesto_disp = formatta_disponibilita(slots_demo)

    risposta = genera_risposta(msg, profilo, cronologia=[], contesto_disponibilita=contesto_disp)
    # Non deve confermare direttamente per le 20:00 senza avvisare
    testo_risposta = risposta.risposta.lower()
    assert any(k in testo_risposta for k in ["completo", "pieno", "non abbiamo", "dispiace", "occupato", "19", "21"])


@REQUIRES_OPENROUTER
def test_scenario_3_richiesta_esplicita_umano():
    """Scenario 3: cliente chiede esplicitamente di parlare con una persona
    -> escalation immediata."""
    profilo = PROFILI_DEMO["trattoria_da_mario"]
    msg = MessaggioInput(testo="Vorrei parlare con una persona dello staff per favore")

    risposta = genera_risposta(msg, profilo, cronologia=[])
    assert risposta.richiede_umano is True
    assert any(k in risposta.motivo.lower() for k in ["operatore", "umano", "staff", "richiesta_esplicita"])


@REQUIRES_OPENROUTER
def test_scenario_4_tre_tentativi_falliti_escalation():
    """Scenario 4: 3 tentativi falliti di raccogliere i dati
    -> escalation con contesto di cosa manca ancora."""
    profilo = PROFILI_DEMO["trattoria_da_mario"]
    msg = MessaggioInput(testo="Non lo so ancora")

    cronologia = [
        ("Vorrei prenotare un tavolo", "Certamente! Per quale giorno, quante persone e a che ora vorreste venire?"),
        ("Non saprei", "Per poterti aiutare a prenotare, mi servirebbe sapere il giorno e l'orario."),
        ("Boh", "Ho bisogno di sapere almeno la data e l'ora desiderata per la prenotazione."),
    ]

    risposta = genera_risposta(
        msg, profilo, cronologia=cronologia, tentativi_falliti=3
    )
    assert risposta.richiede_umano is True
    assert any(k in risposta.motivo.lower() for k in ["tentativ", "mancanti", "dati"])


@REQUIRES_OPENROUTER
def test_nome_mancante_chiede_nome():
    """Punto 1: se mancano solo il nome ma ci sono data, ora e coperti, chiede il nome."""
    profilo = PROFILI_DEMO["trattoria_da_mario"]
    msg = MessaggioInput(testo="Vorrei un tavolo per 4 stasera alle 20:30")
    risposta = genera_risposta(msg, profilo, cronologia=[])
    assert risposta.richiede_umano is False
    assert any(k in risposta.risposta.lower() for k in ["nome", "chi", "segnare", "intestare"])


@REQUIRES_OPENROUTER
def test_allergia_dettaglio_prenotazione_procede():
    """Punto 3: allergia come dettaglio prenotazione va in note e NON fa escalation."""
    profilo = PROFILI_DEMO["trattoria_da_mario"]
    msg = MessaggioInput(testo="Vorrei prenotare un tavolo per 2 stasera alle 20 a nome Luca Rossi. Nota: uno di noi è celiaco")
    risposta = genera_risposta(msg, profilo, cronologia=[])
    assert risposta.richiede_umano is False
    assert risposta.prenotazione is not None
    assert "celiac" in risposta.prenotazione.note.lower() or "senza glutine" in risposta.prenotazione.note.lower() or "allerg" in risposta.prenotazione.note.lower()


@REQUIRES_OPENROUTER
def test_garanzia_sicurezza_alimentare_fa_escalation():
    """Punto 3: richiesta di garanzia medica/zero contaminazione fa escalation."""
    profilo = PROFILI_DEMO["trattoria_da_mario"]
    msg = MessaggioInput(testo="Potete garantire al 100% l'assenza totale di contaminazione per un allergico grave con shock anafilattico?")
    risposta = genera_risposta(msg, profilo, cronologia=[])
    assert risposta.richiede_umano is True
    assert any(k in risposta.motivo.lower() for k in ["sicurezza", "alimentare", "allerg", "contaminazion", "garanzia", "medica"])

