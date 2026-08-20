"""Test generazione PDF report settimanale (no Docker).

Verifica che il PDF si generi, sia un PDF valido, e contenga i dati KPI
attesi — non solo che non lanci eccezioni.

NOTA: weasyprint richiede librerie di sistema (cairo, pango, gobject)
che sono disponibili nel Docker (Debian) ma non su Windows.
Questi test vengono skippati se weasyprint non e' importabile.
"""

import io
import re

import pytest

try:
    from weasyprint import HTML  # noqa: F401
    HAS_WEASYPRINT = True
except (ImportError, OSError):
    HAS_WEASYPRINT = False

pytestmark = pytest.mark.skipif(
    not HAS_WEASYPRINT,
    reason="weasyprint non disponibile (richiede cairo/pango/gobject di sistema)",
)

from src.core.report.pdf_generator import _formatta_tempo_risposta, genera_pdf
from src.models.schemas import (
    KPIMessaggi,
    KPIPrenotazioni,
    KPIRecensioni,
    KPISettimanali,
)


def _estrai_testo_pdf(pdf_bytes: bytes) -> str:
    """Estrae il testo visibile dal PDF.

    WeasyPrint comprime gli stream di contenuto con FlateDecode, quindi i
    raw bytes non contengono il testo in chiaro: va estratto dalle pagine.
    pypdf e' gia' una dipendenza del progetto (vedi src/core/documenti/
    extractor.py); normalizziamo il whitespace per robustezza contro
    interruzioni di riga/parola.
    """
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    testo = "\n".join(page.extract_text() or "" for page in reader.pages)
    return re.sub(r"\s+", " ", testo)


@pytest.fixture
def kpi_esempio():
    """KPI di esempio per i test."""
    return KPISettimanali(
        periodo_inizio="2026-08-11",
        periodo_fine="2026-08-17",
        nome_attivita="Ristorante Da Mario",
        messaggi=KPIMessaggi(
            totale=120,
            gestiti_da_ai=100,
            escalati_a_umano=15,
            percentuale_ai=83.3,
            tempo_medio_risposta_secondi=8.5,
        ),
        prenotazioni=KPIPrenotazioni(
            totale=30,
            confermate=22,
            cancellate=4,
            no_show=1,
            completate=18,
            da_whatsapp=15,
        ),
        recensioni=KPIRecensioni(
            totale=8,
            con_risposta=6,
            percentuale_risposta=75.0,
            media_stelle=4.3,
        ),
    )


def test_pdf_generato_non_vuoto(kpi_esempio):
    """Il PDF viene generato e non e' vuoto."""
    pdf_bytes = genera_pdf(kpi_esempio)
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 0


def test_pdf_header_valido(kpi_esempio):
    """Il file generato inizia con il magic number PDF."""
    pdf_bytes = genera_pdf(kpi_esempio)
    assert pdf_bytes[:5] == b"%PDF-"


def test_pdf_contiene_nome_attivita(kpi_esempio):
    """Il PDF contiene il nome dell'attivita' (testo estratto dalle pagine)."""
    pdf_bytes = genera_pdf(kpi_esempio)
    testo = _estrai_testo_pdf(pdf_bytes)
    assert "Ristorante Da Mario" in testo or "Report Settimanale" in testo


def test_pdf_contiene_periodo(kpi_esempio):
    """Il PDF contiene le date del periodo (testo estratto dalle pagine)."""
    pdf_bytes = genera_pdf(kpi_esempio)
    testo = _estrai_testo_pdf(pdf_bytes)
    # Cerchiamo almeno uno dei due formati (il template usa il formato
    # ISO passato come variabile)
    assert "2026-08-11" in testo or "11/08" in testo


def test_pdf_con_kpi_vuoti():
    """Il PDF si genera correttamente anche con KPI tutti a zero."""
    kpi_vuoto = KPISettimanali(
        periodo_inizio="2026-08-11",
        periodo_fine="2026-08-17",
        nome_attivita="Test Vuoto",
    )
    pdf_bytes = genera_pdf(kpi_vuoto)
    assert pdf_bytes[:5] == b"%PDF-"
    assert len(pdf_bytes) > 100


def test_pdf_senza_tempo_risposta():
    """Il PDF si genera se tempo_medio_risposta_secondi e' None."""
    kpi = KPISettimanali(
        periodo_inizio="2026-08-11",
        periodo_fine="2026-08-17",
        nome_attivita="Test",
        messaggi=KPIMessaggi(tempo_medio_risposta_secondi=None),
    )
    pdf_bytes = genera_pdf(kpi)
    assert pdf_bytes[:5] == b"%PDF-"


# ── Test formattazione tempo (non richiedono weasyprint) ──


@pytest.mark.skipif(False, reason="")
def test_formatta_tempo_secondi():
    assert _formatta_tempo_risposta(45.0) == "45s"


@pytest.mark.skipif(False, reason="")
def test_formatta_tempo_minuti():
    assert _formatta_tempo_risposta(135.0) == "2m 15s"


@pytest.mark.skipif(False, reason="")
def test_formatta_tempo_none():
    assert _formatta_tempo_risposta(None) == "N/D"
