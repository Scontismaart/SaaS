import uuid

import pytest


@pytest.mark.asyncio
async def test_message_event_triggers_event_log(repo, sample_org, sample_contact):
    async with repo.pool.acquire() as conn:
        conv_id = uuid.uuid4()
        await conn.execute("""
            INSERT INTO conversations (id, organization_id, contact_id, status)
            VALUES ($1, $2, $3, 'active')
        """, conv_id, sample_org["id"], sample_contact["id"])

        msg_id = uuid.uuid4()
        await conn.execute("""
            INSERT INTO messages (id, organization_id, conversation_id, direction,
                                  message_type, content, content_text, status)
            VALUES ($1, $2, $3, 'inbound', 'text', '{"text":"test"}'::jsonb,
                    'test message', 'received_pending_ai')
        """, msg_id, sample_org["id"], conv_id)

        await conn.execute("""
            UPDATE messages SET status = 'handled', handling_type = 'ai_handled'
            WHERE id = $1
        """, msg_id)

    async with repo.pool.acquire() as conn:
        events = await conn.fetch(
            "SELECT * FROM event_log WHERE organization_id = $1 ORDER BY created_at",
            sample_org["id"],
        )
    assert len(events) >= 1
    assert events[0]["source_table"] == "messages"
    assert events[0]["tipo_evento"] == "messaggio"


@pytest.mark.asyncio
async def test_review_event_triggers_event_log(repo, sample_org):
    await repo.create_review(
        organization_id=sample_org["id"],
        testo="Bad food",
        valutazione_stelle=1,
        fonte="google",
    )
    async with repo.pool.acquire() as conn:
        events = await conn.fetch(
            "SELECT * FROM event_log WHERE organization_id = $1",
            sample_org["id"],
        )
    assert len(events) >= 1
    assert events[0]["source_table"] == "reviews"
    assert events[0]["tipo_evento"] == "recensione"
