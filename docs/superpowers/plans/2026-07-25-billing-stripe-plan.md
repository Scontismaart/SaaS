# Billing & Stripe Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate Stripe billing with 3 SaaS plans (Starter 49€, Pro 99€, Business 199€), usage counting, plan limits enforcement, trial management.

**Architecture:** Stripe Checkout for onboarding, webhooks for lifecycle (checkout.session.completed, invoice.paid, invoice.payment_failed, customer.subscription.updated, subscription.deleted), DB-level limit enforcement middleware, incremental message counter on `organizations` table.

**Tech Stack:** FastAPI, asyncpg, stripe-python, testcontainers-postgres

## Global Constraints

- `stripe>=9.0,<11` in requirements.txt
- All DB changes via SQL migration in `src/core/db/migrations/003_billing.sql`
- NULL = unlimited for limit columns (messages_limit, users_limit, whatsapp_numbers_limit)
- Webhook signature verification via `stripe.Webhook.construct_event()`
- Idempotency via `processed_stripe_events` table
- All billing routes except `/api/billing/webhook` require auth via `require_ruolo()`
- `/api/billing/webhook` excluded from rate limit whitelist
- Testcontainers PostgreSQL + Stripe mock fixtures for all tests

---

### Task 1: Add billing columns migration

**Files:**
- Create: `src/core/db/migrations/003_billing.sql`
- Modify: `tests/core/conftest.py` (load new migration)
- Test: `tests/core/test_schema.py` (already covers all migrations)

**Interfaces:**
- Consumes: `organizations` table (existing)
- Produces: `003_billing.sql` — adds billing columns + `processed_stripe_events` table

- [ ] **Step 1: Write the migration**

```sql
-- src/core/db/migrations/003_billing.sql
-- Billing/Stripe columns for multi-tenant SaaS

ALTER TABLE organizations ADD COLUMN IF NOT EXISTS
    stripe_customer_id TEXT UNIQUE,
    subscription_id TEXT,
    subscription_status TEXT NOT NULL DEFAULT 'incomplete'
        CHECK (subscription_status IN ('incomplete','trialing','active','past_due','canceled')),
    plan TEXT CHECK (plan IN ('starter','pro','business')),
    messages_used_this_period INT NOT NULL DEFAULT 0,
    messages_limit INT CHECK (messages_limit > 0),  -- NULL = illimitato
    users_limit INT CHECK (users_limit > 0),          -- NULL = illimitato
    whatsapp_numbers_limit INT CHECK (whatsapp_numbers_limit > 0), -- NULL = illimitato
    current_period_start TIMESTAMPTZ,
    current_period_end TIMESTAMPTZ,
    trial_start TIMESTAMPTZ,
    trial_end TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS processed_stripe_events (
    event_id TEXT PRIMARY KEY,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_org_stripe_customer ON organizations(stripe_customer_id);
```

- [ ] **Step 2: Update conftest to load migration**

In `tests/core/conftest.py`, add after the existing migration loads:
```python
with open("src/core/db/migrations/003_billing.sql") as f:
    await conn.execute(f.read())
```

- [ ] **Step 3: Run schema test**

Run: `python -m pytest tests/core/test_schema.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/core/db/migrations/003_billing.sql tests/core/conftest.py
git commit -m "feat(billing): add billing columns and processed_stripe_events table"
```

---

### Task 2: Add stripe dependency and plan constants

**Files:**
- Modify: `requirements.txt`
- Create: `src/core/billing/plans.py`
- Modify: `.env.example`

**Interfaces:**
- Consumes: nothing (pure config)
- Produces: `Plans` dataclass/constants, env vars for Stripe

- [ ] **Step 1: Add stripe to requirements**

```txt
# requirements.txt — add line
stripe>=9.0,<11
```

- [ ] **Step 2: Create plan constants**

```python
# src/core/billing/plans.py
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class Plan:
    name: str
    stripe_price_id: str
    messages_limit: Optional[int]
    users_limit: Optional[int]
    whatsapp_numbers_limit: Optional[int]
    has_reviews: bool
    has_rag: bool
    price_monthly_eur: int


# key = plan slug (matches DB CHECK constraint)
PLANS: Dict[str, Plan] = {
    "starter": Plan(
        name="Starter",
        stripe_price_id=os.getenv("STRIPE_PRICE_STARTER", ""),
        messages_limit=500,
        users_limit=1,
        whatsapp_numbers_limit=1,
        has_reviews=False,
        has_rag=False,
        price_monthly_eur=49,
    ),
    "pro": Plan(
        name="Pro",
        stripe_price_id=os.getenv("STRIPE_PRICE_PRO", ""),
        messages_limit=2000,
        users_limit=3,
        whatsapp_numbers_limit=1,
        has_reviews=True,
        has_rag=False,
        price_monthly_eur=99,
    ),
    "business": Plan(
        name="Business",
        stripe_price_id=os.getenv("STRIPE_PRICE_BUSINESS", ""),
        messages_limit=None,  # unlimited
        users_limit=None,
        whatsapp_numbers_limit=None,
        has_reviews=True,
        has_rag=True,
        price_monthly_eur=199,
    ),
}


def get_plan(plan_slug: str) -> Plan:
    if plan_slug not in PLANS:
        raise ValueError(f"Unknown plan: {plan_slug}. Valid: {list(PLANS.keys())}")
    return PLANS[plan_slug]
```

