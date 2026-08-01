import json
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


async def handle_stripe_webhook(event: dict, repo, trial_days: int) -> dict | None:
    """Tutto il processing avviene in un'unica transazione DB: dedup INSERT
    e effetti billing sono atomici. Se il processo crasha a meta', la
    transazione fa rollback di tutto — l'evento NON risulta processato."""
    event_type = event.get("type")
    event_id = event.get("id", "")
    data_obj = event.get("data", {}).get("object", {})

    async with repo.pool.acquire() as conn:
        async with conn.transaction():
            if event_type == "checkout.session.completed":
                return await _handle_checkout_completed(conn, repo, data_obj, event_id, trial_days)
            if event_type == "invoice.paid":
                return await _handle_invoice_paid(conn, repo, data_obj, event_id)
            if event_type == "invoice.payment_failed":
                return await _handle_payment_failed(conn, repo, data_obj, event_id)
            if event_type == "customer.subscription.updated":
                return await _handle_subscription_updated(conn, repo, data_obj, event_id)
            if event_type == "subscription.deleted":
                return await _handle_subscription_deleted(conn, repo, data_obj, event_id)

    logger.info("Unhandled event type: %s", event_type)
    return None


async def _handle_checkout_completed(conn, repo, data, event_id, trial_days):
    mode = data.get("mode")

    if mode == "payment":
        metadata = data.get("metadata") or {}
        booking_id = metadata.get("booking_id")
        org_id = metadata.get("organization_id")
        if booking_id and org_id:
            if not await repo.process_stripe_event_in_tx(conn, event_id, org_id):
                return {"action": "duplicate", "status": "skipped", "organization_id": org_id}
            await conn.execute("""
                UPDATE bookings SET payment_status = 'paid', payment_link = $1,
                    updated_at = NOW()
                WHERE id = $2
            """, data.get("id"), booking_id)
            return {"action": "deposit_paid", "booking_id": booking_id, "organization_id": org_id}
        return None

    org_id = data.get("client_reference_id")
    subscription_id = data.get("subscription")
    customer_id = data.get("customer")

    if not org_id or not subscription_id or mode != "subscription":
        return None

    if not await repo.process_stripe_event_in_tx(conn, event_id, org_id):
        return {"action": "duplicate", "status": "skipped", "organization_id": org_id}

    now = datetime.now(timezone.utc)
    await conn.execute("""
        UPDATE organizations SET
            stripe_customer_id = $1, subscription_id = $2,
            subscription_status = 'trialing',
            trial_start = $3, trial_end = $4,
            current_period_start = $3, current_period_end = $4
        WHERE id = $5
    """, customer_id, subscription_id, now, now + timedelta(days=trial_days), org_id)
    return {"action": "subscription_created", "status": "trialing", "organization_id": org_id}


async def _lookup_org_by_customer(customer_id: str, repo, conn) -> dict | None:
    if not customer_id:
        return None
    row = await conn.fetchrow(
        "SELECT id, stripe_customer_id, subscription_status, plan, "
        "current_period_start, messages_used_this_period "
        "FROM organizations WHERE stripe_customer_id = $1",
        customer_id,
    )
    return dict(row) if row else None


