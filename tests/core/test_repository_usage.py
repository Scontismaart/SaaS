from datetime import date

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

    oggi = date.today()
    events = await repo.get_usage_by_month(sample_org["id"], oggi.year, oggi.month)
    assert len(events) >= 1


@pytest.mark.asyncio
async def test_usage_summary(repo, sample_org):
    for _ in range(3):
        await repo.record_usage(
            organization_id=sample_org["id"],
            event_type="message_sent",
            quantity=1,
        )
    await repo.record_usage(
        organization_id=sample_org["id"],
        event_type="ai_response",
        quantity=2,
    )
    oggi = date.today()
    summary = await repo.get_usage_summary(sample_org["id"], oggi.year, oggi.month)
    assert summary["message_sent"] == 3
    assert summary["ai_response"] == 2
