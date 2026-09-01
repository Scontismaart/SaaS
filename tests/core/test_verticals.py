"""
test_verticals.py
-----------------
Unit test suite for the vertical modular strategy pattern.
Performs deterministic, offline validation of:
1. Registry & smart synonym resolution
2. Fallback policy on unknown/missing vertical
3. Terminology mapping for UI & reports
4. Booking enrichment and regex plural parsing for each vertical
5. Prompt structure and business invariant rules for each vertical
"""

import pytest
from src.core.verticals import (
    DEFAULT_VERTICAL_CODE,
    get_vertical_strategy,
    get_vertical_terminology,
    list_registered_verticals,
)
from src.core.verticals.base import BaseVerticalStrategy
from src.core.verticals.centro_estetico import CentroEsteticoVerticalStrategy
from src.core.verticals.hotel_bnb import HotelBnBVerticalStrategy
from src.core.verticals.parrucchiere import ParrucchiereVerticalStrategy
from src.core.verticals.ristorante import RistoranteVerticalStrategy
from src.core.verticals.studio_medico import StudioMedicoDentistaVerticalStrategy
from src.models.schemas import DatiPrenotazione, ProfiloAttivita


# =====================================================================
# 1. REGISTRY, SYNONYMS & FALLBACK TESTS
# =====================================================================

def test_registry_contains_all_five_verticals():
    verticals = list_registered_verticals()
    codes = {v["code"] for v in verticals}
    expected = {
        "ristorante",
        "parrucchiere",
        "centro_estetico",
        "hotel_bnb",
        "studio_medico_dentista",
    }
    assert codes == expected


def test_get_vertical_strategy_resolution():
    # Parrucchiere
    assert isinstance(get_vertical_strategy("parrucchiere"), ParrucchiereVerticalStrategy)
    assert isinstance(get_vertical_strategy("barber"), ParrucchiereVerticalStrategy)
    assert isinstance(get_vertical_strategy("barbiere"), ParrucchiereVerticalStrategy)
    assert isinstance(get_vertical_strategy("parrucchiera"), ParrucchiereVerticalStrategy)
    assert isinstance(get_vertical_strategy("salone"), ParrucchiereVerticalStrategy)
    
    # Ristorante
    assert isinstance(get_vertical_strategy("ristorante"), RistoranteVerticalStrategy)
    assert isinstance(get_vertical_strategy("pizzeria"), RistoranteVerticalStrategy)
    assert isinstance(get_vertical_strategy("trattoria"), RistoranteVerticalStrategy)
    assert isinstance(get_vertical_strategy("osteria"), RistoranteVerticalStrategy)
    assert isinstance(get_vertical_strategy("pub"), RistoranteVerticalStrategy)
    
    # Centro Estetico
    assert isinstance(get_vertical_strategy("centro_estetico"), CentroEsteticoVerticalStrategy)
    assert isinstance(get_vertical_strategy("estetista"), CentroEsteticoVerticalStrategy)
    assert isinstance(get_vertical_strategy("spa"), CentroEsteticoVerticalStrategy)
    assert isinstance(get_vertical_strategy("benessere"), CentroEsteticoVerticalStrategy)
    
    # Hotel / B&B
    assert isinstance(get_vertical_strategy("hotel_bnb"), HotelBnBVerticalStrategy)
    assert isinstance(get_vertical_strategy("hotel"), HotelBnBVerticalStrategy)
    assert isinstance(get_vertical_strategy("bnb"), HotelBnBVerticalStrategy)
    assert isinstance(get_vertical_strategy("b&b"), HotelBnBVerticalStrategy)
    assert isinstance(get_vertical_strategy("albergo"), HotelBnBVerticalStrategy)
    
    # Studio Medico / Dentista
    assert isinstance(get_vertical_strategy("studio_medico_dentista"), StudioMedicoDentistaVerticalStrategy)
    assert isinstance(get_vertical_strategy("studio_medico"), StudioMedicoDentistaVerticalStrategy)
    assert isinstance(get_vertical_strategy("dentista"), StudioMedicoDentistaVerticalStrategy)
    assert isinstance(get_vertical_strategy("odontoiatra"), StudioMedicoDentistaVerticalStrategy)
    assert isinstance(get_vertical_strategy("clinica"), StudioMedicoDentistaVerticalStrategy)


