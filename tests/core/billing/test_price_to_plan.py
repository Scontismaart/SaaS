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


def test_price_to_plan_monthly_only_by_default(monkeypatch):
    fake_plans = _install_fake_plans(monkeypatch)
    monkeypatch.delenv("STRIPE_ANNUAL_PRICING_ENABLED", raising=False)
    _init_plan_maps()
    for slug, plan in fake_plans.items():
        assert PRICE_TO_PLAN[plan.stripe_price_id] == slug
        assert plan.stripe_price_id_yearly not in PRICE_TO_PLAN


def test_price_to_plan_includes_yearly_when_enabled(monkeypatch):
    fake_plans = _install_fake_plans(monkeypatch)
    monkeypatch.setenv("STRIPE_ANNUAL_PRICING_ENABLED", "true")
    _init_plan_maps()
    for slug, plan in fake_plans.items():
        assert PRICE_TO_PLAN[plan.stripe_price_id] == slug
        assert PRICE_TO_PLAN[plan.stripe_price_id_yearly] == slug


def test_v1_commercial_profile_never_accepts_annual_even_if_flag_enabled(monkeypatch):
    _install_fake_plans(monkeypatch)
    monkeypatch.setenv("LAUNCH_PROFILE", "commercial_bootstrap")
    monkeypatch.setenv("STRIPE_ANNUAL_PRICING_ENABLED", "true")
    assert _resolve_plan_from_subscription({"items": {"has_more": False, "data": [
        {"price": {"id": "price_pro_y"}, "quantity": 1}
    ]}}) is None


def test_resolve_plan_from_subscription_monthly_only_when_annual_disabled(monkeypatch):
    fake_plans = _install_fake_plans(monkeypatch)
    monkeypatch.delenv("STRIPE_ANNUAL_PRICING_ENABLED", raising=False)
    monkeypatch.delenv("LAUNCH_PROFILE", raising=False)
    _init_plan_maps()

    for slug, plan in fake_plans.items():
        monthly = {"items": {"has_more": False, "data": [{"price": {"id": plan.stripe_price_id}, "quantity": 1}]}}
        yearly = {"items": {"has_more": False, "data": [{"price": {"id": plan.stripe_price_id_yearly}, "quantity": 1}]}}
        assert _resolve_plan_from_subscription(monthly) == slug
        assert _resolve_plan_from_subscription(yearly) is None


def test_resolve_plan_from_subscription_monthly_and_yearly_when_annual_enabled(monkeypatch):
    fake_plans = _install_fake_plans(monkeypatch)
    monkeypatch.setenv("STRIPE_ANNUAL_PRICING_ENABLED", "true")
    monkeypatch.delenv("LAUNCH_PROFILE", raising=False)
    _init_plan_maps()

    for slug, plan in fake_plans.items():
        monthly = {"items": {"has_more": False, "data": [{"price": {"id": plan.stripe_price_id}, "quantity": 1}]}}
        yearly = {"items": {"has_more": False, "data": [{"price": {"id": plan.stripe_price_id_yearly}, "quantity": 1}]}}
        assert _resolve_plan_from_subscription(monthly) == slug
        assert _resolve_plan_from_subscription(yearly) == slug


def test_resolve_plan_unknown_price_returns_none():
    _init_plan_maps()
    unknown = {"items": {"has_more": False, "data": [{"price": {"id": "price_sconosciuto"}, "quantity": 1}]}}
    assert _resolve_plan_from_subscription(unknown) is None


@pytest.mark.parametrize("items", [
    {"data": [{"price": {"id": "price_starter_m"}, "quantity": 1}]},
    {"has_more": True, "data": [{"price": {"id": "price_starter_m"}, "quantity": 1}]},
])
def test_resolve_plan_requires_explicitly_complete_snapshot(monkeypatch, items):
    _install_fake_plans(monkeypatch)
    monkeypatch.delenv("LAUNCH_PROFILE", raising=False)
    monkeypatch.delenv("STRIPE_ANNUAL_PRICING_ENABLED", raising=False)
    assert _resolve_plan_from_subscription({"items": items}) is None


@pytest.mark.parametrize("items", [
    [{"price": {"id": "price_starter_m"}, "quantity": 2}],
    [
        {"price": {"id": "price_starter_m"}, "quantity": 1},
        {"price": {"id": "price_pro_m"}, "quantity": 1},
    ],
    [{"price": {"id": "price_starter_m"}, "quantity": None}],
])
def test_resolve_plan_rejects_incomplete_multiline_or_nonunit_snapshot(monkeypatch, items):
    _install_fake_plans(monkeypatch)
    monkeypatch.delenv("LAUNCH_PROFILE", raising=False)
    monkeypatch.delenv("STRIPE_ANNUAL_PRICING_ENABLED", raising=False)
    assert _resolve_plan_from_subscription({"items": {"has_more": False, "data": items}}) is None
