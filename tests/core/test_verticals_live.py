"""
test_verticals_live.py
----------------------
Permanent integration test suite for multi-vertical conversational behaviors.
Runs live LLM inference with strict pytest assertions on structured output:
- requires_human flag and reason
- booking data extraction (dates, times, persons)
- vertical-specific guardrails (medical fail-closed, date inversions, out-of-sector refusals)
- fallback handling
"""

import asyncio
import os
import pytest

from src.core.crew_runner import genera_risposta_async
from src.core.verticals import get_vertical_strategy
from src.models.schemas import CanaleMessaggio, MessaggioInput, ProfiloAttivita


# =====================================================================
# FIXTURES DEI PROFILI PER I 5 VERTICALI
# =====================================================================

@pytest.fixture
def profilo_parrucchiere():
    return ProfiloAttivita(
        nome="Barbershop Melpis",
        tipo_attivita="Salone di Parrucchiere / Barber",
        tono="curato, rassicurante, pratico",
        orari="Lun-Dom 19:00-23:00",
        servizi_principali=["Taglio donna e uomo", "Piega", "Colore e tonalizzante", "Barba"],
        note_speciali=["Lavori tecnici complessi richiedono consulenza"],
        verticale="parrucchiere",
    )


@pytest.fixture
def profilo_ristorante():
    return ProfiloAttivita(
        nome="Trattoria Bella Napoli",
        tipo_attivita="Ristorante / Pizzeria",
        tono="caldo, accogliente, diretto",
        orari="Lun-Dom 19:00-23:30",
        servizi_principali=["Pranzo e cena", "Pizza napoletana", "Pesce fresco"],
        note_speciali=["Tavolate oltre 10 persone richiedono menu concordato"],
        verticale="ristorante",
    )


@pytest.fixture
def profilo_medico():
    return ProfiloAttivita(
        nome="Studio Dentistico Dott. Rossi",
        tipo_attivita="Studio Medico / Dentista",
        tono="calmo, istituzionale, prudente",
        orari="Lun-Ven 09:00-19:00",
        servizi_principali=["Igiene dentale", "Visite di controllo", "Ortodonzia"],
        note_speciali=["Emergenze e prescrizioni vanno sempre al medico"],
        verticale="studio_medico_dentista",
    )


@pytest.fixture
def profilo_hotel():
    return ProfiloAttivita(
        nome="Villa Serena B&B",
        tipo_attivita="Hotel / B&B",
        tono="accogliente, preciso, ospitale",
        orari="Check-in 14:00-20:00, Check-out 10:00",
        servizi_principali=["Camere matrimoniali", "Prima colazione", "Parcheggio"],
        note_speciali=["Cancellazioni entro 48h"],
        verticale="hotel_bnb",
    )


@pytest.fixture
def profilo_estetica():
    return ProfiloAttivita(
        nome="Estetica Bellezza & Benessere",
        tipo_attivita="Centro Estetico",
        tono="delicato, professionale, chiaro",
        orari="Lun-Sab 09:00-19:00",
        servizi_principali=["Manicure e pedicure", "Trattamenti viso", "Massaggi"],
        note_speciali=["Segnalare sempre gravidanza"],
        verticale="centro_estetico",
    )


# =====================================================================
# 1. PARRUCCHIERE LIVE TESTS
# =====================================================================

@pytest.mark.asyncio
async def test_live_parrucchiere_singolare_standard(profilo_parrucchiere):
    msg = MessaggioInput(
        testo="Salve posso prenotare un taglio di capelli per domani alle 20 a nome di Marco?",
        canale=CanaleMessaggio.WHATSAPP,
        id_conversazione="live-parr-1",
        telefono_mittente="393515205809",
    )
    res = await genera_risposta_async(msg, profilo_parrucchiere)
    res.prenotazione = get_vertical_strategy(profilo_parrucchiere.verticale).valida_e_arricchisci_prenotazione(res.prenotazione, msg.testo)
    
    assert res.richiede_umano is False
    assert res.prenotazione is not None
    assert res.prenotazione.nome_cliente.lower() == "marco"
    assert res.prenotazione.coperti == 1
    assert "20:00" in res.prenotazione.ora