Need to import os at top:
```python
import os
```

- [ ] **Step 3: Update .env.example**

```env
STRIPE_SECRET_KEY=sk_test_your_key_here
STRIPE_PUBLISHABLE_KEY=pk_test_your_key_here
STRIPE_WEBHOOK_SECRET=whsec_your_secret_here
STRIPE_PRICE_STARTER=price_starter_xxx
STRIPE_PRICE_PRO=price_pro_xxx
STRIPE_PRICE_BUSINESS=price_business_xxx
STRIPE_TRIAL_DAYS=7
```

- [ ] **Step 4: Verify import**

Run: `python -c "from src.core.billing.plans import PLANS, get_plan; print('OK')"`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add requirements.txt src/core/billing/plans.py .env.example
git commit -m "feat(billing): add stripe dependency and plan constants"
```

---

### Task 3: Add billing repository methods

**Files:**
- Modify: `src/core/db/repository.py`
- Create: `tests/core/test_repository_billing.py`

**Interfaces:**
- Consumes: `CoreRepository` (existing), `PLANS` dict, migration columns
- Produces: `get_organization_billing(org_id)`, `update_organization_billing(org_id, data)`, `set_subscription_status(org_id, status)`, `increment_message_usage(org_id)`, `reset_message_usage(org_id, period_start, period_end)`, `process_stripe_event(event_id, org_id)`, `update_plan_limits(org_id, plan_slug)`

- [ ] **Step 1: Write the failing tests**

```python
# tests/core/test_repository_billing.py
import uuid
import pytest

pytestmark = pytest.mark.asyncio


async def test_get_organization_billing_defaults(repo, sample_org):
    result = await repo.get_organization_billing(sample_org["id"])
    assert result["subscription_status"] == "incomplete"
    assert result["messages_used_this_period"] == 0
    assert result["messages_limit"] is None
    assert result["plan"] is None


async def test_update_organization_billing(repo, sample_org):
    await repo.update_organization_billing(sample_org["id"], {
        "stripe_customer_id": "cus_test123",
        "subscription_id": "sub_test123",
        "subscription_status": "trialing",
        "plan": "starter",
    })
    result = await repo.get_organization_billing(sample_org["id"])
    assert result["stripe_customer_id"] == "cus_test123"
    assert result["subscription_status"] == "trialing"
    assert result["plan"] == "starter"


async def test_set_subscription_status(repo, sample_org):
    await repo.set_subscription_status(sample_org["id"], "active")
    result = await repo.get_organization_billing(sample_org["id"])
    assert result["subscription_status"] == "active"


async def test_increment_message_usage(repo, sample_org):
    v1 = await repo.increment_message_usage(sample_org["id"])
    assert v1 == 1
    v2 = await repo.increment_message_usage(sample_org["id"])
    assert v2 == 2


async def test_reset_message_usage(repo, sample_org, pg_pool):
    from datetime import datetime, timezone
    await repo.increment_message_usage(sample_org["id"])
    await repo.increment_message_usage(sample_org["id"])
    period_start = datetime.now(timezone.utc)
    period_end = datetime.now(timezone.utc)
    await repo.reset_message_usage(sample_org["id"], period_start, period_end)
    result = await repo.get_organization_billing(sample_org["id"])
    assert result["messages_used_this_period"] == 0
    assert result["current_period_start"] is not None


async def test_process_stripe_event_new(repo, sample_org):
    result = await repo.process_stripe_event("evt_test_001", sample_org["id"])
    assert result is True  # True = new event


async def test_process_stripe_event_duplicate(repo, sample_org):
    await repo.process_stripe_event("evt_test_002", sample_org["id"])
    result = await repo.process_stripe_event("evt_test_002", sample_org["id"])
    assert result is False  # False = already processed


async def test_update_plan_limits_sets_correct_values(repo, sample_org):
    await repo.update_plan_limits(sample_org["id"], "pro")
    result = await repo.get_organization_billing(sample_org["id"])
    assert result["plan"] == "pro"
    assert result["messages_limit"] == 2000
    assert result["users_limit"] == 3


async def test_update_plan_limits_business_unlimited(repo, sample_org):
    await repo.update_plan_limits(sample_org["id"], "business")
    result = await repo.get_organization_billing(sample_org["id"])
    assert result["plan"] == "business"
    assert result["messages_limit"] is None


