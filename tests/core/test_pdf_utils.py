"""Test funzioni di utilità del pdf_generator (no weasyprint richiesto)."""

from src.core.report.pdf_generator import _formatta_tempo_risposta


def test_formatta_tempo_secondi():
    assert _formatta_tempo_risposta(45.0) == "45s"


def test_formatta_tempo_minuti():
    assert _formatta_tempo_risposta(135.0) == "2m 15s"


def test_formatta_tempo_none():
    assert _formatta_tempo_risposta(None) == "N/D"


def test_formatta_tempo_zero():
    assert _formatta_tempo_risposta(0.0) == "0s"


def test_formatta_tempo_esatto_minuto():
    assert _formatta_tempo_risposta(60.0) == "1m 0s"