async def _handle_invoice_paid(conn, repo, data, event_id):
    customer_id = data.get("customer")
    org = await _lookup_org_by_customer(customer_id, repo, conn)
    if not org:
        return None

    if not await repo.process_stripe_event_in_tx(conn, event_id, org["id"]):
        return {"action": "duplicate", "status": "skipped", "organization_id": org["id"]}

    period_start = datetime.fromtimestamp(data.get("period_start", 0), tz=timezone.utc)
    period_end = datetime.fromtimestamp(data.get("period_end", 0), tz=timezone.utc)

    plan_slug = None
    for line in data.get("lines", {}).get("data", []):
        price_id = line.get("price", {}).get("id", "")
        if price_id in PRICE_TO_PLAN:
            plan_slug = PRICE_TO_PLAN[price_id]
            break

    await conn.execute(
        "UPDATE organizations SET subscription_status = 'active' WHERE id = $1",
        org["id"],
    )
    if org.get("current_period_start") != period_start:
        await conn.execute("""
            UPDATE organizations SET
                messages_used_this_period = 0,
                current_period_start = $1,
                current_period_end = $2
            WHERE id = $3
        """, period_start, period_end, org["id"])

    if plan_slug:
        from src.core.billing.plans import get_plan
        plan = get_plan(plan_slug)
        await conn.execute("""
            UPDATE organizations SET
                plan = $1, messages_limit = $2, users_limit = $3,
                whatsapp_numbers_limit = $4
            WHERE id = $5
        """, plan_slug, plan.messages_limit, plan.users_limit, plan.whatsapp_numbers_limit, org["id"])

    return {"action": "subscription_activated", "status": "active", "organization_id": org["id"]}


async def _handle_payment_failed(conn, repo, data, event_id):
    customer_id = data.get("customer")
    org = await _lookup_org_by_customer(customer_id, repo, conn)
    if not org:
        return None

    if not await repo.process_stripe_event_in_tx(conn, event_id, org["id"]):
        return {"action": "duplicate", "status": "skipped", "organization_id": org["id"]}

    await conn.execute(
        "UPDATE organizations SET subscription_status = 'past_due' WHERE id = $1",
        org["id"],
    )
    return {"action": "payment_failed", "status": "past_due", "organization_id": org["id"]}


async def _handle_subscription_updated(conn, repo, data, event_id):
    customer_id = data.get("customer")
    org = await _lookup_org_by_customer(customer_id, repo, conn)
    if not org:
        return None

    if not await repo.process_stripe_event_in_tx(conn, event_id, org["id"]):
        return {"action": "duplicate", "status": "skipped", "organization_id": org["id"]}

    plan_slug = _resolve_plan_from_subscription(data)
    if plan_slug:
        from src.core.billing.plans import get_plan
        plan = get_plan(plan_slug)
        await conn.execute("""
            UPDATE organizations SET
                plan = $1, messages_limit = $2, users_limit = $3,
                whatsapp_numbers_limit = $4
            WHERE id = $5
        """, plan_slug, plan.messages_limit, plan.users_limit, plan.whatsapp_numbers_limit, org["id"])

    if data.get("status") == "past_due":
        await conn.execute(
            "UPDATE organizations SET subscription_status = 'past_due' WHERE id = $1",
            org["id"],
        )
    elif data.get("status") in ("active", "trialing"):
        current_status = org.get("subscription_status")
        if current_status != "active":
            await conn.execute(
                "UPDATE organizations SET subscription_status = $1 WHERE id = $2",
                data["status"], org["id"],
            )

    period_start = data.get("current_period_start")
    period_end = data.get("current_period_end")
    if period_start and period_end:
        new_start = datetime.fromtimestamp(period_start, tz=timezone.utc)
        if org.get("current_period_start") != new_start:
            await conn.execute("""
                UPDATE organizations SET
                    messages_used_this_period = 0,
                    current_period_start = $1,
                    current_period_end = $2
                WHERE id = $3
            """, new_start, datetime.fromtimestamp(period_end, tz=timezone.utc), org["id"])

    return {"action": "subscription_updated", "plan": plan_slug, "organization_id": org["id"]}


async def _handle_subscription_deleted(conn, repo, data, event_id):
    customer_id = data.get("customer")
    org = await _lookup_org_by_customer(customer_id, repo, conn)
    if not org:
        return None

    if not await repo.process_stripe_event_in_tx(conn, event_id, org["id"]):
        return {"action": "duplicate", "status": "skipped", "organization_id": org["id"]}

    await conn.execute(
        "UPDATE organizations SET subscription_status = 'canceled' WHERE id = $1",
        org["id"],
    )
    return {"action": "subscription_deleted", "status": "canceled", "organization_id": org["id"]}