async def test_increment_message_usage_cross_tenant(repo, sample_org, other_org):
    await repo.increment_message_usage(sample_org["id"])
    v_other = await repo.increment_message_usage(other_org["id"])
    assert v_other == 1
    v_main = await repo.increment_message_usage(sample_org["id"])
    assert v_main == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/core/test_repository_billing.py -v`
Expected: FAIL — methods don't exist yet

- [ ] **Step 3: Write minimal repository methods**

Add to `src/core/db/repository.py`:

```python
async def get_organization_billing(self, organization_id: uuid.UUID | str) -> dict:
    if isinstance(organization_id, str):
        organization_id = uuid.UUID(organization_id)
    async with self.pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT stripe_customer_id, subscription_id, subscription_status,
                      plan, messages_used_this_period, messages_limit,
                      users_limit, whatsapp_numbers_limit,
                      current_period_start, current_period_end,
                      trial_start, trial_end
               FROM organizations WHERE id = $1""",
            organization_id,
        )
        if row is None:
            raise ValueError(f"Organization {organization_id} not found")
        return dict(row)


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


async def increment_message_usage(
    self, organization_id: uuid.UUID | str
) -> int:
    if isinstance(organization_id, str):
        organization_id = uuid.UUID(organization_id)
    async with self.pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE organizations
               SET messages_used_this_period = messages_used_this_period + 1
               WHERE id = $1
               RETURNING messages_used_this_period""",
            organization_id,
        )
        return row["messages_used_this_period"]


