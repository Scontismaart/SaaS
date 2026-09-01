"""
parrucchiere.py
---------------
Modulo specializzato per Saloni di Parrucchiere, Barbershop e Hair Stylist.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from src.core.verticals.base import BaseVerticalStrategy, TerminologiaVerticale

if TYPE_CHECKING:
    from src.models.schemas import DatiPrenotazione, ProfiloAttivita


class ParrucchiereVerticalStrategy(BaseVerticalStrategy):
    """Strategia specializzata per Saloni di Parrucchiere e Barbieri."""

    code: str = "parrucchiere"
    label: str = "Salone di Parrucchiere / Barber"
    synonyms: tuple[str, ...] = (
        "parrucchiere", "barber", "barbiere", "parrucchiera", "parrucchieri", "salone", "hair", "hairdresser"
    )
    terminologia: TerminologiaVerticale = TerminologiaVerticale(
        label_singolare="appuntamento",
        label_plurale="appuntamenti",
        label_unita="persona",
        label_unita_plurale="persone",
        label_servizio="servizio / trattamento",
    )
    default_coperti: int | None = 1  # In un salone il default naturale per ogni servizio è 1 persona

    servizi_default: tuple[str, ...] = (
        "Taglio donna e uomo",
        "Piega e styling",
        "Colore e tonalizzante",
        "Trattamenti cute e ricostruzione capelli",
        "Rifinitura barba e cura del viso",
    )

    regole_escalation_default: tuple[str, ...] = (
        "Lavori tecnici complessi o correzioni colore estreme (es. decolorazioni totali)",
        "Reazioni cutanee, allergie note a tinture o problemi dermatologici",
        "Preventivi per lavori elaborati (richiedono consulenza dal vivo)",
        "Reclami su servizi precedenti o richieste di rimborsi",
    )

    def costruisci_blocco_settore(self, profilo: ProfiloAttivita) -> str:
        return (
            "GESTIONE APPUNTAMENTI (SETTORE PARRUCCHIERE / BARBERSHOP):\n"
            "Gli appuntamenti per un salone di parrucchiere/barber sono servizi individuali alla persona.\n\n"
            "1. REGOLE SUL NUMERO DI PERSONE (DEFAULT = 1 PERSONA):\n"
            "   - Quando un cliente chiede un appuntamento per un servizio al singolare (es. 'un taglio', 'una piega', 'taglio e barba', 'posso venire domani alle 20 a nome Marco?'):\n"
            "     Assumi AUTOMATICAMENTE 1 PERSONA (prenotazione.coperti = 1). NON CHIEDERE MAI 'Per quante persone?'!\n"
            "   - Chiedi il numero di persone o l'operatore SOLO se il cliente formula una richiesta palesemente plurale o ambigua (es. 'vorremmo fare dei tagli', 'siamo in 2 per il taglio', 'per me e mio figlio').\n\n"
            "2. DATI ESSENZIALI PER CONFERMARE L'APPUNTAMENTO:\n"
            "   I dati essenziali per fissare un appuntamento sono:\n"
            "   - SERVIZIO RICHIESTO (es. taglio, barba, piega, colore)\n"
            "   - DATA (risolta rispetto a oggi)\n"
            "   - ORA\n"
            "   - NOME DEL CLIENTE\n"
            "   (Il numero di persone è già 1 per default).\n\n"
            "3. REGISTRAZIONE E CONFERMA IMMEDIATA (1 SOLO TURNO):\n"
            "   - Se il cliente ha fornito SERVIZIO, DATA, ORA e NOME (o il nome è già presente): registra SUBITO la richiesta nel campo 'prenotazione', imposta richiede_umano=False e rispondi confermando l'appuntamento (es. 'Perfetto [Nome], ho registrato il tuo appuntamento per [servizio] [data] alle [ora]! Ti aspettiamo.').\n"
            "   - Se MANCANO dei dati (es. manca l'orario o il servizio): chiedi gentilmente SOLO i dati mancanti, senza fare domande inutili sul numero di persone.\n\n"
            "4. NOTE E CASI PARTICOLARI:\n"
            "   - Se il cliente chiede servizi per più persone (es. 'due tagli'), imposta prenotazione.coperti = 2 (o il numero specificato).\n"
            "   - Richieste di appuntamenti per più di 4 persone contemporaneamente vanno girate a umano (richiede_umano=True con motivo 'gruppo_numeroso').\n"
            "   - Per servizi tecnici che richiedono consulenza (es. decolorazioni estreme da nero a biondo platino, extension): imposta richiede_umano=True con motivo 'lavori_tecnici_complessi'."
        )

    def valida_e_arricchisci_prenotazione(
        self,
        pren: DatiPrenotazione | None,
        testo_messaggio: str,
    ) -> DatiPrenotazione | None:
        if pren is None:
            return None

        # Controllo plurali nel testo (es. "due tagli", "2 persone", "in 2")
        testo_lower = testo_messaggio.lower()
        if re.search(r"\b(due tagli|2 tagli|in due|in 2|per due|per 2|io e mio figlio|io e mia figlia|due persone|2 persone)\b", testo_lower):
            pren.coperti = 2
        elif re.search(r"\b(tre tagli|3 tagli|in tre|in 3|per tre|per 3|tre persone|3 persone)\b", testo_lower):
            pren.coperti = 3
        elif pren.coperti is None or pren.coperti <= 0:
            pren.coperti = 1  # Default naturale 1 persona

        return pren
