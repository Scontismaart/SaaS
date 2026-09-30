import pytest

pytestmark = pytest.mark.usefixtures("reset_db")


@pytest.mark.asyncio
async def test_record_and_query_usage(repo, sample_org):
    event = await repo.record_usage(
        organization_id=sample_org["id"],
        event_type="message_sent",
        quantity=1,
        metadata={"conversation_id": "conv-1"},
    )
    assert event["event_type"] == "message_sent"
    assert event["billing_month"] is not None

    billing_month = event["billing_month"]
    events = await repo.get_usage_by_month(
        sample_org["id"], billing_month.year, billing_month.month
    )
    assert len(events) >= 1


@pytest.mark.asyncio
async def test_usage_summary(repo, sample_org):
    expected_by_month = {}
    for _ in range(3):
        event = await repo.record_usage(
            organization_id=sample_org["id"],
            event_type="message_sent",
            quantity=1,
        )
        billing_month = event["billing_month"]
        expected = expected_by_month.setdefault(
            billing_month, {"message_sent": 0, "ai_response": 0}
        )
        expected["message_sent"] += 1
    event = await repo.record_usage(
        organization_id=sample_org["id"],
        event_type="ai_response",
        quantity=2,
    )
    billing_month = event["billing_month"]
    expected = expected_by_month.setdefault(
        billing_month, {"message_sent": 0, "ai_response": 0}
    )
    expected["ai_response"] += 2

    for billing_month, month_expected in expected_by_month.items():
        summary = await repo.get_usage_summary(
            sample_org["id"], billing_month.year, billing_month.month
        )
        assert summary.get("message_sent", 0) == month_expected["message_sent"]
        assert summary.get("ai_response", 0) == month_expected["ai_response"]
