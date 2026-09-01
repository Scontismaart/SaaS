"""
centro_estetico.py
------------------
Modulo specializzato per Centri Estetici, SPA, Saloni di Bellezza e Benessere.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from src.core.verticals.base import BaseVerticalStrategy, TerminologiaVerticale

if TYPE_CHECKING:
    from src.models.schemas import DatiPrenotazione, ProfiloAttivita


class CentroEsteticoVerticalStrategy(BaseVerticalStrategy):
    """Strategia specializzata per Centri Estetici, SPA e Beauty Center."""

    code: str = "centro_estetico"
    label: str = "Centro Estetico / SPA / Benessere"
    synonyms: tuple[str, ...] = (
        "centro_estetico", "estetista", "estetica", "spa", "benessere", "beauty", "massaggi", "nail", "unghie"
    )
    terminologia: TerminologiaVerticale = TerminologiaVerticale(
        label_singolare="trattamento",
        label_plurale="trattamenti",
        label_unita="persona",
        label_unita_plurale="persone",
        label_servizio="trattamento / seduta",
    )
    default_coperti: int | None = 1  # Per i trattamenti estetici il default è 1 persona

    servizi_default: tuple[str, ...] = (
        "Manicure, pedicure e ricostruzione unghie",
        "Trattamenti viso e pulizia profonda",
        "Massaggi rilassanti, decontratturanti e percorsi corpo",
        "Epilazione laser e ceretta",
    )

    regole_escalation_default: tuple[str, ...] = (
        "Gravidanza, allattamento o condizioni mediche specifiche",
        "Trattamenti invasivi, acidi o controindicazioni dermatologiche",
        "Reazioni allergiche dopo un trattamento",
        "Richieste di diagnosi mediche su macchie o inestetismi",
    )

    def costruisci_blocco_settore(self, profilo: ProfiloAttivita) -> str:
        return (
            "GESTIONE TRATTAMENTI E APPUNTAMENTI (SETTORE CENTRO ESTETICO / SPA):\n"
            "Gli appuntamenti riguardano sedute di estetica, massaggi o trattamenti benessere individuali.\n\n"
            "1. REGOLE SUL NUMERO DI PERSONE (DEFAULT = 1 PERSONA):\n"
            "   - Quando un cliente chiede un appuntamento per un trattamento (es. 'una manicure', 'un massaggio viso', 'pulizia del viso domani alle 11 a nome Sara'):\n"
            "     Assumi AUTOMATICAMENTE 1 PERSONA (prenotazione.coperti = 1). NON chiedere 'Per quante persone?'.\n"
            "   - Chiedi il numero solo per percorsi di coppia o richieste esplicitamente plurali (es. 'massaggio di coppia', 'per me e una mia amica').\n\n"
            "2. DATI ESSENZIALI:\n"
            "   I dati essenziali sono: TRATTAMENTO/SERVIZIO, DATA, ORA e NOME_CLIENTE.\n"
            "   - Se presenti tutti, registra subito l'appuntamento e rispondi con cortesia.\n\n"
            "3. GRAVIDANZA E CONTROINDICAZIONI MEDICHE (ESCALATION):\n"
            "   - Se la cliente menziona uno stato di gravidanza o allattamento per trattamenti corpo/macchinari/laser/massaggi:\n"
            "     NON dare rassicurazioni cliniche! Imposta richiede_umano=True con motivo 'condizione_medica_gravidanza' e scrivi un messaggio rassicurante spiegando che l'operatrice verificherà il protocollo più sicuro e adatto."
        )

    def valida_e_arricchisci_prenotazione(
        self,
        pren: DatiPrenotazione | None,
        testo_messaggio: str,
    ) -> DatiPrenotazione | None:
        if pren is None:
            return None

        testo_lower = testo_messaggio.lower()
        if re.search(r"\b(in due|in 2|di coppia|per due|per 2|io e mia amica|io e mia sorella|2 persone)\b", testo_lower):
            pren.coperti = 2
        elif pren.coperti is None or pren.coperti <= 0:
            pren.coperti = 1

        return pren