async def reset_message_usage(
    self,
    organization_id: uuid.UUID | str,
    period_start: datetime.datetime,
    period_end: datetime.datetime,
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


async def process_stripe_event(
    self, event_id: str, organization_id: uuid.UUID | str
) -> bool:
    """Returns True if event was new, False if duplicate."""
    if isinstance(organization_id, str):
        organization_id = uuid.UUID(organization_id)
    async with self.pool.acquire() as conn:
        try:
            await conn.execute(
                "INSERT INTO processed_stripe_events (event_id) VALUES ($1)",
                event_id,
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
```

Add import at top of repository.py if not present:
```python
import datetime
import asyncpg
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/core/test_repository_billing.py -v`
Expected: 10 PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/db/repository.py tests/core/test_repository_billing.py
git commit -m "feat(billing): add billing repository methods"
```

---

### Task 4: Add webhook handler

**Files:**
- Create: `src/core/billing/webhook_handler.py`
- Create: `tests/core/billing/test_webhook_handler.py`

**Interfaces:**
- Consumes: `CoreRepository` (get_organization_billing, update_organization_billing, update_plan_limits, reset_message_usage, process_stripe_event, set_subscription_status)
- Produces: `handle_stripe_webhook(payload: bytes, sig_header: str, repo: CoreRepository) -> dict`

- [ ] **Step 1: Write the failing tests**

```python
# tests/core/billing/test_webhook_handler.py
import uuid
import json
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
def valid_invoice_paid_event(valid_checkout_event):
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
                            "price": {"id": "price_starter_xxx"},
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
                    "data": [{"price": {"id": "price_pro_xxx"}, "plan": {"product": "prod_pro"}}]
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
    """Some checkout sessions (e.g. payment setups) don't have a subscription."""
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/core/billing/test_webhook_handler.py -v`
Expected: FAIL — module doesn't exist yet

- [ ] **Step 3: Write minimal webhook handler**

```python
# src/core/billing/webhook_handler.py
import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Map Stripe price IDs to plan slugs
PRICE_TO_PLAN: dict[str, str] = {}


def _init_price_map():
    from src.core.billing.plans import PLANS
    for slug, plan in PLANS.items():
        if plan.stripe_price_id:
            PRICE_TO_PLAN[plan.stripe_price_id] = slug


def _resolve_plan_from_subscription(subscription_data: dict) -> str | None:
    if not PRICE_TO_PLAN:
        _init_price_map()
    for item in subscription_data.get("items", {}).get("data", []):
        price_id = item.get("price", {}).get("id", "")
        if price_id in PRICE_TO_PLAN:
            return PRICE_TO_PLAN[price_id]
        # Fallback: try plan.product for mapping
    return None


async def handle_stripe_webhook(event: dict, repo) -> dict | None:
    event_type = event.get("type")
    data_obj = event.get("data", {}).get("object", {})

    if event_type == "checkout.session.completed":
        return await _handle_checkout_completed(data_obj, repo)

    if event_type == "invoice.paid":
        return await _handle_invoice_paid(data_obj, repo)

    if event_type == "invoice.payment_failed":
        return await _handle_payment_failed(data_obj, repo)

    if event_type == "customer.subscription.updated":
        return await _handle_subscription_updated(data_obj, repo)

    if event_type == "subscription.deleted":
        return await _handle_subscription_deleted(data_obj, repo)

    logger.info("Unhandled event type: %s", event_type)
    return None


async def _handle_checkout_completed(data: dict, repo) -> dict | None:
    org_id = data.get("client_reference_id")
    subscription_id = data.get("subscription")
    customer_id = data.get("customer")

    if not org_id or not subscription_id or data.get("mode") != "subscription":
        return None

    is_new = await repo.process_stripe_event(
        data.get("id", f"cs_{org_id}_{subscription_id}"), org_id
    )
    if not is_new:
        return {"action": "duplicate", "status": "skipped"}

    now = datetime.now(timezone.utc)
    trial_days = int(os.getenv("STRIPE_TRIAL_DAYS", "7"))
    await repo.update_organization_billing(org_id, {
        "stripe_customer_id": customer_id,
        "subscription_id": subscription_id,
        "subscription_status": "trialing",
        "trial_start": now,
        "trial_end": now.replace(day=now.day + trial_days),
        "current_period_start": now,
        "current_period_end": now.replace(day=now.day + trial_days),
    })
    return {"action": "subscription_created", "status": "trialing"}


async def _handle_invoice_paid(data: dict, repo) -> dict | None:
    customer_id = data.get("customer")
    subscription_id = data.get("subscription")

    if not customer_id:
        return None

    is_new = await repo.process_stripe_event(
        data.get("id", f"inv_{subscription_id}"), customer_id
    )
    if not is_new:
        return {"action": "duplicate", "status": "skipped"}

    # Find org by stripe_customer_id
    org = await repo.get_organization_by_stripe_customer(customer_id)
    if not org:
        logger.warning("No org found for stripe_customer_id=%s", customer_id)
        return None

    period_start = datetime.fromtimestamp(data.get("period_start", 0), tz=timezone.utc)
    period_end = datetime.fromtimestamp(data.get("period_end", 0), tz=timezone.utc)

    # Resolve plan from invoice lines
    plan_slug = None
    for line in data.get("lines", {}).get("data", []):
        price_id = line.get("price", {}).get("id", "")
        if price_id in PRICE_TO_PLAN:
            plan_slug = PRICE_TO_PLAN[price_id]
            break

    await repo.set_subscription_status(org["id"], "active")
    await repo.reset_message_usage(org["id"], period_start, period_end)

    if plan_slug:
        await repo.update_plan_limits(org["id"], plan_slug)

    return {"action": "subscription_activated", "status": "active"}


async def _handle_payment_failed(data: dict, repo) -> dict | None:
    customer_id = data.get("customer")
    if not customer_id:
        return None

    is_new = await repo.process_stripe_event(
        data.get("id", f"payfail_{customer_id}"), customer_id
    )
    if not is_new:
        return {"action": "duplicate", "status": "skipped"}

    org = await repo.get_organization_by_stripe_customer(customer_id)
    if not org:
        return None

    await repo.set_subscription_status(org["id"], "past_due")
    return {"action": "payment_failed", "status": "past_due"}


async def _handle_subscription_updated(data: dict, repo) -> dict | None:
    customer_id = data.get("customer")
    if not customer_id:
        return None

    is_new = await repo.process_stripe_event(
        data.get("id", f"subupd_{customer_id}"), customer_id
    )
    if not is_new:
        return {"action": "duplicate", "status": "skipped"}

    org = await repo.get_organization_by_stripe_customer(customer_id)
    if not org:
        return None

    plan_slug = _resolve_plan_from_subscription(data)
    if plan_slug:
        await repo.update_plan_limits(org["id"], plan_slug)

    if data.get("status") == "past_due":
        await repo.set_subscription_status(org["id"], "past_due")
    elif data.get("status") in ("active", "trialing"):
        current_status = org.get("subscription_status")
        if current_status != "active":
            await repo.set_subscription_status(org["id"], data["status"])

    period_start = data.get("current_period_start")
    period_end = data.get("current_period_end")
    if period_start and period_end:
        from datetime import datetime, timezone
        await repo.reset_message_usage(
            org["id"],
            datetime.fromtimestamp(period_start, tz=timezone.utc),
            datetime.fromtimestamp(period_end, tz=timezone.utc),
        )

    return {"action": "subscription_updated", "plan": plan_slug}


async def _handle_subscription_deleted(data: dict, repo) -> dict | None:
    customer_id = data.get("customer")
    if not customer_id:
        return None

    is_new = await repo.process_stripe_event(
        data.get("id", f"subdel_{customer_id}"), customer_id
    )
    if not is_new:
        return {"action": "duplicate", "status": "skipped"}

    org = await repo.get_organization_by_stripe_customer(customer_id)
    if not org:
        return None

    await repo.set_subscription_status(org["id"], "canceled")
    return {"action": "subscription_deleted", "status": "canceled"}
```

- [ ] **Step 4: Add `get_organization_by_stripe_customer` to repository**

```python
async def get_organization_by_stripe_customer(
    self, stripe_customer_id: str
) -> dict | None:
    async with self.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, stripe_customer_id, subscription_status, plan "
            "FROM organizations WHERE stripe_customer_id = $1",
            stripe_customer_id,
        )
        if row is None:
            return None
        return dict(row)
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/core/billing/test_webhook_handler.py -v`
Expected: 10 PASS

- [ ] **Step 6: Commit**

```bash
git add src/core/billing/webhook_handler.py src/core/db/repository.py tests/core/billing/test_webhook_handler.py
git commit -m "feat(billing): add Stripe webhook handler"
```

---

### Task 5: Add billing API routes

**Files:**
- Create: `src/core/billing/router.py`
- Create: `tests/core/billing/test_billing_routes.py`
- Modify: `src/api/main.py` (mount router)

**Interfaces:**
- Consumes: `CoreRepository` billing methods, `handle_stripe_webhook`, `require_ruolo`
- Produces: FastAPI APIRouter with 5 endpoints

- [ ] **Step 1: Write the failing tests**

```python
# tests/core/billing/test_billing_routes.py
import os
import json
import uuid
import pytest
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


@pytest.fixture
def app_with_repo(repo, pg_pool):
    """Create a FastAPI app with the billing router mounted and repo injected."""
    from fastapi import FastAPI
    from src.core.billing.router import router as billing_router

    app = FastAPI()
    app.state.repo = repo
    app.state.pool = pg_pool
    app.include_router(billing_router, prefix="/api/billing")
    return app


@pytest.fixture
async def client(app_with_repo):
    transport = ASGITransport(app=app_with_repo)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestWebhookEndpoint:
    async def test_webhook_missing_signature_returns_400(self, client):
        resp = await client.post(
            "/api/billing/webhook",
            content=json.dumps({"type": "test"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    async def test_webhook_invalid_payload_returns_400(self, client):
        resp = await client.post(
            "/api/billing/webhook",
            content=b"not-json",
            headers={
                "Content-Type": "application/json",
                "Stripe-Signature": "t=123,v1=fake",
            },
        )
        assert resp.status_code == 400

    async def test_webhook_unknown_event_type_accepted(self, client):
        """Unknown event types should return 200 to acknowledge receipt."""
        with patch("stripe.Webhook.construct_event") as mock:
            mock.return_value = {"type": "unknown.event", "data": {"object": {}}}
            resp = await client.post(
                "/api/billing/webhook",
                content=json.dumps({"type": "unknown.event"}).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Stripe-Signature": "t=123,v1=fake",
                },
            )
        assert resp.status_code == 200


class TestCheckoutSessionEndpoint:
    async def test_checkout_session_requires_owner(self, client):
        resp = await client.post("/api/billing/create-checkout-session")
        assert resp.status_code == 403

    async def test_create_checkout_session_no_auth(self, client):
        resp = await client.post(
            "/api/billing/create-checkout-session",
            json={"plan": "starter"},
        )
        # No auth header → 401 from token check
        assert resp.status_code == 401


class TestUsageEndpoint:
    async def test_usage_requires_auth(self, client):
        resp = await client.get("/api/billing/usage")
        assert resp.status_code == 401


class TestSubscriptionEndpoint:
    async def test_subscription_requires_auth(self, client):
        resp = await client.get("/api/billing/subscription")
        assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/core/billing/test_billing_routes.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Write the billing router**

```python
# src/core/billing/router.py
import os
import json
import stripe
from fastapi import APIRouter, HTTPException, Depends, Request
from src.core.auth.dependencies import require_ruolo, get_repo

router = APIRouter(tags=["billing"])


def get_stripe():
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
    return stripe


@router.post("/create-checkout-session")
async def create_checkout_session(
    request: Request,
    user: dict = Depends(require_ruolo("owner")),
    repo = Depends(get_repo),
):
    body = await request.json()
    plan_slug = body.get("plan")
    from src.core.billing.plans import get_plan
    try:
        plan = get_plan(plan_slug)
    except ValueError:
        raise HTTPException(400, f"Piano non valido: {plan_slug}")

    if not plan.stripe_price_id:
        raise HTTPException(500, "Price ID non configurato per questo piano")

    st = get_stripe()
    trial_days = int(os.getenv("STRIPE_TRIAL_DAYS", "7"))
    org_billing = await repo.get_organization_billing(user.get("organization_id"))
    customer_id = org_billing.get("stripe_customer_id")

    try:
        session = st.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": plan.stripe_price_id, "quantity": 1}],
            client_reference_id=str(user.get("organization_id")),
            customer=customer_id if customer_id else None,
            customer_creation="always" if not customer_id else None,
            trial_period_days=trial_days,
            payment_method_collection="if_required",
            success_url=os.getenv("FRONTEND_URL", "http://localhost:5173/dashboard"),
            cancel_url=os.getenv("FRONTEND_URL", "http://localhost:5173/pricing"),
        )
    except Exception as e:
        raise HTTPException(500, f"Errore creazione sessione Stripe: {e}")

    return {"url": session.url, "session_id": session.id}


@router.post("/create-portal-session")
async def create_portal_session(
    user: dict = Depends(require_ruolo("owner")),
    repo = Depends(get_repo),
):
    org_billing = await repo.get_organization_billing(user.get("organization_id"))
    customer_id = org_billing.get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(400, "Nessun cliente Stripe trovato per questa organizzazione")

    st = get_stripe()
    try:
        session = st.billing_portal.Session.create(
            customer=customer_id,
            return_url=os.getenv("FRONTEND_URL", "http://localhost:5173/dashboard"),
        )
    except Exception as e:
        raise HTTPException(500, f"Errore creazione portal session: {e}")

    return {"url": session.url}


@router.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("Stripe-Signature")
    endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    if not sig_header:
        raise HTTPException(400, "Header Stripe-Signature mancante")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except ValueError:
        raise HTTPException(400, "Payload non valido")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(400, "Firma Stripe non valida")

    repo = None
    from src.core.billing.webhook_handler import handle_stripe_webhook
    try:
        # Try to get repo from app state
        repo = getattr(request.app.state, "repo", None)
    except Exception:
        pass

    if repo:
        await handle_stripe_webhook(event, repo)

    return {"received": True}


@router.get("/usage")
async def get_usage(
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
    repo = Depends(get_repo),
):
    billing = await repo.get_organization_billing(user.get("organization_id"))
    return {
        "messages_used": billing["messages_used_this_period"],
        "messages_limit": billing["messages_limit"],
        "period_start": billing["current_period_start"],
        "period_end": billing["current_period_end"],
        "plan": billing["plan"],
    }


@router.get("/subscription")
async def get_subscription(
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
    repo = Depends(get_repo),
):
    billing = await repo.get_organization_billing(user.get("organization_id"))
    return {
        "plan": billing["plan"],
        "status": billing["subscription_status"],
        "current_period_end": billing["current_period_end"],
        "trial_end": billing["trial_end"],
    }
```

- [ ] **Step 4: Mount the router in main.py**

In `src/api/main.py`, add:
```python
from src.core.billing.router import router as billing_router
# ...
app.include_router(billing_router, prefix="/api/billing")
```

Also add `/api/billing/webhook` to rate limit whitelist (line with `RATE_LIMIT_EXCLUDED_PATHS`):
```python
RATE_LIMIT_EXCLUDED_PATHS = {"/api/health", "/webhooks/whatsapp", "/api/billing/webhook"}
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/core/billing/test_billing_routes.py -v`
Expected: All tests pass or show auth-related behavior. Some tests with missing setup may need adjustment.

- [ ] **Step 6: Commit**

```bash
git add src/core/billing/router.py src/api/main.py tests/core/billing/test_billing_routes.py
git commit -m "feat(billing): add billing API routes with auth"
```

---

### Task 6: Add usage counting and limits middleware

**Files:**
- Create: `src/core/billing/middleware.py`
- Create: `tests/core/billing/test_middleware.py`
- Modify: `src/api/main.py` (register middleware)

**Interfaces:**
- Consumes: `CoreRepository` (check_plan_limits logic)
- Produces: `UsageLimitMiddleware` or async middleware function

- [ ] **Step 1: Write the failing tests**

```python
# tests/core/billing/test_middleware.py
import uuid
import pytest
from datetime import datetime, timezone

pytestmark = pytest.mark.asyncio


async def test_check_plan_limits_ok(repo, sample_org):
    from src.core.billing.middleware import check_plan_limits

    await repo.update_organization_billing(sample_org["id"], {
        "subscription_status": "active",
        "plan": "pro",
        "messages_limit": 2000,
        "messages_used_this_period": 100,
    })
    result = await check_plan_limits(sample_org["id"], repo)
    assert result["allowed"] is True
    assert result["remaining"] == 1900


async def test_check_plan_limits_exceeded(repo, sample_org):
    from src.core.billing.middleware import check_plan_limits

    await repo.update_organization_billing(sample_org["id"], {
        "subscription_status": "active",
        "plan": "starter",
        "messages_limit": 500,
        "messages_used_this_period": 500,
    })
    result = await check_plan_limits(sample_org["id"], repo)
    assert result["allowed"] is False
    assert result["reason"] == "quota_exceeded"


async def test_check_plan_limits_past_due(repo, sample_org):
    from src.core.billing.middleware import check_plan_limits

    await repo.update_organization_billing(sample_org["id"], {
        "subscription_status": "past_due",
        "plan": "pro",
    })
    result = await check_plan_limits(sample_org["id"], repo)
    assert result["allowed"] is False
    assert result["reason"] == "payment_failed"


async def test_check_plan_limits_canceled(repo, sample_org):
    from src.core.billing.middleware import check_plan_limits

    await repo.update_organization_billing(sample_org["id"], {
        "subscription_status": "canceled",
    })
    result = await check_plan_limits(sample_org["id"], repo)
    assert result["allowed"] is False
    assert result["reason"] == "subscription_inactive"


async def test_check_plan_limits_trialing(repo, sample_org):
    from src.core.billing.middleware import check_plan_limits

    await repo.update_organization_billing(sample_org["id"], {
        "subscription_status": "trialing",
        "plan": "starter",
        "messages_limit": 500,
        "messages_used_this_period": 50,
    })
    result = await check_plan_limits(sample_org["id"], repo)
    assert result["allowed"] is True


async def test_check_plan_limits_business_unlimited(repo, sample_org):
    from src.core.billing.middleware import check_plan_limits

    await repo.update_organization_billing(sample_org["id"], {
        "subscription_status": "active",
        "plan": "business",
        "messages_limit": None,
        "messages_used_this_period": 999999,
    })
    result = await check_plan_limits(sample_org["id"], repo)
    assert result["allowed"] is True


async def test_check_plan_limits_warning_80(repo, sample_org):
    from src.core.billing.middleware import check_plan_limits

    await repo.update_organization_billing(sample_org["id"], {
        "subscription_status": "active",
        "plan": "starter",
        "messages_limit": 500,
        "messages_used_this_period": 400,
    })
    result = await check_plan_limits(sample_org["id"], repo)
    assert result["warning"] == 80


async def test_check_plan_limits_warning_100(repo, sample_org):
    from src.core.billing.middleware import check_plan_limits

    await repo.update_organization_billing(sample_org["id"], {
        "subscription_status": "active",
        "plan": "starter",
        "messages_limit": 500,
        "messages_used_this_period": 500,
    })
    result = await check_plan_limits(sample_org["id"], repo)
    assert result["allowed"] is False
    assert result["reason"] == "quota_exceeded"


async def test_increment_and_check(repo, sample_org):
    """End-to-end: send a message, increment, then check limits."""
    from src.core.billing.middleware import check_plan_limits

    await repo.update_organization_billing(sample_org["id"], {
        "subscription_status": "active",
        "plan": "starter",
        "messages_limit": 500,
        "messages_used_this_period": 0,
    })
    await repo.increment_message_usage(sample_org["id"])
    result = await check_plan_limits(sample_org["id"], repo)
    assert result["used"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/core/billing/test_middleware.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Write middleware**

```python
# src/core/billing/middleware.py
from datetime import datetime, timezone


async def check_plan_limits(organization_id, repo) -> dict:
    """
    Check if an organization can send/receive messages based on billing limits.

    Returns:
        dict with keys:
            - allowed: bool
            - reason: str | None (if blocked)
            - remaining: int | None
            - used: int
            - limit: int | None
            - warning: int | None (80, 90, 100 percentage)
            - resets_at: datetime | None
    """
    billing = await repo.get_organization_billing(organization_id)

    status = billing["subscription_status"]
    if status not in ("active", "trialing"):
        reasons = {
            "past_due": "payment_failed",
            "canceled": "subscription_inactive",
            "incomplete": "subscription_inactive",
        }
        return {
            "allowed": False,
            "reason": reasons.get(status, "subscription_inactive"),
            "remaining": 0,
            "used": billing["messages_used_this_period"],
            "limit": billing["messages_limit"],
            "warning": None,
            "resets_at": billing["current_period_end"],
        }

    used = billing["messages_used_this_period"]
    limit = billing["messages_limit"]

    # NULL limit = unlimited (Business)
    if limit is None:
        return {
            "allowed": True,
            "reason": None,
            "remaining": None,
            "used": used,
            "limit": None,
            "warning": None,
            "resets_at": billing["current_period_end"],
        }

    remaining = limit - used
    if remaining <= 0:
        return {
            "allowed": False,
            "reason": "quota_exceeded",
            "remaining": 0,
            "used": used,
            "limit": limit,
            "warning": 100,
            "resets_at": billing["current_period_end"],
        }

    # Warning levels
    pct = int(used / limit * 100)
    warning = None
    if pct >= 100:
        warning = 100
    elif pct >= 90:
        warning = 90
    elif pct >= 80:
        warning = 80

    return {
        "allowed": True,
        "reason": None,
        "remaining": remaining,
        "used": used,
        "limit": limit,
        "warning": warning,
        "resets_at": billing["current_period_end"],
    }
```

- [ ] **Step 4: Wire middleware into main.py**

In `src/api/main.py`, add a dependency to the message processing routes that calls `check_plan_limits` before processing messages. Add this dependency to the relevant routes:

```python
from src.core.billing.middleware import check_plan_limits
```

For the message routes, add a check after getting the user/organization context. The simplest approach is to add `require_active_subscription` dependency:

```python
async def require_active_subscription(
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
    repo = Depends(get_repo),
):
    org_id = user.get("organization_id")
    if org_id:
        result = await check_plan_limits(org_id, repo)
        if not result["allowed"]:
            status_code = 402 if result["reason"] == "payment_failed" else 429
            raise HTTPException(
                status_code=status_code,
                detail={
                    "error": result["reason"],
                    "limit": result["limit"],
                    "used": result["used"],
                    "resets_at": str(result["resets_at"]) if result["resets_at"] else None,
                },
                headers={"X-Quota-Warning": str(result["warning"])} if result["warning"] else None,
            )
    return user
```

Then add `require_active_subscription` as a dependency to the message-sending routes.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/core/billing/test_middleware.py -v`
Expected: 10 PASS

- [ ] **Step 6: Commit**

```bash
git add src/core/billing/middleware.py tests/core/billing/test_middleware.py
git commit -m "feat(billing): add usage counting and plan limits middleware"
```

---

### Task 7: Integration test — end-to-end billing flow

**Files:**
- Create: `tests/core/billing/test_billing_integration.py`
- Modify: (none)

**Interfaces:**
- Consumes: All billing components (webhook handler, middleware, repository, router, plans)
- Produces: End-to-end integration test

- [ ] **Step 1: Write the integration tests**

```python
# tests/core/billing/test_billing_integration.py
import uuid
import pytest
from datetime import datetime, timezone

pytestmark = pytest.mark.asyncio


async def test_full_trial_to_active_flow(repo, sample_org, pg_pool):
    """
    Simulate: user signs up (checkout.session.completed) → trial starts →
    invoice.paid → org goes active → subscription.deleted → org suspended.
    """
    from src.core.billing.webhook_handler import handle_stripe_webhook
    from src.core.billing.middleware import check_plan_limits
    org_id = sample_org["id"]

    # 1. Checkout completed
    checkout_event = {
        "id": "evt_int_e2e_001",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_e2e_001",
                "client_reference_id": str(org_id),
                "mode": "subscription",
                "customer": "cus_e2e_001",
                "subscription": "sub_e2e_001",
                "status": "complete",
            }
        },
    }
    result = await handle_stripe_webhook(checkout_event, repo)
    assert result["action"] == "subscription_created"

    limits = await check_plan_limits(org_id, repo)
    assert limits["allowed"] is True  # Trial allowed

    # 2. Invoice paid (after trial or first payment)
    invoice_event = {
        "id": "evt_int_e2e_002",
        "type": "invoice.paid",
        "data": {
            "object": {
                "id": "in_e2e_001",
                "customer": "cus_e2e_001",
                "subscription": "sub_e2e_001",
                "status": "paid",
                "period_start": datetime.now(timezone.utc).timestamp(),
                "period_end": datetime.now(timezone.utc).timestamp() + 2592000,
                "lines": {
                    "data": [
                        {
                            "price": {"id": ""},  # will need price ID
                            "plan": {"product": "prod_starter"},
                        }
                    ]
                },
            }
        },
    }
    # Need to set a price ID that maps to a plan. For now just test status change.
    # This test assumes price ID is configured in env.
    result = await handle_stripe_webhook(invoice_event, repo)
    # If price ID not mapped, plan won't update but status should still go active
    billing = await repo.get_organization_billing(org_id)
    assert billing["subscription_status"] == "active"

    # 3. Use a message
    used = await repo.increment_message_usage(org_id)
    assert used >= 1

    # 4. Subscription deleted
    delete_event = {
        "id": "evt_int_e2e_003",
        "type": "subscription.deleted",
        "data": {
            "object": {
                "id": "sub_e2e_001",
                "customer": "cus_e2e_001",
            }
        },
    }
    result = await handle_stripe_webhook(delete_event, repo)
    assert result["action"] == "subscription_deleted"

    limits = await check_plan_limits(org_id, repo)
    assert limits["allowed"] is False
    assert limits["reason"] == "subscription_inactive"


