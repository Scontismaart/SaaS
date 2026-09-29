"""Test funzioni di utilità del pdf_generator (no weasyprint richiesto)."""

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from src.core.report.pdf_generator import (
    _formatta_tempo_risposta,
    genera_pdf,
)


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


def test_pdf_generator_installs_deny_all_fetcher():
    captured = {}

    class FakeBaseFetcher:
        pass

    class FakeHTML:
        def __init__(self, *, string, url_fetcher):
            captured["url_fetcher"] = url_fetcher
            assert "Report Settimanale" in string

        def write_pdf(self, *, target):
            target.write(b"%PDF-test")

    fake_weasyprint = ModuleType("weasyprint")
    fake_weasyprint.__path__ = []
    fake_weasyprint.HTML = FakeHTML
    fake_urls = ModuleType("weasyprint.urls")
    fake_urls.URLFetcher = FakeBaseFetcher
    kpi = MagicMock()
    kpi.messaggi.tempo_medio_risposta_secondi = None
    with patch.dict(sys.modules, {"weasyprint": fake_weasyprint, "weasyprint.urls": fake_urls}):
        assert genera_pdf(kpi) == b"%PDF-test"

    assert isinstance(captured["url_fetcher"], FakeBaseFetcher)
    for url in ("https://example.com/a", "file:///etc/passwd", "data:text/plain,a"):
        with pytest.raises(ValueError, match="External PDF resources are disabled"):
            captured["url_fetcher"].fetch(url)
