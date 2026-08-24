import pytest

from src.core.billing.webhook_handler import (
    PRICE_TO_PLAN,
    PRODUCT_TO_PLAN,
    _init_plan_maps,
    _resolve_plan_from_subscription,
)


@pytest.fixture(autouse=True)
def _reset_plan_maps():
    PRICE_TO_PLAN.clear()
    PRODUCT_TO_PLAN.clear()
    yield
    PRICE_TO_PLAN.clear()
    PRODUCT_TO_PLAN.clear()


def _install_fake_plans(monkeypatch):
    class FakePlan:
        def __init__(self, monthly, yearly):
            self.stripe_price_id = monthly
            self.stripe_price_id_yearly = yearly

    fake_plans = {
        "starter": FakePlan("price_starter_m", "price_starter_y"),
        "pro": FakePlan("price_pro_m", "price_pro_y"),
    }
    monkeypatch.setattr(
        "src.core.billing.plans.PLANS", fake_plans, raising=False
    )
    return fake_plans


def test_price_to_plan_includes_yearly(monkeypatch):
    fake_plans = _install_fake_plans(monkeypatch)
    _init_plan_maps()
    for slug, plan in fake_plans.items():
        assert PRICE_TO_PLAN[plan.stripe_price_id] == slug
        assert PRICE_TO_PLAN[plan.stripe_price_id_yearly] == slug


def test_resolve_plan_from_subscription_monthly_and_yearly(monkeypatch):
    fake_plans = _install_fake_plans(monkeypatch)
    _init_plan_maps()

    for slug, plan in fake_plans.items():
        monthly = {"items": {"data": [{"price": {"id": plan.stripe_price_id}}]}}
        yearly = {"items": {"data": [{"price": {"id": plan.stripe_price_id_yearly}}]}}
        assert _resolve_plan_from_subscription(monthly) == slug
        assert _resolve_plan_from_subscription(yearly) == slug


def test_resolve_plan_unknown_price_returns_none():
    _init_plan_maps()
    unknown = {"items": {"data": [{"price": {"id": "price_sconosciuto"}}]}}
    assert _resolve_plan_from_subscription(unknown) is None
