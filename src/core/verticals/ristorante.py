"""
ristorante.py
-------------
Modulo specializzato per Ristoranti, Pizzerie, Trattorie, Osterie e Bistrot.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from src.core.verticals.base import BaseVerticalStrategy, TerminologiaVerticale

if TYPE_CHECKING:
    from src.models.schemas import DatiPrenotazione, ProfiloAttivita


class RistoranteVerticalStrategy(BaseVerticalStrategy):
    """Strategia specializzata per il settore Ristorazione (Food & Beverage)."""

    code: str = "ristorante"
    label: str = "Ristorante / Pizzeria / Trattoria"
    synonyms: tuple[str, ...] = (
        "ristorante", "pizzeria", "trattoria", "osteria", "bistrot", "pub", "bar", "food", "tavoli"
    )
    terminologia: TerminologiaVerticale = TerminologiaVerticale(
        label_singolare="tavolo",
        label_plurale="tavoli",
        label_unita="coperto",
        label_unita_plurale="coperti",
        label_servizio="menu / ristorazione",
    )
    default_coperti: int | None = None  # Nel ristorante il numero di persone è OBBLIGATORIO (nessun default implicito a 1)

    servizi_default: tuple[str, ...] = (
        "Pranzo e cena",
        "Prenotazioni tavoli",
        "Menu degustazione e carta vini",
        "Eventi privati e cerimonie su richiesta",
    )

    regole_escalation_default: tuple[str, ...] = (
        "Tavolate numerose oltre 10 persone o eventi privati",
        "Richieste di garanzie mediche assolute su contaminazione allergeni (shock anafilattico)",
        "Reclami su esperienze o conti precedenti",
        "Richieste di piatti/menu personalizzati non presenti nella carta",
    )

    def costruisci_blocco_settore(self, profilo: ProfiloAttivita) -> str:
        return (
            "GESTIONE PRENOTAZIONI (SETTORE RISTORAZIONE / FOOD):\n"
            "La prenotazione riguarda un tavolo per il pranzo o la cena.\n\n"
            "1. REGOLE SUL NUMERO DI COPERTI (OBBLIGATORIO):\n"
            "   - Per prenotare un tavolo, il numero di persone (coperti) è un dato ESSENZIALE e OBBLIGATORIO.\n"
            "   - Se il cliente NON specifica il numero di persone (es. 'Vorrei un tavolo per domani alle 20 a nome Marco'):\n"
            "     NON compilare il campo prenotazione (lascia prenotazione=null). Chiedi SEMPRE: 'Certo [Nome]! Per quante persone posso segnare il tavolo?'.\n\n"
            "2. DATI ESSENZIALI PER CONFERMARE IL TAVOLO (1 SOLO TURNO):\n"
            "   I 4 dati essenziali sono: DATA, ORA, COPERTI (numero persone) e NOME_CLIENTE.\n"
            "   - Se il cliente HA FORNITO tutti i 4 dati essenziali (es. 'Vorrei un tavolo per 4 persone per domani alle 20 a nome Marco'):\n"
            "     Compila SUBITO il campo 'prenotazione' con coperti=4, imposta richiede_umano=False e rispondi confermando la registrazione del tavolo!\n"
            "   - Se manca anche un solo dato (es. mancano i coperti o l'orario o il nome): lascia prenotazione=null e chiedi cortesemente il dato mancante.\n\n"
            "3. ALLERGIE E INTOLLERANZE ALIMENTARI:\n"
            "   - Se un'allergia/intolleranza è menzionata come nota di prenotazione (es. 'siamo in 4, uno è celiaco', 'nota: no crostacei'):\n"
            "     imposta richiede_umano=False, inserisci l'intolleranza nel campo prenotazione.note e procedi normalmente.\n"
            "   - Se il cliente chiede garanzie mediche assolute (es. 'garantite zero contaminazione assoluta per shock anafilattico?'):\n"
            "     NON improvvisare rassicurazioni, imposta richiede_umano=True con motivo 'domanda_sicurezza_alimentare'.\n\n"
            "4. TAVOLATE NUMEROSE E GRUPPI:\n"
            "   - Per richieste di gruppi oltre 10 persone (es. tavolate di 15-20 persone): imposta SEMPRE richiede_umano=True con motivo 'tavolata_numerosa', spiegando che per i gruppi lo staff concorderà il menu."
        )

    def valida_e_arricchisci_prenotazione(
        self,
        pren: DatiPrenotazione | None,
        testo_messaggio: str,
    ) -> DatiPrenotazione | None:
        if pren is None:
            return None

        # Nel ristorante non si forza default=1 a meno che non ci sia una frase esplicita
        if not pren.coperti:
            testo_lower = testo_messaggio.lower()
            match_num = re.search(r"\b(?:per|siamo in|tavolo per|da)\s+(\d{1,2})\s*(?:persone|coperti|amici|ragazzi|colleghi)?\b", testo_lower)
            if match_num:
                pren.coperti = int(match_num.group(1))

        return pren
