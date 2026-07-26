from datetime import date, time
import pytest
from unittest.mock import patch

pytestmark = pytest.mark.asyncio


async def _setup_deposito_settings(repo, sample_org, config_overrides=None):
    config = {
        "deposito": {
            "enabled": True,
            "importo_default": 10.00,
            "valuta": "EUR",
            "criteri": {
                "coperti_min": 6,
                "tipi_evento": ["evento_speciale", "cena_di_gala"],
                "fasce": ["20:00", "21:00"],
                "date": ["2026-12-31"],
            },
        }
    }
    if config_overrides:
        deep_update(config, config_overrides)
    await repo.upsert_booking_settings_config(sample_org["id"], config)


def deep_update(d, u):
    for k, v in u.items():
        if isinstance(v, dict) and k in d and isinstance(d[k], dict):
            deep_update(d[k], v)
        else:
            d[k] = v


async def test_deposito_disabled(booking_service, repo, sample_org):
    config = {"deposito": {"enabled": False}}
    await repo.upsert_booking_settings_config(sample_org["id"], config)
    result = await booking_service._valuta_richiede_deposito(
        sample_org["id"], coperti=10, tipo_evento="normale", ora="20:00", data="2026-08-15"
    )
    assert result is False


async def test_deposito_matcha_coperti_min(booking_service, repo, sample_org):
    await _setup_deposito_settings(repo, sample_org)
    result = await booking_service._valuta_richiede_deposito(
        sample_org["id"], coperti=6, tipo_evento="", ora="12:00", data="2026-08-15"
    )
    assert result is True


async def test_deposito_non_matcha_coperti_sotto_soglia(booking_service, repo, sample_org):
    await _setup_deposito_settings(repo, sample_org)
    result = await booking_service._valuta_richiede_deposito(
        sample_org["id"], coperti=4, tipo_evento="", ora="12:00", data="2026-08-15"
    )
    assert result is False


async def test_deposito_matcha_tipo_evento(booking_service, repo, sample_org):
    await _setup_deposito_settings(repo, sample_org)
    result = await booking_service._valuta_richiede_deposito(
        sample_org["id"], coperti=2, tipo_evento="cena_di_gala", ora="12:00", data="2026-08-15"
    )
    assert result is True


async def test_deposito_matcha_fascia_oraria(booking_service, repo, sample_org):
    await _setup_deposito_settings(repo, sample_org)
    result = await booking_service._valuta_richiede_deposito(
        sample_org["id"], coperti=2, tipo_evento="", ora="20:30", data="2026-08-15"
    )
    assert result is True


async def test_deposito_matcha_data(booking_service, repo, sample_org):
    await _setup_deposito_settings(repo, sample_org)
    result = await booking_service._valuta_richiede_deposito(
        sample_org["id"], coperti=2, tipo_evento="", ora="12:00", data="2026-12-31"
    )
    assert result is True


async def test_deposito_genera_payment_link(booking_service, repo, sample_org):
    await _setup_deposito_settings(repo, sample_org)
    b = await booking_service.create_booking(
        sample_org["id"], nome_cliente="Mario", telefono="+393331234567",
        data="2026-08-01", ora="20:00", coperti=8,
    )
    with patch("stripe.PaymentLink.create") as mock_create:
        mock_create.return_value = type("obj", (), {"url": "https://pay.stripe.com/test_123"})()
        confirmed = await booking_service.confirm(sample_org["id"], b["id"])
    assert confirmed["payment_status"] == "pending"
    assert confirmed["payment_link"] == "https://pay.stripe.com/test_123"