def test_get_vertical_strategy_fallback():
    # Sconosciuto o None deve cadere sul default registrato (ristorante)
    fallback = get_vertical_strategy("sconosciuto_xyz", organization_id="org-test")
    assert isinstance(fallback, RistoranteVerticalStrategy)
    assert fallback.code == DEFAULT_VERTICAL_CODE

    fallback_none = get_vertical_strategy(None)
    assert isinstance(fallback_none, RistoranteVerticalStrategy)


# =====================================================================
# 2. TERMINOLOGY & UI LABELS
# =====================================================================

def test_terminology_labels():
    term_parr = get_vertical_terminology("parrucchiere")
    assert term_parr.label_unita == "persona"
    assert term_parr.label_singolare == "appuntamento"

    term_rist = get_vertical_terminology("ristorante")
    assert term_rist.label_unita == "coperto"
    assert term_rist.label_singolare == "tavolo"

    term_est = get_vertical_terminology("centro_estetico")
    assert term_est.label_unita == "persona"
    assert term_est.label_singolare == "trattamento"

    term_hotel = get_vertical_terminology("hotel_bnb")
    assert term_hotel.label_unita == "ospite"
    assert term_hotel.label_singolare == "soggiorno"

    term_med = get_vertical_terminology("studio_medico_dentista")
    assert term_med.label_unita == "paziente"
    assert term_med.label_singolare == "visita"


# =====================================================================
# 3. ENRICHMENT & PARSING PER CIASCUN VERTICALE
# =====================================================================

def test_parrucchiere_booking_enrichment():
    strat = ParrucchiereVerticalStrategy()
    
    # 1. Singolare implicito -> default coperti=1
    pren1 = DatiPrenotazione(nome_cliente="Marco", data="2026-08-29", ora="20:00", coperti=None)
    res1 = strat.valida_e_arricchisci_prenotazione(pren1, "un taglio a nome Marco")
    assert res1.coperti == 1

    # 2. Plurale esplicito (due tagli) -> coperti=2
    pren2 = DatiPrenotazione(nome_cliente="Marco", data="2026-08-29", ora="20:00", coperti=None)
    res2 = strat.valida_e_arricchisci_prenotazione(pren2, "vorrei due tagli per me e mio figlio")
    assert res2.coperti == 2

    # 3. Plurale con 'io e mio figlio' -> coperti=2
    res3 = strat.valida_e_arricchisci_prenotazione(pren2, "prenota per io e mio figlio alle 17")
    assert res3.coperti == 2


def test_ristorante_booking_enrichment():
    strat = RistoranteVerticalStrategy()
    
    # Ristorante non forza default coperti se non menzionati
    pren1 = DatiPrenotazione(nome_cliente="Marco", data="2026-08-29", ora="20:00", coperti=None)
    res1 = strat.valida_e_arricchisci_prenotazione(pren1, "tavolo per domani alle 20")
    assert res1.coperti is None

    # Estrae il numero dal testo se presente ("tavolo per 4 persone")
    pren2 = DatiPrenotazione(nome_cliente="Marco", data="2026-08-29", ora="20:00", coperti=None)
    res2 = strat.valida_e_arricchisci_prenotazione(pren2, "tavolo per 4 persone")
    assert res2.coperti == 4

    # Estrae da "siamo in 6"
    pren3 = DatiPrenotazione(nome_cliente="Marco", data="2026-08-29", ora="20:00", coperti=None)
    res3 = strat.valida_e_arricchisci_prenotazione(pren3, "vorrei prenotare, siamo in 6")
    assert res3.coperti == 6


def test_centro_estetico_booking_enrichment():
    strat = CentroEsteticoVerticalStrategy()
    
    # Default 1 persona per trattamento singolo
    pren1 = DatiPrenotazione(nome_cliente="Sara", data="2026-08-29", ora="11:00", coperti=None)
    res1 = strat.valida_e_arricchisci_prenotazione(pren1, "manicure semipermanente domani alle 11")
    assert res1.coperti == 1

    # Massaggio di coppia -> coperti=2
    pren2 = DatiPrenotazione(nome_cliente="Sara", data="2026-08-29", ora="11:00", coperti=None)
    res2 = strat.valida_e_arricchisci_prenotazione(pren2, "vorrei un massaggio di coppia")
    assert res2.coperti == 2


