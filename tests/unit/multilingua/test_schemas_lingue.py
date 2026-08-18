"""Multilingua (task 14): validazione dei campi lingua negli schemas.

Lista chiusa it/en/fr/de/es, "it" sempre inclusa e di default, lingua di
default vincolata a essere tra le supportate. ProfiloAttivita e
WhatsAppBusinessProfile devono avere default compatibili con i profili
salvati prima della migration 033.
"""

import pytest
from pydantic import ValidationError

from src.models.schemas import (
    LINGUE_DISPONIBILI,
    OnboardingProfileInput,
    ProfiloAttivita,
    WhatsAppBusinessProfile,
)


def _payload(**overrides):
    data = {
        "verticale": "ristorante",
        "nome_attivita": "Trattoria Da Mario",
        "orari": "Lun-Dom 12-23",
        "tono": "caldo, diretto",
        "servizi": ["Pranzo", "Cena"],
        "regole_escalation": ["Allergie"],
    }
    data.update(overrides)
    return OnboardingProfileInput(**data)


class TestVocabolario:
    def test_lingue_disponibili_chiuse(self):
        assert LINGUE_DISPONIBILI == {"it", "en", "fr", "de", "es"}

    def test_it_sempre_presente(self):
        assert "it" in LINGUE_DISPONIBILI


class TestProfiloAttivita:
    def test_default_italiano(self):
        profilo = ProfiloAttivita(
            nome="X", tipo_attivita="ristorante", tono="t", orari="9-18"
        )
        assert profilo.lingue_supportate == ["it"]
        assert profilo.lingua_default == "it"
        assert profilo.verticale is None

    def test_campi_personalizzati(self):
        profilo = ProfiloAttivita(
            nome="X",
            tipo_attivita="hotel_bnb",
            tono="t",
            orari="24/7",
            lingue_supportate=["it", "en", "de"],
            lingua_default="de",
            verticale="hotel_bnb",
        )
        assert profilo.lingua_default == "de"


class TestWhatsAppBusinessProfile:
    def test_campi_opzionali_per_compatibilita(self):
        p = WhatsAppBusinessProfile()
        assert p.lingue_supportate is None
        assert p.lingua_default is None
        assert p.verticale is None

    def test_round_trip_accepts_lingue(self):
        p = WhatsAppBusinessProfile.model_validate(
            {
                "nome": "X",
                "lingue_supportate": ["it", "fr"],
                "lingua_default": "fr",
                "verticale": "studio_medico_dentista",
            }
        )
        assert p.lingue_supportate == ["it", "fr"]
        assert p.lingua_default == "fr"
        assert p.verticale == "studio_medico_dentista"


class TestOnboardingProfileInput:
    def test_default_italiano(self):
        p = _payload()
        assert p.lingue_supportate == ["it"]
        assert p.lingua_default == "it"

    def test_lingue_personalizzate_valide(self):
        p = _payload(lingue_supportate=["it", "en", "de"], lingua_default="en")
        assert p.lingue_supportate == ["it", "en", "de"]
        assert p.lingua_default == "en"

    def test_lingua_non_nel_vocabolario_rifiutata(self):
        with pytest.raises(ValidationError, match="non supportate"):
            _payload(lingue_supportate=["it", "xx"])

    def test_it_non_rimovibile(self):
        with pytest.raises(ValidationError, match="it"):
            _payload(lingue_supportate=["en", "de"])

    def test_lista_vuota_rifiutata(self):
        with pytest.raises(ValidationError, match="almeno una lingua"):
            _payload(lingue_supportate=[])

    def test_lingua_default_non_supportata_rifiutata(self):
        with pytest.raises(ValidationError, match="non supportata"):
            _payload(lingue_supportate=["it"], lingua_default="xx")

    def test_lingua_default_fuori_dalle_supportate_rifiutata(self):
        with pytest.raises(ValidationError, match="non e' tra le lingue supportate"):
            _payload(lingue_supportate=["it", "en"], lingua_default="fr")