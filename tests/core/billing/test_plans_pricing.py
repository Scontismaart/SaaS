"""B5: griglia prezzi Essenziale/Crescita/Scala + supporto annuale."""
import pytest
from src.core.billing.plans import PLANS


def test_prezzi_canonici():
    assert PLANS["starter"].price_monthly_eur == 29
    assert PLANS["pro"].price_monthly_eur == 69
    assert PLANS["business"].price_monthly_eur == 149


def test_prezzi_annuali_25_percento():
    assert PLANS["starter"].price_yearly_eur == 288   # 24*12
    assert PLANS["pro"].price_yearly_eur == 708       # 59*12
    assert PLANS["business"].price_yearly_eur == 1548 # 129*12


def test_nomi_commerciali():
    assert PLANS["starter"].name == "Essenziale"
    assert PLANS["pro"].name == "Crescita"
    assert PLANS["business"].name == "Scala"


def test_limiti_invariati():
    assert PLANS["starter"].messages_limit == 300
    assert PLANS["pro"].messages_limit == 1200
    assert PLANS["business"].messages_limit == 5000
    assert PLANS["pro"].has_reviews is True
    assert PLANS["business"].has_rag is True


def test_resolve_price_id():
    from src.core.billing.routes import _resolve_price_id
    p = PLANS["pro"]
    p.stripe_price_id = "price_m"
    p.stripe_price_id_yearly = "price_y"
    assert _resolve_price_id(p, "monthly") == "price_m"
    assert _resolve_price_id(p, "yearly") == "price_y"


def test_resolve_price_id_intervallo_invalido():
    from src.core.billing.routes import _resolve_price_id
    with pytest.raises(ValueError):
        _resolve_price_id(PLANS["pro"], "settimanale")