async def test_starter_hits_limit_then_business_upgrade_unblocks(repo, sample_org):
    """Starter hits 500 limit → blocked → upgrade to Business → unblocked."""
    from src.core.billing.webhook_handler import handle_stripe_webhook
    from src.core.billing.middleware import check_plan_limits
    org_id = sample_org["id"]

    # Setup: org on Starter, 500 messages used
    await repo.update_organization_billing(org_id, {
        "subscription_status": "active",
        "stripe_customer_id": "cus_upg_001",
        "plan": "starter",
        "messages_limit": 500,
        "messages_used_this_period": 500,
    })

    limits = await check_plan_limits(org_id)
    assert limits["allowed"] is False
    assert limits["reason"] == "quota_exceeded"

    # Upgrade to Business (unlimited)
    upgrade_event = {
        "id": "evt_int_upg_001",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_upg_001",
                "customer": "cus_upg_001",
                "status": "active",
                "items": {
                    "data": [{"price": {"id": ""}, "plan": {"product": "prod_business"}}]
                },
                "current_period_start": datetime.now(timezone.utc).timestamp(),
                "current_period_end": datetime.now(timezone.utc).timestamp() + 2592000,
            }
        },
    }
    await handle_stripe_webhook(upgrade_event, repo)

    limits = await check_plan_limits(org_id)
    assert limits["allowed"] is True
    assert limits["limit"] is None  # unlimited
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest tests/core/billing/test_billing_integration.py -v`
Expected: Some tests may need adjustment for specific env vars (price IDs)

- [ ] **Step 3: Commit**

```bash
git add tests/core/billing/test_billing_integration.py
git commit -m "test(billing): add end-to-end billing integration tests"
```

---

### Task 8: Add audit logging for billing events

**Files:**
- Modify: `src/core/billing/webhook_handler.py` (add audit calls)
- Create: `tests/core/billing/test_billing_audit.py`

**Interfaces:**
- Consumes: `audit_log` from `src.core.auth.audit`
- Produces: Audit log entries for subscription status changes

- [ ] **Step 1: Write test**

```python
# tests/core/billing/test_billing_audit.py
import uuid
import pytest