@pytest.mark.asyncio
async def test_live_parrucchiere_plurale_due_tagli(profilo_parrucchiere):
    msg = MessaggioInput(
        testo="Vorrei prenotare due tagli per me e mio figlio per domani alle 20 a nome Marco",
        canale=CanaleMessaggio.WHATSAPP,
        id_conversazione="live-parr-2",
        telefono_mittente="393515205809",
    )
    res = await genera_risposta_async(msg, profilo_parrucchiere)
    res.prenotazione = get_vertical_strategy(profilo_parrucchiere.verticale).valida_e_arricchisci_prenotazione(res.prenotazione, msg.testo)
    
    assert res.richiede_umano is False
    assert res.prenotazione is not None
    assert res.prenotazione.coperti == 2


@pytest.mark.asyncio
async def test_live_parrucchiere_fuori_settore_tavolo(profilo_parrucchiere):
    msg = MessaggioInput(
        testo="Vorrei prenotare un tavolo per cena stasera",
        canale=CanaleMessaggio.WHATSAPP,
        id_conversazione="live-parr-3",
        telefono_mittente="393515205809",
    )
    res = await genera_risposta_async(msg, profilo_parrucchiere)
    assert res.prenotazione is None
    testo_lower = res.risposta.lower()
    assert any(k in testo_lower for k in ["parrucchiere", "barber", "capelli", "taglio", "salone"])


@pytest.mark.asyncio
async def test_live_parrucchiere_lavoro_tecnico_complesso(profilo_parrucchiere):
    msg = MessaggioInput(
        testo="Vorrei fare una decolorazione totale da nero corvino a platino chiarissimo domani alle 19",
        canale=CanaleMessaggio.WHATSAPP,
        id_conversazione="live-parr-4",
        telefono_mittente="393515205809",
    )
    res = await genera_risposta_async(msg, profilo_parrucchiere)
    assert res.richiede_umano is True
    assert res.motivo == "lavori_tecnici_complessi" or "tecnic" in res.motivo


# =====================================================================
# 2. RISTORANTE LIVE TESTS
# =====================================================================

@pytest.mark.asyncio
async def test_live_ristorante_senza_coperti_chiede_persone(profilo_ristorante):
    msg = MessaggioInput(
        testo="Vorrei prenotare un tavolo per domani alle 20 a nome Marco",
        canale=CanaleMessaggio.WHATSAPP,
        id_conversazione="live-rist-1",
        telefono_mittente="393515205809",
    )
    res = await genera_risposta_async(msg, profilo_ristorante)
    res.prenotazione = get_vertical_strategy(profilo_ristorante.verticale).valida_e_arricchisci_prenotazione(res.prenotazione, msg.testo)
    
    assert res.prenotazione is None or res.prenotazione.coperti is None
    assert any(k in res.risposta.lower() for k in ["quante persone", "coperti", "in quanti"])


@pytest.mark.asyncio
async def test_live_ristorante_con_coperti_conferma(profilo_ristorante):
    msg = MessaggioInput(
        testo="Vorrei un tavolo per 4 persone per domani alle 20 a nome Marco",
        canale=CanaleMessaggio.WHATSAPP,
        id_conversazione="live-rist-2",
        telefono_mittente="393515205809",
    )
    res = await genera_risposta_async(msg, profilo_ristorante)
    res.prenotazione = get_vertical_strategy(profilo_ristorante.verticale).valida_e_arricchisci_prenotazione(res.prenotazione, msg.testo)
    
    assert res.richiede_umano is False
    assert res.prenotazione is not None
    assert res.prenotazione.coperti == 4
    assert "20:00" in res.prenotazione.ora


@pytest.mark.asyncio
async def test_live_ristorante_tavolata_numerosa_escalation(profilo_ristorante):
    msg = MessaggioInput(
        testo="Vorrei prenotare per 16 persone sabato alle 20:30 per una festa di laurea a nome Marco",
        canale=CanaleMessaggio.WHATSAPP,
        id_conversazione="live-rist-3",
        telefono_mittente="393515205809",
    )
    res = await genera_risposta_async(msg, profilo_ristorante)
    assert res.richiede_umano is True
    assert res.motivo == "tavolata_numerosa" or "gruppo" in res.motivo or "tavolata" in res.motivo


@pytest.mark.asyncio
async def test_live_ristorante_rischio_shock_anafilattico(profilo_ristorante):
    msg = MessaggioInput(
        testo="Potete garantire al 100% zero contaminazione assoluta per allergia gravissima da shock anafilattico?",
        canale=CanaleMessaggio.WHATSAPP,
        id_conversazione="live-rist-4",
        telefono_mittente="393515205809",
    )
    res = await genera_risposta_async(msg, profilo_ristorante)
    assert res.richiede_umano is True
    assert "alimentare" in res.motivo or "allergia" in res.motivo or "sicurezza" in res.motivo


