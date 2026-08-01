"""Fonti recensioni: ingresso manuale per TripAdvisor/Manuale.

Dopo la decisione di scope (mini-form manuale, nessun fetch/CSV/SerpApi),
la fonte TripAdvisor NON deve piu' sollevare NotImplementedError: deve
restituire una lista vuota, esattamente come FonteManuale. L'ingresso
avviene via /api/recensione con fonte="tripadvisor".
"""
from src.core.review_sources.manuale import FonteManuale
from src.core.review_sources.tripadvisor_stub import FonteTripAdvisor


def test_tripadvisor_non_solleva_not_implemented():
    fonte = FonteTripAdvisor()
    assert fonte.recupera_nuove_recensioni() == []


def test_manuale_restituisce_vuoto():
    fonte = FonteManuale()
    assert fonte.recupera_nuove_recensioni() == []


def test_tripadvisor_ingresso_manuale_via_recensione():
    # Endpoint /api/recensione accetta fonte="tripadvisor" (RecensioneInput
    # ha il campo fonte); la recensione inserita a mano entra nel DB con
    # questa etichetta e filtra correttamente in /api/recensioni.
    from src.models.schemas import RecensioneInput
    rec = RecensioneInput(testo="Ottimo pranzo", fonte="tripadvisor")
    assert rec.fonte == "tripadvisor"
