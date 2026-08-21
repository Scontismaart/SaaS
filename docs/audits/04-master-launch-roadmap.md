# Master Launch Roadmap
**Phase:** 04
**Role:** CTO
**Date:** 2026-08-21

## 1. Executive Summary

**Product**: "Melpis" is an AI-powered conversational agent and booking assistant for local businesses via WhatsApp (Instagram planned as a future feature).
**Maturity**: The backend architecture (FastAPI, asyncpg, pgvector) and the testing suite are remarkably robust. Core infrastructure for idempotency, webhooks, and billing exists. 
**Launch Status**: **NOT READY**. Despite a strong foundation, critical flaws in worker transaction boundaries, side-effect idempotency, SaaS UX (no cancellation), and a catastrophic mismatch in billing limits prevent a safe launch.

---

## 2. Production Readiness Score (0-10)

| Category | Score | Notes |
| :--- | :--- | :--- |
| **Database** | 9/10 | Excellent use of `asyncpg`, `pgvector`, and migrations. |
| **Testing** | 8/10 | Comprehensive test suite including RLS, retention, and guardrails. |
| **AI / Guardrails** | 8/10 | Strong deterministic guardrail strategy; MFA implemented for sensitive endpoints. |
| **Observability** | 8/10 | Audit logs and trace IDs are present. |
| **Architecture** | 8/10 | Clean webhook decoupling and async worker model (`SKIP LOCKED` verified). |
| **Multi-tenancy** | 7/10 | Application-level via `service_role`. Relies heavily on developer discipline (High risk). |
| **Workers** | 7/10 | Supervisor and retention scheduler exist and are tested. |
| **Infrastructure** | 7/10 | Standard Docker/Compose setup. |
| **Security** | 6/10 | Flawed side-effect authorization. |
| **GDPR/Privacy** | 6/10 | Automated retention exists, but self-serve erasure/export is missing. |
| **RAG** | 6/10 | Susceptible to cache poisoning and prompt injection. |
| **Billing** | 6/10 | Stripe integrated, but limits don't match the business model. |
| **UX / Product** | 5/10 | Missing critical SaaS flows (upgrade, downgrade, cancellation). |
| **Messaging** | 5/10 | Critical race condition drops messages on API failure. |
| **Disaster Recovery** | 5/10 | No automated backup strategy documented in the repository. |
| **Marketing** | 5/10 | Severe branding inconsistency across docs. |

---

## 3. Launch Verdict

**NOT READY.**

We cannot safely sell this product today. If we launch now:
1. **Financial Ruin**: The Business plan has unlimited AI messages hardcoded in `plans.py`, contrasting with the 5,000 limit in the marketing copy. A single malicious customer could bankrupt the company via LLM costs.
2. **Data Corruption**: A worker crash during booking creation will result in duplicate bookings for restaurants because `create_booking` lacks idempotency.
3. **Dropped Customer Messages**: Network errors when contacting Meta's API will cause messages to be marked as "handled" in our DB but never actually sent, silently breaking the service.
4. **Legal Liability**: Selling subscriptions without a cancellation button in the UI is illegal. Also missing Terms of Service and Privacy Policies.

---

## 4. P0 — Launch Blockers (Must fix immediately)

### P0-1: Broken Booking Idempotency (SEC-001)
*   **Problem**: `create_booking` uses a random `uuid4`. A worker crash leaves the message in the queue but the booking in the DB, causing duplicates on retry.
*   **Fix**: Pass `msg["id"]` to `create_booking` and enforce a UNIQUE constraint on `(organization_id, id_conversazione, data, ora)`.
*   **Affected Files**: `src/core/bookings/service.py`, `src/core/db/repository.py`
*   **Acceptance Criteria**: Retrying a successful booking request must not create a duplicate row.

### P0-2: Premature Message State Update (SEC-002)
*   **Problem**: Worker marks message as `ai_handled` *before* sending it to Meta. If Meta API fails, the message is permanently lost.
*   **Fix**: Call `_send_ai_reply` first. Only call `try_mark_replied` upon a successful API response. Manage outbound idempotency via local state or a robust outbox pattern, as Meta's Cloud API does not natively support strict header-based idempotency for standard sends.
*   **Affected Files**: `src/whatsapp/inbound_processor.py`
*   **Acceptance Criteria**: Simulating a 500 error from Meta leaves the message in `received_pending_ai` state for the retry worker.

### P0-3: Infinite Cost Vulnerability (BILL-001)
*   **Problem**: `plans.py` sets Business tier limits to `None`.
*   **Fix**: Update `plans.py` to strictly match the pricing doc (Starter: 300, Pro: 1200, Business: 5000). Implement overage handling or a hard cap.
*   **Affected Files**: `src/core/billing/plans.py`
*   **Acceptance Criteria**: Business tier throws `MessageUsageExceeded` at 5,000 messages.

### P0-4: No Cancellation UI (PROD-001)
*   **Problem**: Customers cannot cancel subscriptions.
*   **Fix**: Add a "Manage Subscription" button in the frontend calling the Stripe Customer Portal endpoint.
*   **Affected Files**: `web/app.js`, `web/index.html`
*   **Acceptance Criteria**: User can navigate to Stripe Portal and cancel their plan, triggering the webhook that sets the org to read-only.

---

## 5. P1 — Public Launch Requirements (Must fix before GA)

### P1-1: Brand Unification (MKT-001)
*   **Problem**: Product is called both "Melpis" and "Sempre".
*   **Fix**: Standardize on **"Melpis"**. Rename all marketing/pricing docs and landing page copy.

