# ADR 004: Message idempotency strategy

## Context
Webhooks from Meta might be delivered multiple times for the same event, and network failures can trigger retries.

## Decision
All webhook processing and external side effects must be idempotent. We use an atomic `dedup_check` based on `wam_id` and status to prevent duplicate processing. Opt-out states and billing events must also gracefully handle duplicate triggers.
