from datetime import date, time
import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("reset_db")]


async def test_webhook_payment_mode_updates_booking(repo, sample_org):
    b = await repo.create_booking(organization_id=sample_org["id"], nome_cliente="Mario",
        data=date(2026, 8, 1), ora=time(20, 0), coperti=4, richiede_deposito=True)
    await repo.update_booking_payment(sample_org["id"], b["id"], "pending")
    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "mode": "payment",
                "metadata": {
                    "booking_id": str(b["id"]),
                    "organization_id": str(sample_org["id"]),
                },
                "id": "cs_test_abc123",
            }
        }
    }
    from src.core.billing.webhook_handler import handle_stripe_webhook
    result = await handle_stripe_webhook(event, repo, 7)
    assert result is not None
    updated = await repo.get_booking(sample_org["id"], b["id"])
    assert updated["payment_status"] == "paid"


async def test_webhook_payment_mode_fail_closed_without_org(repo, sample_org):
    """Metadata.organization_id assente: NESSUN update sul booking (fail-closed)."""
    b = await repo.create_booking(organization_id=sample_org["id"], nome_cliente="Mario",
        data=date(2026, 8, 1), ora=time(20, 0), coperti=4, richiede_deposito=True)
    await repo.update_booking_payment(sample_org["id"], b["id"], "pending")
    event = {
        "type": "checkout.session.completed",
        "id": "evt_noorg_001",
        "data": {
            "object": {
                "mode": "payment",
                "metadata": {"booking_id": str(b["id"])},
                "id": "cs_test_noorg",
            }
        }
    }
    from src.core.billing.webhook_handler import handle_stripe_webhook
    result = await handle_stripe_webhook(event, repo, 7)
    assert result is None
    updated = await repo.get_booking(sample_org["id"], b["id"])
    assert updated["payment_status"] == "pending"


async def test_webhook_payment_mode_fail_closed_malformed_org(repo, sample_org):
    """Metadata.organization_id non-UUID: NESSUN update sul booking (fail-closed)."""
    b = await repo.create_booking(organization_id=sample_org["id"], nome_cliente="Mario",
        data=date(2026, 8, 1), ora=time(20, 0), coperti=4, richiede_deposito=True)
    await repo.update_booking_payment(sample_org["id"], b["id"], "pending")
    event = {
        "type": "checkout.session.completed",
        "id": "evt_badorg_001",
        "data": {
            "object": {
                "mode": "payment",
                "metadata": {"booking_id": str(b["id"]), "organization_id": "not-a-uuid"},
                "id": "cs_test_badorg",
            }
        }
    }
    from src.core.billing.webhook_handler import handle_stripe_webhook
    result = await handle_stripe_webhook(event, repo, 7)
    assert result is None
    updated = await repo.get_booking(sample_org["id"], b["id"])
    assert updated["payment_status"] == "pending"


async def test_webhook_subscription_mode_unaffected(repo, sample_org):
    """Subscription mode logic is not touched."""
    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "mode": "subscription",
                "metadata": {},
                "id": "cs_test_sub_123",
                "client_reference_id": str(sample_org["id"]),
                "subscription": "sub_test_123",
                "customer": "cus_test_123",
            }
        }
    }
    from src.core.billing.webhook_handler import handle_stripe_webhook
    result = await handle_stripe_webhook(event, repo, 7)
    # Subscription mode, no booking match — returns a subscription result
    assert result is not None
    assert result.get("action") == "subscription_created"
