from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Any

import asyncpg

from src.core.db.scoping import TenantScopedRepository, system_scope


class BillingRepository(TenantScopedRepository):
    """Repository specializzato per abbonamenti, limiti, eventi di utilizzo e integrazione Stripe."""

    def __init__(self, pool):
        self.pool = pool

    # ── Usage events ──────────────────────────────────────────

    async def record_usage(
        self, organization_id: uuid.UUID | str, event_type: str, quantity: int = 1, metadata: dict | None = None
    ) -> dict:
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO usage_events (id, organization_id, event_type,
                                          quantity, metadata)
                VALUES ($1, $2, $3, $4, $5::jsonb)
                RETURNING *
            """, uuid.uuid4(), organization_id, event_type, quantity,
            json.dumps(metadata or {}))
            return dict(row)

    async def get_usage_by_month(
        self, organization_id: uuid.UUID | str, year: int, month: int
    ) -> list[dict]:
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM usage_events
                WHERE organization_id = $1
                  AND billing_month = $2
                ORDER BY created_at
            """, organization_id, date(year, month, 1))
            return [dict(r) for r in rows]

    async def get_usage_summary(
        self, organization_id: uuid.UUID | str, year: int, month: int
    ) -> dict[str, int]:
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT event_type, SUM(quantity)::int as total
                FROM usage_events
                WHERE organization_id = $1
                  AND billing_month = $2
                GROUP BY event_type
            """, organization_id, date(year, month, 1))
            return {r["event_type"]: r["total"] for r in rows}

    # ── Abbonamento & Limiti Organizzazione ──────────────────

    async def get_organization_billing(self, organization_id: uuid.UUID | str) -> dict:
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT stripe_customer_id, subscription_id, subscription_status,
                       plan, messages_used_this_period, messages_limit,
                       users_limit, whatsapp_numbers_limit,
                       current_period_start, current_period_end,
                       trial_start, trial_end, suspension_notified_at
                FROM organizations WHERE id = $1
            """, organization_id)
            if row is None:
                raise ValueError(f"Organization {organization_id} not found")
            return dict(row)

    async def get_org_subscription_state(self, org_id: uuid.UUID | str) -> dict | None:
        if isinstance(org_id, str):
            org_id = uuid.UUID(org_id)
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT subscription_status, trial_end,
                       messages_used_this_period, messages_limit
                FROM organizations WHERE id = $1
            """, org_id)
            return dict(row) if row else None

    async def update_organization_billing(
        self, organization_id: uuid.UUID | str, data: dict
    ) -> dict:
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)
        sets = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(data))
        values = list(data.values())
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""UPDATE organizations SET {sets}
                    WHERE id = $1
                    RETURNING stripe_customer_id, subscription_id, subscription_status,
                              plan, messages_used_this_period, messages_limit,
                              users_limit, whatsapp_numbers_limit,
                              current_period_start, current_period_end,
                              trial_start, trial_end""",
                organization_id,
                *values,
            )
            return dict(row)

    async def set_subscription_status(
        self, organization_id: uuid.UUID | str, status: str
    ) -> None:
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE organizations SET subscription_status = $1 WHERE id = $2",
                status,
                organization_id,
            )

    async def check_message_usage(self, org_id: uuid.UUID | str) -> dict | None:
        if isinstance(org_id, str):
            org_id = uuid.UUID(org_id)
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT messages_used_this_period, messages_limit
                FROM organizations WHERE id = $1
            """, org_id)
            return dict(row) if row else None

    async def increment_message_usage(
        self, organization_id: uuid.UUID | str, conn=None
    ) -> int | None:
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)
        if conn is not None:
            return await self._increment_message_usage(conn, organization_id)
        async with self.pool.acquire() as c:
            return await self._increment_message_usage(c, organization_id)

    async def _increment_message_usage(self, conn, org_id: uuid.UUID) -> int | None:
        row = await conn.fetchrow("""
            UPDATE organizations
            SET messages_used_this_period = messages_used_this_period + 1
            WHERE id = $1 AND (messages_limit IS NULL OR messages_used_this_period < messages_limit)
            RETURNING messages_used_this_period
        """, org_id)
        return row["messages_used_this_period"] if row else None

    async def reset_message_usage(
        self,
        organization_id: uuid.UUID | str,
        period_start: datetime,
        period_end: datetime,
    ) -> None:
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)
        async with self.pool.acquire() as conn:
            await conn.execute(
                """UPDATE organizations
                   SET messages_used_this_period = 0,
                       current_period_start = $1,
                       current_period_end = $2
                   WHERE id = $3""",
                period_start,
                period_end,
                organization_id,
            )

    # ── Stripe Integration ────────────────────────────────────

    async def process_stripe_event(
        self, event_id: str, organization_id: uuid.UUID | str
    ) -> bool:
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    "INSERT INTO processed_stripe_events (event_id, organization_id) VALUES ($1, $2)",
                    event_id,
                    organization_id,
                )
                return True
            except asyncpg.exceptions.UniqueViolationError:
                return False

    async def process_stripe_event_in_tx(
        self, conn, event_id: str, organization_id: uuid.UUID | str
    ) -> bool:
        """Like process_stripe_event but uses an existing connection/transaction
        so the dedup INSERT and the billing effect run atomically together."""
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)
        try:
            await conn.execute(
                "INSERT INTO processed_stripe_events (event_id, organization_id) VALUES ($1, $2)",
                event_id,
                organization_id,
            )
            return True
        except asyncpg.exceptions.UniqueViolationError:
            return False

    async def update_plan_limits(
        self, organization_id: uuid.UUID | str, plan_slug: str
    ) -> dict:
        from src.core.billing.plans import get_plan
        plan = get_plan(plan_slug)
        if isinstance(organization_id, str):
            organization_id = uuid.UUID(organization_id)
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE organizations
                   SET plan = $1,
                       messages_limit = $2,
                       users_limit = $3,
                       whatsapp_numbers_limit = $4
                   WHERE id = $5
                   RETURNING stripe_customer_id, subscription_id, subscription_status,
                             plan, messages_used_this_period, messages_limit,
                             users_limit, whatsapp_numbers_limit,
                             current_period_start, current_period_end,
                             trial_start, trial_end""",
                plan_slug,
                plan.messages_limit,
                plan.users_limit,
                plan.whatsapp_numbers_limit,
                organization_id,
            )
            return dict(row)

    @system_scope("risoluzione tenant da stripe_customer_id platform-unique")
    async def get_organization_by_stripe_customer(
        self, stripe_customer_id: str
    ) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, stripe_customer_id, subscription_status, plan, "
                "current_period_start "
                "FROM organizations WHERE stripe_customer_id = $1",
                stripe_customer_id,
            )
            if row is None:
                return None
            return dict(row)
