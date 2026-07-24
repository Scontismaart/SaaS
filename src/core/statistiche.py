from datetime import datetime
from collections import Counter

from src.models.schemas import EventoDashboard, StatisticheReport


def _periodo_oggi() -> str:
    return datetime.now().strftime("%d %b %Y")


def _campiona_deterministico(
    eventi: list[EventoDashboard],
    categoria: str,
    max_campioni: int = 2,
) -> list[str]:
    filtrati = [
        e for e in eventi
        if e.dettagli.get("categoria", "generico") == categoria
    ]
    filtrati.sort(key=lambda e: e.timestamp, reverse=True)
    return [e.testo_originale for e in filtrati[:max_campioni]]


def calcola_statistiche(storico: list[EventoDashboard]) -> StatisticheReport:
    if not storico:
        return StatisticheReport(
            periodo=_periodo_oggi(),
            totale_messaggi=0,
            gestiti_da_ai=0,
            girati_a_umano=0,
        )

    totale = len(storico)
    gestiti_ai = sum(1 for e in storico if e.gestito_da_ai)
    girati_umano = totale - gestiti_ai

    conteggio_cat = Counter(
        e.dettagli.get("categoria", "generico") for e in storico
    )
    categorie_dict = dict(conteggio_cat.most_common())

    esempi = {}
    for cat in categorie_dict:
        campioni = _campiona_deterministico(storico, cat)
        if campioni:
            esempi[cat] = campioni

    return StatisticheReport(
        periodo=_periodo_oggi(),
        totale_messaggi=totale,
        gestiti_da_ai=gestiti_ai,
        girati_a_umano=girati_umano,
        categorie=categorie_dict,
        esempi_per_categoria=esempi,
    )