### P1-2: GDPR Self-Serve Erasure & Export (GDPR-001, GDPR-002)
*   **Problem**: No UI for account deletion or data export.
*   **Fix**: Add "Delete Account" and "Export Data" buttons to the settings view. Connect to `repo.delete_organization`.

### P1-3: FAQ Cache Poisoning (SEC-003)
*   **Problem**: AI hallucinations are dynamically cached in `faq_cache` and served forever.
*   **Fix**: Disable dynamic FAQ caching for generated answers, or require an explicit HITL approval.

### P1-4: RAG Prompt Injection (SEC-004)
*   **Problem**: Untrusted document chunks can override AI instructions.
*   **Fix**: Wrap the RAG context in strict XML tags (`<DocumentContext>`) in the system prompt.

### P1-5: service_role Data Leak Risk (SEC-005)
*   **Problem**: Multi-tenancy relies heavily on developer discipline (`WHERE organization_id`). A single mistake leaks data.
*   **Fix**: Implement a linter (e.g., Flake8/Ruff plugin) or DB wrapper that enforces `organization_id` statically on all repository queries.

### P1-6: Legal Documents & Compliance
*   **Problem**: Missing core legal safeguards.
*   **Fix**: Publish Terms of Service, Privacy Policy, and a Data Processing Agreement (DPA) for B2B customers.

---

## 6. P2 — Post-Launch Improvements

*   **P2-1**: Dead-Letter Queue UI in the dashboard for tenants to view failed messages.
*   **P2-2**: Trial expiry UI banner countdown.
*   **P2-3**: Competitor validation for pricing anchors.
*   **P2-4**: Instagram channel integration — future roadmap.

---

## 7. Master Roadmap

**Phase 1: Integrity & Safety (Week 1)**
1. `P0-1`: Refactor `create_booking` idempotency.
2. `P0-2`: Invert the state-update/send logic in `InboundProcessor` + outbox pattern.
*Requires mandatory code review.*

**Phase 2: SaaS & Billing (Week 1-2)**
3. `P0-3`: Align `plans.py` limits with product strategy.
4. `P0-4`: Wire Stripe Customer Portal in the frontend.

**Phase 3: Legal & Brand (Week 2)**
5. `P1-1`: Unify brand name to "Melpis".
6. `P1-2`: Implement GDPR export and delete endpoints.
7. `P1-6`: Publish Terms, Privacy, and DPA.

**Phase 4: AI & Security Hardening (Week 3)**
8. `P1-3`: Refactor `faq_cache` to require approval.
9. `P1-4`: Add XML boundaries to RAG prompts.
10. `P1-5`: Add `service_role` linter.

---

## 8. Critical Test Plan

Before we deploy to production, these specific automated tests must pass:
1. `test_booking_idempotency_on_crash`: Simulates a worker crash after `INSERT INTO bookings` and verifies the retry does not duplicate.
2. `test_message_retained_on_api_failure`: Mocks Meta API returning 503 and verifies the DB state remains `received_pending_ai`.
3. `test_pricing_enforcement_business_tier`: Mocks a 5,001st message on the Business plan and verifies `ai_handled` is skipped due to rate limits.
4. `test_cancellation_downgrades_to_readonly`: Triggers Stripe `customer.subscription.deleted` and verifies the tenant can no longer send AI messages.
5. **Load Testing**: Stress test `SKIP LOCKED` worker concurrency under burst traffic to ensure no race conditions trigger before Beta.

---

## 9. Production Operations

Before routing real WhatsApp traffic:
*   **Monitoring**: Datadog/Sentry APM enabled to catch `InboundProcessor` crashes.
*   **Alerts**: PagerDuty alerts for >5% failure rate on `/webhooks/whatsapp` or Meta API timeouts.
*   **Backups**: PostgreSQL continuous archiving (WAL-G / pgBackRest) configured with point-in-time recovery tested.
*   **Rollback**: Database migrations strictly forward-compatible to allow instant traffic rollback to N-1 container images.

---

## 10. Commercial Launch Stages

*   **0 → 10 Customers (Private Beta)**: 
    *   Requires Phase 1 & 2 complete. Load tests on workers passed.
    *   Manual onboarding. Close monitoring of LLM costs per tenant.
*   **10 → 100 Customers (Public Launch)**: 
    *   Requires Phase 3 & 4 complete.
    *   Self-serve Stripe checkout, GDPR compliance verified. 
    *   **Requires Canary/Staged rollout plan** for new releases to limit blast radius.
*   **100 → 1000 Customers (Scale)**: 
    *   Requires Read Replicas.
    *   Requires automated DLQ retry dashboard for customers.
    *   Switch to HNSW index for `pgvector` as data volume grows.

---

## 11. Final CTO Decision

1. **Can we safely sell today?** NO.
2. **Can we run a private beta?** Yes, but ONLY after Phase 1 and Phase 2 (P0 issues) are completed, plus load tests on workers.
3. **What are the 5 biggest blockers?** Booking idempotency, API failure state sync, Billing limits infinite vulnerability, Missing Cancellation UX, Brand mismatch.
4. **What is the shortest safe path to launch?** Fix the 4 P0s. Launch the private beta. Fix the P1s during the beta.
5. **What must never be postponed?** Fixing the transaction/state boundary for WhatsApp messages. If we drop messages, customers will churn instantly.
6. **What can safely wait?** DLQ UI, trial countdown banners, Instagram integration.
7. **Estimated engineering effort:** ~3 weeks for 1 Senior Engineer + mandatory code reviews on transactional changes (P0-1/P0-2).
