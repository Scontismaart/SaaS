"""
hotel_bnb.py
------------
Modulo specializzato per Hotel, B&B, Agriturismi, Residence e Strutture Ricettive.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from src.core.verticals.base import BaseVerticalStrategy, TerminologiaVerticale

if TYPE_CHECKING:
    from src.models.schemas import DatiPrenotazione, ProfiloAttivita


class HotelBnBVerticalStrategy(BaseVerticalStrategy):
    """Strategia specializzata per il settore Hospitality (Hotel, B&B, Strutture Ricettive)."""

    code: str = "hotel_bnb"
    label: str = "Hotel / B&B / Struttura Ricettiva"
    synonyms: tuple[str, ...] = (
        "hotel_bnb", "hotel", "bnb", "b&b", "albergo", "residence", "agriturismo", "guest_house", "camere"
    )
    terminologia: TerminologiaVerticale = TerminologiaVerticale(
        label_singolare="soggiorno",
        label_plurale="soggiorni",
        label_unita="ospite",
        label_unita_plurale="ospiti",
        label_servizio="camera / soggiorno",
    )
    default_coperti: int | None = 2  # Tipicamente standard per camera doppia se non specificato

    servizi_default: tuple[str, ...] = (
        "Pernottamento e tipologie camere",
        "Orari di check-in e check-out",
        "Prima colazione e servizi inclusi",
        "Informazioni turistiche e parcheggio",
    )

    regole_escalation_default: tuple[str, ...] = (
        "Richieste di cancellazione con rimborso o contestazione penali",
        "Richieste di accessibilità specifica per disabilità motorie",
        "Problemi, guasti o lamentele durante il soggiorno in camera",
        "Overbooking o richieste last-minute per grandi gruppi",
    )

    def costruisci_blocco_settore(self, profilo: ProfiloAttivita) -> str:
        return (
            "GESTIONE PRENOTAZIONI E SOGGIORNI (SETTORE HOSPITALITY / HOTEL / B&B):\n"
            "La richiesta riguarda la prenotazione di camere, date di soggiorno e informazioni di ospitalità.\n\n"
            "1. REGOLE SULLE DATE DI SOGGIORNO (CHECK-IN E CHECK-OUT):\n"
            "   - Per un soggiorno sono necessarie: DATA DI CHECK-IN (arrivo) e DATA DI CHECK-OUT (partenza) oppure il numero di notti.\n"
            "   - CONTROLLO DI COERENZA DATE (VALIDAZIONE LOGICA):\n"
            "     La data di check-out deve essere SEMPRE SUCCESSIVA alla data di check-in.\n"
            "     Se il cliente indica date invertite o incoerenti (es. check-in il 15 settembre e check-out il 10 settembre):\n"
            "     NON registrare la prenotazione! Segnala cortesemente l'incongruenza (es. 'Sembra ci sia un errore nelle date: la data di partenza [check-out] risulta antecedente a quella di arrivo. Puoi confermarmi le date corrette del soggiorno?').\n\n"
            "2. DATI ESSENZIALI:\n"
            "   I dati essenziali sono: DATA CHECK-IN, DATA CHECK-OUT (o notti), NUMERO OSPITI, TIPOLOGIA CAMERA e NOME_CLIENTE.\n"
            "   - Se hai tutti i dati, registra la richiesta impostando data = check-in, ora = '14:00' (o orario check-in standard), note = 'Check-out: [data_checkout]'.\n\n"
            "3. POLICY CANCELLAZIONI E RIMBORSI (ESCALATION):\n"
            "   - Se il cliente chiede cancellazioni con deroga alle penali o rimborsi di tariffe non rimborsabili: imposta richiede_umano=True con motivo 'richiesta_rimborso_cancellazione'."
        )

    def valida_e_arricchisci_prenotazione(
        self,
        pren: DatiPrenotazione | None,
        testo_messaggio: str,
    ) -> DatiPrenotazione | None:
        if pren is None:
            return None

        if pren.coperti is None or pren.coperti <= 0:
            testo_lower = testo_messaggio.lower()
            if "singola" in testo_lower or "1 persona" in testo_lower:
                pren.coperti = 1
            elif "matrimoniale" in testo_lower or "doppia" in testo_lower or "2 persone" in testo_lower:
                pren.coperti = 2
            elif "tripla" in testo_lower or "3 persone" in testo_lower:
                pren.coperti = 3
            elif "quadrupla" in testo_lower or "4 persone" in testo_lower:
                pren.coperti = 4
            else:
                pren.coperti = 2  # Default standard ospitalità

        return pren
