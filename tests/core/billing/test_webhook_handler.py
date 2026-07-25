import uuid
import pytest
from datetime import datetime, timezone

pytestmark = pytest.mark.asyncio


@pytest.fixture
def valid_checkout_event():
    return {
        "id": "evt_checkout_001",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_001",
                "client_reference_id": str(uuid.uuid4()),
                "mode": "subscription",
                "customer": "cus_test001",
                "subscription": "sub_test001",
                "status": "complete",
            }
        },
    }


@pytest.fixture
def valid_invoice_paid_event():
    return {
        "id": "evt_invoice_001",
        "type": "invoice.paid",
        "data": {
            "object": {
                "id": "in_test_001",
                "customer": "cus_test001",
                "subscription": "sub_test001",
                "status": "paid",
                "period_start": datetime.now(timezone.utc).timestamp(),
                "period_end": datetime.now(timezone.utc).timestamp() + 2592000,
                "lines": {
                    "data": [
                        {
                            "price": {"id": ""},
                            "plan": {"product": "prod_starter"},
                        }
                    ]
                },
            }
        },
    }


async def test_handle_checkout_completed_sets_trialing(repo, sample_org, valid_checkout_event):
    from src.core.billing.webhook_handler import handle_stripe_webhook
    event = valid_checkout_event
    event["data"]["object"]["client_reference_id"] = str(sample_org["id"])
    result = await handle_stripe_webhook(event, repo)
    billing = await repo.get_organization_billing(sample_org["id"])
    assert billing["subscription_status"] == "trialing"
    assert billing["stripe_customer_id"] == "cus_test001"
    assert result["action"] == "subscription_created"


async def test_handle_checkout_completed_sets_trial_period(repo, sample_org, valid_checkout_event):
    from src.core.billing.webhook_handler import handle_stripe_webhook
    event = valid_checkout_event
    event["data"]["object"]["client_reference_id"] = str(sample_org["id"])
    await handle_stripe_webhook(event, repo)
    billing = await repo.get_organization_billing(sample_org["id"])
    assert billing["trial_start"] is not None
    assert billing["trial_end"] is not None


async def test_handle_invoice_paid_resets_usage(repo, sample_org, valid_invoice_paid_event):
    from src.core.billing.webhook_handler import handle_stripe_webhook
    await repo.update_organization_billing(sample_org["id"], {
        "stripe_customer_id": "cus_test001",
    })
    await repo.increment_message_usage(sample_org["id"])
    await repo.increment_message_usage(sample_org["id"])
    event = valid_invoice_paid_event
    event["data"]["object"]["customer"] = "cus_test001"
    await handle_stripe_webhook(event, repo)
    billing = await repo.get_organization_billing(sample_org["id"])
    assert billing["messages_used_this_period"] == 0
    assert billing["subscription_status"] == "active"


async def test_handle_invoice_paid_sets_period(repo, sample_org, valid_invoice_paid_event):
    from src.core.billing.webhook_handler import handle_stripe_webhook
    await repo.update_organization_billing(sample_org["id"], {
        "stripe_customer_id": "cus_test001",
    })
    event = valid_invoice_paid_event
    event["data"]["object"]["customer"] = "cus_test001"
    await handle_stripe_webhook(event, repo)
    billing = await repo.get_organization_billing(sample_org["id"])
    assert billing["current_period_start"] is not None
    assert billing["current_period_end"] is not None


async def test_handle_subscription_updated_changes_plan(repo, sample_org):
    from src.core.billing.webhook_handler import handle_stripe_webhook
    await repo.update_organization_billing(sample_org["id"], {
        "stripe_customer_id": "cus_test001",
        "plan": "starter",
        "messages_limit": 500,
    })
    event = {
        "id": "evt_sub_upd_001",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_test001",
                "customer": "cus_test001",
                "status": "active",
                "items": {
                    "data": [{"price": {"id": ""}, "plan": {"product": "prod_pro"}}]
                },
                "current_period_start": datetime.now(timezone.utc).timestamp(),
                "current_period_end": datetime.now(timezone.utc).timestamp() + 2592000,
            }
        },
    }
    await handle_stripe_webhook(event, repo)
    billing = await repo.get_organization_billing(sample_org["id"])
    assert billing["plan"] == "pro"
    assert billing["messages_limit"] == 2000


async def test_handle_subscription_deleted_sets_canceled(repo, sample_org):
    from src.core.billing.webhook_handler import handle_stripe_webhook
    await repo.update_organization_billing(sample_org["id"], {
        "stripe_customer_id": "cus_test001",
        "subscription_status": "active",
    })
    event = {
        "id": "evt_sub_del_001",
        "type": "subscription.deleted",
        "data": {
            "object": {
                "id": "sub_test001",
                "customer": "cus_test001",
            }
        },
    }
    await handle_stripe_webhook(event, repo)
    billing = await repo.get_organization_billing(sample_org["id"])
    assert billing["subscription_status"] == "canceled"


async def test_handle_invoice_payment_failed_sets_past_due(repo, sample_org):
    from src.core.billing.webhook_handler import handle_stripe_webhook
    await repo.update_organization_billing(sample_org["id"], {
        "stripe_customer_id": "cus_test001",
        "subscription_status": "active",
    })
    event = {
        "id": "evt_pay_fail_001",
        "type": "invoice.payment_failed",
        "data": {
            "object": {
                "id": "in_fail_001",
                "customer": "cus_test001",
                "subscription": "sub_test001",
            }
        },
    }
    await handle_stripe_webhook(event, repo)
    billing = await repo.get_organization_billing(sample_org["id"])
    assert billing["subscription_status"] == "past_due"


async def test_handle_unknown_event_does_nothing(repo, sample_org):
    from src.core.billing.webhook_handler import handle_stripe_webhook
    event = {"id": "evt_unknown_001", "type": "unknown.event", "data": {"object": {}}}
    result = await handle_stripe_webhook(event, repo)
    assert result is None


async def test_handle_checkout_completed_without_subscription(repo, sample_org):
    from src.core.billing.webhook_handler import handle_stripe_webhook
    event = {
        "id": "evt_no_sub_001",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_no_sub_001",
                "client_reference_id": str(sample_org["id"]),
                "mode": "setup",
                "customer": "cus_test002",
                "subscription": None,
                "status": "complete",
            }
        },
    }
    result = await handle_stripe_webhook(event, repo)
    assert result is None
    billing = await repo.get_organization_billing(sample_org["id"])
    assert billing["subscription_status"] == "incomplete"
