import os
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

PRICE_TO_PLAN: dict[str, str] = {}
PRODUCT_TO_PLAN: dict[str, str] = {}


def _init_plan_maps():
    from src.core.billing.plans import PLANS
    for slug, plan in PLANS.items():
        if plan.stripe_price_id:
            PRICE_TO_PLAN[plan.stripe_price_id] = slug
        PRODUCT_TO_PLAN[f"prod_{slug}"] = slug


def _resolve_plan_from_subscription(subscription_data: dict) -> str | None:
    if not PRICE_TO_PLAN and not PRODUCT_TO_PLAN:
        _init_plan_maps()
    for item in subscription_data.get("items", {}).get("data", []):
        price_id = item.get("price", {}).get("id", "")
        if price_id in PRICE_TO_PLAN:
            return PRICE_TO_PLAN[price_id]
        product_id = item.get("plan", {}).get("product", "")
        if product_id in PRODUCT_TO_PLAN:
            return PRODUCT_TO_PLAN[product_id]
    return None


async def handle_stripe_webhook(event: dict, repo) -> dict | None:
    event_type = event.get("type")
    data_obj = event.get("data", {}).get("object", {})

    if event_type == "checkout.session.completed":
        return await _handle_checkout_completed(data_obj, repo)

    if event_type == "invoice.paid":
        return await _handle_invoice_paid(data_obj, repo)

    if event_type == "invoice.payment_failed":
        return await _handle_payment_failed(data_obj, repo)

    if event_type == "customer.subscription.updated":
        return await _handle_subscription_updated(data_obj, repo)

    if event_type == "subscription.deleted":
        return await _handle_subscription_deleted(data_obj, repo)

    logger.info("Unhandled event type: %s", event_type)
    return None


async def _handle_checkout_completed(data: dict, repo) -> dict | None:
    org_id = data.get("client_reference_id")
    subscription_id = data.get("subscription")
    customer_id = data.get("customer")

    if not org_id or not subscription_id or data.get("mode") != "subscription":
        return None

    if not await repo.process_stripe_event(data.get("id", ""), org_id):
        return {"action": "duplicate", "status": "skipped", "organization_id": org_id}

    now = datetime.now(timezone.utc)
    trial_days = int(os.getenv("STRIPE_TRIAL_DAYS", "7"))
    await repo.update_organization_billing(org_id, {
        "stripe_customer_id": customer_id,
        "subscription_id": subscription_id,
        "subscription_status": "trialing",
        "trial_start": now,
        "trial_end": now + timedelta(days=trial_days),
        "current_period_start": now,
        "current_period_end": now + timedelta(days=trial_days),
    })
    return {"action": "subscription_created", "status": "trialing", "organization_id": org_id}


async def _lookup_org_by_customer(customer_id: str, repo) -> dict | None:
    if not customer_id:
        return None
    return await repo.get_organization_by_stripe_customer(customer_id)


async def _handle_invoice_paid(data: dict, repo) -> dict | None:
    customer_id = data.get("customer")
    org = await _lookup_org_by_customer(customer_id, repo)
    if not org:
        return None

    if not await repo.process_stripe_event(data.get("id", ""), org["id"]):
        return {"action": "duplicate", "status": "skipped", "organization_id": org["id"]}

    period_start = datetime.fromtimestamp(data.get("period_start", 0), tz=timezone.utc)
    period_end = datetime.fromtimestamp(data.get("period_end", 0), tz=timezone.utc)

    plan_slug = None
    for line in data.get("lines", {}).get("data", []):
        price_id = line.get("price", {}).get("id", "")
        if price_id in PRICE_TO_PLAN:
            plan_slug = PRICE_TO_PLAN[price_id]
            break

    await repo.set_subscription_status(org["id"], "active")
    await repo.reset_message_usage(org["id"], period_start, period_end)

    if plan_slug:
        await repo.update_plan_limits(org["id"], plan_slug)

    return {"action": "subscription_activated", "status": "active", "organization_id": org["id"]}


async def _handle_payment_failed(data: dict, repo) -> dict | None:
    customer_id = data.get("customer")
    org = await _lookup_org_by_customer(customer_id, repo)
    if not org:
        return None

    if not await repo.process_stripe_event(data.get("id", ""), org["id"]):
        return {"action": "duplicate", "status": "skipped", "organization_id": org["id"]}

    await repo.set_subscription_status(org["id"], "past_due")
    return {"action": "payment_failed", "status": "past_due", "organization_id": org["id"]}


async def _handle_subscription_updated(data: dict, repo) -> dict | None:
    customer_id = data.get("customer")
    org = await _lookup_org_by_customer(customer_id, repo)
    if not org:
        return None

    if not await repo.process_stripe_event(data.get("id", ""), org["id"]):
        return {"action": "duplicate", "status": "skipped", "organization_id": org["id"]}

    plan_slug = _resolve_plan_from_subscription(data)
    if plan_slug:
        await repo.update_plan_limits(org["id"], plan_slug)

    if data.get("status") == "past_due":
        await repo.set_subscription_status(org["id"], "past_due")
    elif data.get("status") in ("active", "trialing"):
        current_status = org.get("subscription_status")
        if current_status != "active":
            await repo.set_subscription_status(org["id"], data["status"])

    period_start = data.get("current_period_start")
    period_end = data.get("current_period_end")
    if period_start and period_end:
        await repo.reset_message_usage(
            org["id"],
            datetime.fromtimestamp(period_start, tz=timezone.utc),
            datetime.fromtimestamp(period_end, tz=timezone.utc),
        )

    return {"action": "subscription_updated", "plan": plan_slug, "organization_id": org["id"]}


async def _handle_subscription_deleted(data: dict, repo) -> dict | None:
    customer_id = data.get("customer")
    org = await _lookup_org_by_customer(customer_id, repo)
    if not org:
        return None

    if not await repo.process_stripe_event(data.get("id", ""), org["id"]):
        return {"action": "duplicate", "status": "skipped", "organization_id": org["id"]}

    await repo.set_subscription_status(org["id"], "canceled")
    return {"action": "subscription_deleted", "status": "canceled", "organization_id": org["id"]}
