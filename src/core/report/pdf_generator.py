"""Generazione PDF del report settimanale via weasyprint.

Rendering: Jinja2 (HTML template) -> weasyprint (PDF in memoria).
Il PDF non viene mai scritto su filesystem — generato in BytesIO.
"""

import io
import os
from datetime import datetime, timezone

from jinja2 import Environment, FileSystemLoader

from src.models.schemas import KPISettimanali

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")


def _formatta_tempo_risposta(secondi: float | None) -> str:
    """Formatta i secondi in una stringa leggibile (es. '2m 15s', '45s')."""
    if secondi is None:
        return "N/D"
    if secondi < 60:
        return f"{int(secondi)}s"
    minuti = int(secondi // 60)
    sec = int(secondi % 60)
    return f"{minuti}m {sec}s"


def genera_pdf(kpi: KPISettimanali) -> bytes:
    """Genera il PDF del report settimanale a partire dai KPI.

    Restituisce i bytes del PDF, pronti per allegato email o download.
    """
    # Import lazy per non rallentare il boot dell'app se weasyprint
    # non e' necessario (es. worker che non generano report).
    from weasyprint import HTML

    env = Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        autoescape=True,
    )
    template = env.get_template("weekly_report.html")

    html_content = template.render(
        nome_attivita=kpi.nome_attivita,
        periodo_inizio=kpi.periodo_inizio,
        periodo_fine=kpi.periodo_fine,
        messaggi=kpi.messaggi,
        prenotazioni=kpi.prenotazioni,
        recensioni=kpi.recensioni,
        tempo_risposta_fmt=_formatta_tempo_risposta(
            kpi.messaggi.tempo_medio_risposta_secondi
        ),
        generato_il=datetime.now(tz=timezone.utc).strftime("%d/%m/%Y %H:%M UTC"),
    )

    pdf_buffer = io.BytesIO()
    HTML(string=html_content).write_pdf(target=pdf_buffer)
    return pdf_buffer.getvalue()
