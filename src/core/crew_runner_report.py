from datetime import datetime

from src.agents.report_agent import crea_report_crew
from src.core.statistiche import calcola_statistiche
from src.models.schemas import EventoDashboard, StatisticheReport, ReportOutput


def genera_report(storico: list[EventoDashboard]) -> ReportOutput:
    statistiche = calcola_statistiche(storico)

    if statistiche.totale_messaggi < 3:
        return ReportOutput(
            data=datetime.now().strftime("%Y-%m-%d"),
            statistiche=statistiche,
            analisi_testuale=(
                f"Giornata molto tranquilla: solo {statistiche.totale_messaggi} "
                f"{'messaggi' if statistiche.totale_messaggi != 1 else 'messaggio'}. "
                "Non ci sono abbastanza dati per un'analisi significativa."
            ),
            suggerimenti=[],
            generato_il=datetime.now().isoformat(),
        )

    crew = crea_report_crew(statistiche)
    risultato = crew.kickoff()

    output = risultato.pydantic
    if output is None or not isinstance(output, ReportOutput):
        raise RuntimeError(
            "Il modello non ha restituito un output conforme a ReportOutput."
        )

    output.data = datetime.now().strftime("%Y-%m-%d")
    output.statistiche = statistiche
    output.generato_il = datetime.now().isoformat()

    return output
