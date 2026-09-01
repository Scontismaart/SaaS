"""
studio_medico.py
----------------
Modulo specializzato per Studi Medici, Dentisti, Poliambulatori e Centri Diagnostici.
Implementa una rigorosa politica FAIL-CLOSED contro consulenze mediche non autorizzate o autodiagnosi.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from src.core.verticals.base import BaseVerticalStrategy, TerminologiaVerticale

if TYPE_CHECKING:
    from src.models.schemas import DatiPrenotazione, ProfiloAttivita


class StudioMedicoDentistaVerticalStrategy(BaseVerticalStrategy):
    """Strategia specializzata per il settore Sanitario e Odontoiatrico."""

    code: str = "studio_medico_dentista"
    label: str = "Studio Medico / Dentista / Poliambulatorio"
    synonyms: tuple[str, ...] = (
        "studio_medico_dentista", "studio_medico", "dentista", "odontoiatra", "medico", "clinica", "dottore", "poliambulatorio", "sanita"
    )
    terminologia: TerminologiaVerticale = TerminologiaVerticale(
        label_singolare="visita",
        label_plurale="visite",
        label_unita="paziente",
        label_unita_plurale="pazienti",
        label_servizio="prestazione / visita",
    )
    default_coperti: int | None = 1  # 1 paziente per visita

    servizi_default: tuple[str, ...] = (
        "Visite specialistiche e controlli di routine",
        "Igiene dentale e prevenzione",
        "Promemoria appuntamenti e orari sede",
        "Indicazioni amministrative e documentazione",
    )

    regole_escalation_default: tuple[str, ...] = (
        "Sintomi, dolori acuti o richieste di autodiagnosi medica",
        "Domande su farmaci, antibiotici, posologie o terapie",
        "Referti clinici, esami o dati sanitari sensibili (GDPR sanitario)",
        "Urgenze o emergenze cliniche",
    )

    def costruisci_blocco_settore(self, profilo: ProfiloAttivita) -> str:
        return (
            "GESTIONE APPUNTAMENTI E PRESTAZIONI (SETTORE MEDICO / ODONTOIATRICO):\n"
            "Gli appuntamenti riguardano visite specialistiche, sedute di igiene o controlli per singoli pazienti.\n\n"
            "1. REGOLE SUL NUMERO DI PAZIENTI (DEFAULT = 1 PAZIENTE):\n"
            "   - Per qualsiasi richiesta di visita (es. 'igiene dentale', 'visita di controllo giovedì alle 15 a nome Laura'):\n"
            "     Assumi AUTOMATICAMENTE 1 PAZIENTE (prenotazione.coperti = 1). NON chiedere 'Per quante persone?'.\n\n"
            "2. DATI ESSENZIALI:\n"
            "   I dati essenziali sono: PRESTAZIONE/TIPO VISITA, DATA, ORA e NOME_CLIENTE (Paziente).\n"
            "   - Se presenti, registra la richiesta di visita.\n\n"
            "3. FAIL-CLOSED MEDICO ASSOLUTO (SICUREZZA SANITARIA - FONDAMENTALE):\n"
            "   - Tu sei un assistente per la segreteria e gli appuntamenti, NON un medico o un odontoiatra!\n"
            "   - Se il cliente descrive SINTOMI (es. 'ho un mal di denti lancinante', 'ho la gengiva gonfia con pus', 'ho febbre e dolore'):\n"
            "     1. NON fare MAI diagnosi né suggerire terapie o farmaci (es. non consigliare MAI antibiotici o antinfiammatori specifici)!\n"
            "     2. Imposta SEMPRE richiede_umano=True con motivo 'sintomi_urgenza_medica'.\n"
            "     3. Rispondi con tono rassicurante e professionale: 'Mi dispiace per il dolore. Come assistente virtuale non posso fornire consigli medici o prescrivere farmaci. Ho avvisato subito il nostro staff per ricontattarti al più presto. In caso di urgenza grave o emergenza, ti invitiamo a contattare il 112 o il servizio di Continuità Assistenziale (Guardia Medica).'"
        )

    def valida_e_arricchisci_prenotazione(
        self,
        pren: DatiPrenotazione | None,
        testo_messaggio: str,
    ) -> DatiPrenotazione | None:
        if pren is None:
            return None

        if pren.coperti is None or pren.coperti <= 0:
            pren.coperti = 1

        return pren