def test_hotel_bnb_booking_enrichment():
    strat = HotelBnBVerticalStrategy()
    
    # Default doppia -> 2 ospiti
    pren1 = DatiPrenotazione(nome_cliente="Rossi", data="2026-09-10", ora="14:00", coperti=None)
    res1 = strat.valida_e_arricchisci_prenotazione(pren1, "camera matrimoniale dal 10 al 12 settembre")
    assert res1.coperti == 2

    # Camera singola -> 1 ospite
    pren2 = DatiPrenotazione(nome_cliente="Rossi", data="2026-09-10", ora="14:00", coperti=None)
    res_singola = strat.valida_e_arricchisci_prenotazione(pren2, "camera singola per 1 notte")
    assert res_singola.coperti == 1

    # Camera tripla -> 3 ospiti
    pren3 = DatiPrenotazione(nome_cliente="Rossi", data="2026-09-10", ora="14:00", coperti=None)
    res_tripla = strat.valida_e_arricchisci_prenotazione(pren3, "stanza tripla")
    assert res_tripla.coperti == 3


def test_studio_medico_booking_enrichment():
    strat = StudioMedicoDentistaVerticalStrategy()
    
    pren = DatiPrenotazione(nome_cliente="Laura", data="2026-09-03", ora="15:00", coperti=None)
    res = strat.valida_e_arricchisci_prenotazione(pren, "visita di controllo per Laura")
    assert res.coperti == 1


# =====================================================================
# 4. PROMPT INVARIANTS & SECTOR RULES FOR ALL 5 VERTICALS
# =====================================================================

def test_parrucchiere_prompt_invariants():
    profilo = ProfiloAttivita(
        nome="Barbershop Test", tipo_attivita="Salone di Parrucchiere / Barber",
        tono="curato", orari="Lun-Sab 09:00-19:00", servizi_principali=["Taglio", "Barba"],
        note_speciali=[], verticale="parrucchiere",
    )
    prompt = get_vertical_strategy(profilo.verticale).costruisci_system_prompt(profilo)
    assert "PARRUCCHIERE / BARBERSHOP" in prompt
    assert "1 PERSONA" in prompt
    assert "lavori_tecnici_complessi" in prompt


def test_ristorante_prompt_invariants():
    profilo = ProfiloAttivita(
        nome="Ristorante Test", tipo_attivita="Ristorante / Pizzeria",
        tono="cordiale", orari="Lun-Dom 19:00-23:30", servizi_principali=["Cena", "Pizza"],
        note_speciali=[], verticale="ristorante",
    )
    prompt = get_vertical_strategy(profilo.verticale).costruisci_system_prompt(profilo)
    assert "SETTORE RISTORAZIONE" in prompt
    assert "COPERTI (OBBLIGATORIO)" in prompt
    assert "tavolata_numerosa" in prompt
    assert "domanda_sicurezza_alimentare" in prompt


def test_centro_estetico_prompt_invariants():
    profilo = ProfiloAttivita(
        nome="Estetica Test", tipo_attivita="Centro Estetico / SPA",
        tono="delicato", orari="Lun-Sab 09:00-19:00", servizi_principali=["Manicure", "Massaggi"],
        note_speciali=[], verticale="centro_estetico",
    )
    prompt = get_vertical_strategy(profilo.verticale).costruisci_system_prompt(profilo)
    assert "CENTRO ESTETICO / SPA" in prompt
    assert "condizione_medica_gravidanza" in prompt


def test_hotel_bnb_prompt_invariants():
    profilo = ProfiloAttivita(
        nome="Hotel Test", tipo_attivita="Hotel / B&B",
        tono="accogliente", orari="Check-in 14:00-20:00", servizi_principali=["Camere"],
        note_speciali=[], verticale="hotel_bnb",
    )
    prompt = get_vertical_strategy(profilo.verticale).costruisci_system_prompt(profilo)
    assert "HOSPITALITY / HOTEL / B&B" in prompt
    assert "CHECK-IN E CHECK-OUT" in prompt
    assert "richiesta_rimborso_cancellazione" in prompt


def test_studio_medico_prompt_invariants():
    profilo = ProfiloAttivita(
        nome="Studio Medico Test", tipo_attivita="Studio Medico / Dentista",
        tono="prudente", orari="Lun-Ven 09:00-19:00", servizi_principali=["Visite"],
        note_speciali=[], verticale="studio_medico_dentista",
    )
    prompt = get_vertical_strategy(profilo.verticale).costruisci_system_prompt(profilo)
    assert "SETTORE MEDICO / ODONTOIATRICO" in prompt
    assert "FAIL-CLOSED MEDICO ASSOLUTO" in prompt
    assert "sintomi_urgenza_medica" in prompt
    assert "112" in prompt
