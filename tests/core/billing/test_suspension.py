import pytest
from datetime import datetime, timedelta, timezone

from src.core.billing.suspension import is_org_suspended


class TestIsOrgSuspended:
    def test_canceled_always_suspended(self):
        assert is_org_suspended("canceled", None) is True

    def test_active_not_suspended_even_with_old_trial(self):
        past = datetime.now(timezone.utc) - timedelta(days=30)
        assert is_org_suspended("active", past) is False

    def test_past_due_not_suspended(self):
        past = datetime.now(timezone.utc) - timedelta(days=1)
        assert is_org_suspended("past_due", past) is False

    def test_trialing_with_future_trial_not_suspended(self):
        future = datetime.now(timezone.utc) + timedelta(days=5)
        assert is_org_suspended("trialing", future) is False

    def test_trialing_with_expired_trial_suspended(self):
        past = datetime.now(timezone.utc) - timedelta(minutes=1)
        assert is_org_suspended("trialing", past) is True

    def test_incomplete_with_expired_trial_suspended(self):
        past = datetime.now(timezone.utc) - timedelta(days=1)
        assert is_org_suspended("incomplete", past) is True

    def test_no_trial_not_suspended(self):
        assert is_org_suspended("trialing", None) is False

    def test_naive_datetime_treated_as_utc(self):
        past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
        assert is_org_suspended("trialing", past) is True


@pytest.mark.asyncio
async def test_suspension_notice_job_enqueues_once(pg_pool, sample_org):
    """Il job trial scaduto notifica una sola volta per org (claim atomico
    su suspension_notified_at). Una seconda esecuzione non ri-notifica."""
    from src.core.scheduler import _suspension_notice_job
    from src.core.notifications import email_service

    past = datetime.now(timezone.utc) - timedelta(days=1)
    async with pg_pool.acquire() as conn:
        await conn.execute(
            "UPDATE organizations SET subscription_status = 'trialing', trial_end = $1 WHERE id = $2",
            past, sample_org["id"],
        )

    email_service.start_worker()
    try:
        enqueued = []

        original = email_service._enqueue

        def fake_enqueue(event):
            enqueued.append(event)
            return original(event)

        email_service._enqueue = fake_enqueue

        await _suspension_notice_job(pg_pool)
        assert len(enqueued) == 1

        await _suspension_notice_job(pg_pool)
        assert len(enqueued) == 1
    finally:
        email_service._enqueue = original
        email_service.stop_worker()


@pytest.mark.asyncio
async def test_suspension_notice_job_skips_active_orgs(pg_pool, sample_org):
    from src.core.scheduler import _suspension_notice_job
    from src.core.notifications import email_service

    past = datetime.now(timezone.utc) - timedelta(days=1)
    async with pg_pool.acquire() as conn:
        await conn.execute(
            "UPDATE organizations SET subscription_status = 'active', trial_end = $1 WHERE id = $2",
            past, sample_org["id"],
        )

    email_service.start_worker()
    try:
        enqueued = []
        original = email_service._enqueue

        def fake_enqueue(event):
            enqueued.append(event)

        email_service._enqueue = fake_enqueue

        await _suspension_notice_job(pg_pool)
        assert enqueued == []
    finally:
        email_service._enqueue = original
        email_service.stop_worker()
