import os
from dataclasses import dataclass


@dataclass
class Plan:
    name: str
    stripe_price_id: str
    messages_limit: int | None
    users_limit: int | None
    whatsapp_numbers_limit: int | None
    has_reviews: bool
    has_rag: bool
    price_monthly_eur: int


PLANS: dict[str, Plan] = {
    "starter": Plan(
        name="Starter",
        stripe_price_id=os.getenv("STRIPE_PRICE_STARTER", ""),
        messages_limit=300,
        users_limit=1,
        whatsapp_numbers_limit=1,
        has_reviews=False,
        has_rag=False,
        price_monthly_eur=49,
    ),
    "pro": Plan(
        name="Pro",
        stripe_price_id=os.getenv("STRIPE_PRICE_PRO", ""),
        messages_limit=1200,
        users_limit=3,
        whatsapp_numbers_limit=1,
        has_reviews=True,
        has_rag=False,
        price_monthly_eur=99,
    ),
    "business": Plan(
        name="Business",
        stripe_price_id=os.getenv("STRIPE_PRICE_BUSINESS", ""),
        messages_limit=5000,
        users_limit=None,
        whatsapp_numbers_limit=None,
        has_reviews=True,
        has_rag=True,
        price_monthly_eur=199,
    ),
}


def get_plan(plan_slug: str) -> Plan:
    if plan_slug not in PLANS:
        raise ValueError(f"Unknown plan: {plan_slug}. Valid: {list(PLANS.keys())}")
    return PLANS[plan_slug]
