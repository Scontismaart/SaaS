import asyncio

import pytest

from src.core.reviews.idempotency import claim_external_review, claim_google_review_sync


class FakeConnection:
    async def fetchval(self, query, *_args):
        return True


class FakePool:
    def __init__(self, size):
        self.size = size
        self.active = 0
        self._available = asyncio.Semaphore(size)

    def get_max_size(self):
        return self.size

    async def acquire(self):
        await self._available.acquire()
        self.active += 1
        return FakeConnection()

    async def release(self, _connection):
        self.active -= 1
        self._available.release()


@pytest.mark.asyncio
async def test_pool_size_three_reserves_one_connection_across_sync_and_review_claims():
    pool = FakePool(3)
    async with claim_google_review_sync(pool, "org-a") as sync_claimed:
        assert sync_claimed is True
        async with claim_external_review(pool, "org-a", "review-a") as review_claimed:
            assert review_claimed is True

            async def wait_for_second_review_claim():
                async with claim_external_review(pool, "org-a", "review-b"):
                    return True

            pending = asyncio.create_task(wait_for_second_review_claim())
            await asyncio.sleep(0)
            spare = await asyncio.wait_for(pool.acquire(), timeout=0.1)
            assert pool.active == 3
            await pool.release(spare)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
    assert pool.active == 0


@pytest.mark.asyncio
async def test_pool_size_two_fails_closed_for_sync_and_review_claims():
    pool = FakePool(2)
    with pytest.raises(RuntimeError, match="three connections"):
        async with claim_google_review_sync(pool, "org-a"):
            pass
    with pytest.raises(RuntimeError, match="three connections"):
        async with claim_external_review(pool, "org-a", "review-a"):
            pass
    assert pool.active == 0
