"""
__init__.py
-----------
Factory e Registry per la gestione dei moduli verticali del SaaS.
Registra i 5 verticali ufficiali e gestisce il fallback esplicito e tracciato.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from src.core.verticals.base import BaseVerticalStrategy, TerminologiaVerticale
from src.core.verticals.centro_estetico import CentroEsteticoVerticalStrategy
from src.core.verticals.hotel_bnb import HotelBnBVerticalStrategy
from src.core.verticals.parrucchiere import ParrucchiereVerticalStrategy
from src.core.verticals.ristorante import RistoranteVerticalStrategy
from src.core.verticals.studio_medico import StudioMedicoDentistaVerticalStrategy

if TYPE_CHECKING:
    from src.models.schemas import DatiPrenotazione, ProfiloAttivita

logger = logging.getLogger(__name__)

# Istanza delle 5 strategie verticali registrate
_STRATEGIES: dict[str, BaseVerticalStrategy] = {
    RistoranteVerticalStrategy.code: RistoranteVerticalStrategy(),
    ParrucchiereVerticalStrategy.code: ParrucchiereVerticalStrategy(),
    CentroEsteticoVerticalStrategy.code: CentroEsteticoVerticalStrategy(),
    HotelBnBVerticalStrategy.code: HotelBnBVerticalStrategy(),
    StudioMedicoDentistaVerticalStrategy.code: StudioMedicoDentistaVerticalStrategy(),
}

# Codice di fallback esplicito (Ristorante, il verticale standard e storico di riferimento)
DEFAULT_VERTICAL_CODE = RistoranteVerticalStrategy.code


def get_vertical_strategy(
    verticale: str | None,
    organization_id: str | None = None,
) -> BaseVerticalStrategy:
    """
    Recupera la strategia verticale appropriata in base al codice o sinonimo.
    Se non specificato o sconosciuto, applica un fallback ESPLICITO con logging strutturato.
    """
    if verticale:
        norm = str(verticale).strip().lower().replace(" ", "_").replace("-", "_")

        # 1. Match diretto per codice o sinonimo esatto
        if norm in _STRATEGIES:
            return _STRATEGIES[norm]

        for strat in _STRATEGIES.values():
            if norm in strat.synonyms:
                return strat

        # 2. Match su parti di parole composte (es. "studio_medico" in "studio_medico_dentista")
        for strat in _STRATEGIES.values():
            if any(re.search(rf"(?:^|_){re.escape(s)}(?:_|$)", norm) for s in strat.synonyms):
                return strat

    # 3. Fallback Esplicito
    fallback = _STRATEGIES[DEFAULT_VERTICAL_CODE]
    logger.warning(
        "[verticals] Verticale '%s' non riconosciuto o mancante (org_id=%s). Applico fallback esplicito: '%s' (%s)",
        verticale,
        organization_id or "sconosciuta",
        fallback.code,
        fallback.label,
    )
    return fallback


def get_vertical_terminology(verticale: str | None) -> TerminologiaVerticale:
    """Restituisce i termini semantici usati nella UI e nei report per il verticale specificato."""
    strategy = get_vertical_strategy(verticale)
    return strategy.terminologia


def list_registered_verticals() -> list[dict[str, Any]]:
    """Restituisce l'elenco dei verticali registrati nel sistema con i loro metadati."""
    return [
        {
            "code": s.code,
            "label": s.label,
            "servizi_default": list(s.servizi_default),
            "regole_escalation_default": list(s.regole_escalation_default),
            "terminologia": {
                "singolare": s.terminologia.label_singolare,
                "plurale": s.terminologia.label_plurale,
                "unita": s.terminologia.label_unita,
                "unita_plurale": s.terminologia.label_unita_plurale,
                "servizio": s.terminologia.label_servizio,
            },
        }
        for s in _STRATEGIES.values()
    ]
