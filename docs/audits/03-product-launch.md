# Product Launch Readiness Audit
**Phase:** 03
**Role:** CTO + Product Lead + SaaS Operations
**Date:** 2026-08-21

This audit evaluates the system's readiness for paying customers across Product, SaaS/Billing, GDPR compliance, Operations, and Marketing.

---

## 1. TECHNICAL LAUNCH BLOCKERS (P0)

### PROD-001: No Self-Serve Subscription Management (Cancellation)
*   **Area**: SAAS / UX
*   **Finding**: The backend API has endpoints for Stripe Checkout and Customer Portal (`/api/billing/create-checkout-session`, `/api/billing/customer-portal`), but the frontend dashboard (`app.js`, `index.html`) completely lacks UI for upgrading, downgrading, or canceling a subscription.
*   **Impact**: Users cannot cancel their trial or subscription without emailing support. In many jurisdictions (e.g., California, EU), it is illegal to offer online subscriptions without a frictionless, self-serve online cancellation mechanism.
*   **Action**: Wire up the "Manage Subscription" button to the Stripe Customer Portal endpoint.

### GDPR-001: Missing Right to Erasure & Data Retention Enforcement
*   **Area**: GDPR / COMPLIANCE
*   **Finding**: The system has no user-facing UI or API endpoint to delete an organization's account. Furthermore, while migration `004_gdpr.sql` adds `deleted_at` and `message_retention_days` for soft deletion, there is no cron job or worker that periodically executes hard-deletion of PII older than the retention period.
*   **Impact**: Blatant GDPR violation (Right to be Forgotten). Retaining PII indefinitely without an active legal basis is a massive compliance liability.
*   **Action**: 
    1. Implement a `/api/organization/delete` endpoint and UI button that executes `repo.delete_organization`.
    2. Add a daily cron job that permanently deletes messages/contacts where `deleted_at < NOW() - 30 days` or `created_at < NOW() - message_retention_days`.

---

## 2. BUSINESS LAUNCH BLOCKERS (P1)

### MKT-001: Severe Branding Inconsistency (Sempre vs Melpis)
*   **Area**: MARKETING
*   **Finding**: The product is called "Melpis" in the core pricing strategy document (`melpis-piano-pricing-definitivo.md`), but the landing page (`sempre-presentazione.md`) extensively refers to the product as "Sempre". 
*   **Impact**: Destroys trust during the conversion funnel. Customers will be confused about what they are buying.
*   **Action**: Unify the brand name across all copy, legal documents, and UI elements before launch.

### BILL-001: Pricing Limits Mismatch (Code vs Copy)
*   **Area**: SAAS / BILLING
*   **Finding**: The pricing page copy promises: 
    *   Essential: 300 messages
    *   Growth: 1,200 messages
    *   Scale: 5,000 messages
    However, `src/core/billing/plans.py` hardcodes:
    *   Starter: 500 messages
    *   Pro: 2,000 messages
    *   Business: Unlimited (`None`)
*   **Impact**: Customers on the highest tier will consume unlimited tokens instead of being capped/flagged at 5,000, creating an infinite cost vulnerability.
*   **Action**: Align `plans.py` strictly with the finalized marketing strategy.

### GDPR-002: Missing Right to Portability (Data Export)
*   **Area**: GDPR / COMPLIANCE
*   **Finding**: The API exposes `/api/report/csv` to export *completed bookings*. There is no way for a tenant to export their AI conversation history or contact list.
*   **Impact**: Fails GDPR data portability requirements.
*   **Action**: Add an endpoint to dump conversations and contacts to CSV/JSON.

---

## 3. POST-LAUNCH IMPROVEMENTS (P2/P3)

### OPS-001: Dead-Letter Queue Visibility (P2)
*   **Area**: OPERATIONS
*   **Finding**: The `run_supervisor.py` handles retries, but if a message permanently fails, it is orphaned in the DB. The backoffice/dashboard has no "Failed Messages" view for tenants to manually inspect why a message wasn't answered.
*   **Action**: Add a "System Errors / Unhandled Messages" tab to the dashboard.

### PROD-002: Trial Expiry Friction (P2)
*   **Area**: PRODUCT / UX
*   **Finding**: When a trial expires, the DB puts the organization in a read-only state. However, the UI does not proactively warn the user (e.g., "3 days left in trial").
*   **Action**: Implement a persistent UI banner calculating days/messages remaining in the trial to drive conversion urgency.

### MKT-002: Competitor Acknowledgment (P3)
*   **Area**: MARKETING
*   **Finding**: The pricing document mentions a competitor ("Polsia.com") but notes the URL/data was unverified. 
*   **Action**: Finalize competitor research to ensure the pricing anchors (49/99/199) are actually competitive in the local market.

---

## Conclusion

**Status:** ❌ **NOT READY FOR LAUNCH**

The core AI engine is sophisticated, but the "SaaS Wrapper" around it is incomplete. The product cannot legally or safely accept paying customers until the P0 (Cancellation & Data Deletion) and P1 (Pricing mismatch & Branding) issues are resolved.