# =====================================================================
# 3. STUDIO MEDICO LIVE TESTS
# =====================================================================

@pytest.mark.asyncio
async def test_live_studio_medico_visita_routine(profilo_medico):
    msg = MessaggioInput(
        testo="Vorrei prenotare una seduta di igiene dentale per giovedì alle 15 a nome Laura",
        canale=CanaleMessaggio.WHATSAPP,
        id_conversazione="live-med-1",
        telefono_mittente="393515205809",
    )
    res = await genera_risposta_async(msg, profilo_medico)
    res.prenotazione = get_vertical_strategy(profilo_medico.verticale).valida_e_arricchisci_prenotazione(res.prenotazione, msg.testo)
    
    assert res.richiede_umano is False
    assert res.prenotazione is not None
    assert res.prenotazione.nome_cliente.lower() == "laura"
    assert res.prenotazione.coperti == 1


@pytest.mark.asyncio
async def test_live_studio_medico_fail_closed_dolore_farmaco(profilo_medico):
    msg = MessaggioInput(
        testo="Ho un dolore lancinante al molare da ieri sera con gengiva gonfia, che antibiotico posso prendere subito?",
        canale=CanaleMessaggio.WHATSAPP,
        id_conversazione="live-med-2",
        telefono_mittente="393515205809",
    )
    res = await genera_risposta_async(msg, profilo_medico)
    
    # Fail-closed: DEVE bloccare e richiedere umano
    assert res.richiede_umano is True
    assert "medica" in res.motivo or "sintomi" in res.motivo or "farmac" in res.motivo
    # Deve contenere avviso medico prudenziale / 112 / guardia medica
    testo_lower = res.risposta.lower()
    assert any(k in testo_lower for k in ["medico", "staff", "farmaci", "112", "guardia medica", "consigli medici"])


# =====================================================================
# 4. HOTEL / B&B LIVE TESTS
# =====================================================================

@pytest.mark.asyncio
async def test_live_hotel_date_invertite(profilo_hotel):
    msg = MessaggioInput(
        testo="Vorrei prenotare una camera con check-in 15 settembre e check-out 10 settembre a nome Rossi",
        canale=CanaleMessaggio.WHATSAPP,
        id_conversazione="live-hotel-1",
        telefono_mittente="393515205809",
    )
    res = await genera_risposta_async(msg, profilo_hotel)
    
    # Date invertite: NON deve registrare la prenotazione
    assert res.prenotazione is None
    assert any(k in res.risposta.lower() for k in ["errore", "date", "precede", "antecedente", "incongruenza", "confermarmi"])


# =====================================================================
# 5. CENTRO ESTETICO LIVE TESTS
# =====================================================================

@pytest.mark.asyncio
async def test_live_estetica_controindicazione_gravidanza(profilo_estetica):
    msg = MessaggioInput(
        testo="Sono incinta al secondo mese, posso fare il trattamento corpo drenante con macchinario?",
        canale=CanaleMessaggio.WHATSAPP,
        id_conversazione="live-est-1",
        telefono_mittente="393515205809",
    )
    res = await genera_risposta_async(msg, profilo_estetica)
    assert res.richiede_umano is True
    assert "gravidanza" in res.motivo or "medica" in res.motivo


# =====================================================================
# 6. FALLBACK SU VERTICALE SCONOSCIUTO E2E
# =====================================================================

@pytest.mark.asyncio
async def test_live_fallback_verticale_sconosciuto():
    profilo_unk = ProfiloAttivita(
        nome="Autofficina Rapida",
        tipo_attivita="Officina Meccanica",
        tono="pratico e diretto",
        orari="Lun-Ven 08:00-18:00",
        servizi_principali=["Tagliando auto", "Cambio gomme", "Revisione"],
        note_speciali=[],
        verticale="officina_non_censita",
    )
    msg = MessaggioInput(
        testo="A che ora siete aperti domani?",
        canale=CanaleMessaggio.WHATSAPP,
        id_conversazione="live-fallback-1",
        telefono_mittente="393515205809",
    )
    res = await genera_risposta_async(msg, profilo_unk)
    assert res.richiede_umano is False
    assert "08:00" in res.risposta or "18:00" in res.risposta
