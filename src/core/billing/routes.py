import os
import json
import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from src.core.auth.dependencies import require_ruolo
from src.core.auth.audit import audit_log
from src.core.billing.plans import PLANS
from src.core.billing.webhook_handler import handle_stripe_webhook

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/billing", tags=["billing"])


class CheckoutSessionRequest(BaseModel):
    plan: str
    success_url: str
    cancel_url: str


def _get_stripe():
    import stripe
    key = os.getenv("STRIPE_SECRET_KEY")
    if not key:
        raise HTTPException(status_code=503, detail="Stripe not configured")
    stripe.api_key = key
    return stripe


async def _stripe_call(call, *args, **kwargs):
    return await asyncio.to_thread(call, *args, **kwargs)


@router.post("/create-checkout-session")
async def create_checkout_session(
    req: CheckoutSessionRequest,
    request: Request,
    user: dict = Depends(require_ruolo("owner")),
):
    repo = getattr(request.app.state, "repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="Database not available")

    if req.plan not in PLANS:
        raise HTTPException(status_code=400, detail=f"Invalid plan: {req.plan}")

    org_id = user["organization_id"]
    org = await repo.get_organization_billing(org_id)

    st = _get_stripe()
    customer_id = org.get("stripe_customer_id")

    if not customer_id:
        customer = await _stripe_call(st.Customer.create)
        customer_id = customer.id
        await repo.update_organization_billing(org_id, {
            "stripe_customer_id": customer_id,
        })

    plan = PLANS[req.plan]
    if not plan.stripe_price_id:
        raise HTTPException(status_code=503, detail=f"Stripe price ID not configured for plan: {req.plan}")

    trial_days = int(os.getenv("STRIPE_TRIAL_DAYS", "7"))
    session = await _stripe_call(
        st.checkout.Session.create,
        customer=customer_id,
        line_items=[{"price": plan.stripe_price_id, "quantity": 1}],
        mode="subscription",
        success_url=req.success_url,
        cancel_url=req.cancel_url,
        client_reference_id=str(org_id),
        subscription_data={"trial_period_days": trial_days},
        payment_method_collection="if_required",
    )

    try:
        await audit_log(repo, organization_id=org_id,
                        action="billing.checkout_session_created",
                        auth_user_id=user.get("auth_user_id"),
                        target_table="organizations", target_id=str(org_id),
                        details={"plan": req.plan, "session_id": session.id})
    except Exception as e:
        logger.warning("Audit log failed: %s", e)

    return {"url": session.url}


@router.post("/create-portal-session")
async def create_portal_session(
    request: Request,
    user: dict = Depends(require_ruolo("owner")),
):
    repo = getattr(request.app.state, "repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="Database not available")

    org_id = user["organization_id"]
    org = await repo.get_organization_billing(org_id)
    customer_id = org.get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(status_code=400, detail="No Stripe customer found")

    st = _get_stripe()
    return_url = os.getenv("STRIPE_RETURN_URL", "http://localhost:5173/settings/billing")
    session = await _stripe_call(
        st.billing_portal.Session.create,
        customer=customer_id,
        return_url=return_url,
    )

    try:
        await audit_log(repo, organization_id=org_id,
                        action="billing.portal_session_created",
                        auth_user_id=user.get("auth_user_id"),
                        target_table="organizations", target_id=str(org_id))
    except Exception as e:
        logger.warning("Audit log failed: %s", e)

    return {"url": session.url}


@router.get("/subscription")
async def get_subscription(
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
):
    repo = getattr(request.app.state, "repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="Database not available")

    org_id = user["organization_id"]
    billing = await repo.get_organization_billing(org_id)
    return {
        "plan": billing.get("plan"),
        "subscription_status": billing.get("subscription_status"),
        "messages_limit": billing.get("messages_limit"),
        "users_limit": billing.get("users_limit"),
        "whatsapp_numbers_limit": billing.get("whatsapp_numbers_limit"),
        "messages_used_this_period": billing.get("messages_used_this_period"),
        "current_period_start": billing.get("current_period_start"),
        "current_period_end": billing.get("current_period_end"),
        "trial_start": billing.get("trial_start"),
        "trial_end": billing.get("trial_end"),
    }


@router.get("/usage")
async def get_usage(
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
):
    repo = getattr(request.app.state, "repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="Database not available")

    org_id = user["organization_id"]
    billing = await repo.get_organization_billing(org_id)
    limit = billing.get("messages_limit")
    used = billing.get("messages_used_this_period", 0)

    return {
        "messages_used": used,
        "messages_limit": limit,
        "percentage": round((used / limit * 100), 1) if limit and limit > 0 else 0,
    }


@router.post("/webhook")
async def billing_webhook(request: Request):
    repo = getattr(request.app.state, "repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="Database not available")

    body = await request.body()
    sig_header = request.headers.get("Stripe-Signature", "")
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    import stripe
    try:
        event = stripe.Webhook.construct_event(body, sig_header, secret)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    result = await handle_stripe_webhook(event.to_dict_recursive(), repo)
    if result is None:
        return {"status": "ignored"}
    if result.get("action"):
        try:
            await audit_log(repo,
                            organization_id=result.get("organization_id"),
                            action=f"billing.webhook.{result['action']}",
                            details={"stripe_event_id": event.get("id"),
                                     "stripe_event_type": event.get("type")})
        except Exception as e:
            logger.warning("Audit log failed: %s", e)
    return result