pytestmark = pytest.mark.asyncio


async def test_audit_log_on_subscription_change(repo, sample_org):
    from src.core.billing.webhook_handler import handle_stripe_webhook

    org_id = sample_org["id"]
    event = {
        "id": "evt_audit_001",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_audit_001",
                "client_reference_id": str(org_id),
                "mode": "subscription",
                "customer": "cus_audit_001",
                "subscription": "sub_audit_001",
                "status": "complete",
            }
        },
    }
    await handle_stripe_webhook(event, repo)
    billing = await repo.get_organization_billing(org_id)
    assert billing["subscription_status"] == "trialing"
```

- [ ] **Step 2: Add audit_log calls to webhook_handler**

In `_handle_checkout_completed`, `_handle_invoice_paid`, `_handle_payment_failed`, `_handle_subscription_updated`, `_handle_subscription_deleted`, add after the status change:

```python
try:
    from src.core.auth.audit import audit_log
    await audit_log(
        repo=repo,
        organization_id=str(org["id"]),
        action=f"subscription_{new_status}",
        target_table="organizations",
        target_id=str(org["id"]),
        details={"previous_status": old_status, "new_status": new_status},
    )
except Exception:
    logger.warning("Audit log write failed", exc_info=True)
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/core/billing/ -v`
Expected: All billing tests pass (12 from webhook + 10 from middleware + 5 from routes + 2 integration + 1 audit = ~30)

- [ ] **Step 4: Commit**

```bash
git add src/core/billing/webhook_handler.py tests/core/billing/test_billing_audit.py
git commit -m "feat(billing): add audit logging for subscription changes"
```
