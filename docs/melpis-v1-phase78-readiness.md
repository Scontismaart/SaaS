# Melpis V1 — Phase 7/8 integration checkpoint

Status: **IN PROGRESS — no merge or deploy authorized/executed**.

## Pricing and product scope

Official monthly prices: Essenziale €29, Crescita €69, Scala €149.
Configured yearly amounts (€288/€708/€1,548) and existing plan limits are
preserved; yearly commercial approval remains pending. No uniform percentage
discount or free-month claim is certified. No Stripe Live resource was created.
Older billing design/plan documents are marked superseded, retaining history.

V1 retains WhatsApp, safe AI, Inbox/human takeover, native bookings, Calendar,
AI configuration, knowledge, team, security and existing billing. Reviews and
Instagram require actual provider availability. Advanced multi-location,
additional PMS/booking providers, Messenger, chat widget, advanced analytics,
white-label and PWA/push remain deferred; existing code is not deleted.

## Integration and local QA

PR #66 and #60 were verified open with successful CI at their original heads.
Separate branch `codex/melpis-v1-phase7-8` combines both, without conflicts.
Migration 059 and durable revocation/JIT, OAuth binding, MFA, release guards
and the web entrypoint are retained. Initial combined security tests: **200/200**.

Migration 059 was applied only to the verified `phase6-auth-runtime` local
Supabase database. A new disposable QA identity was created afterwards, and
the normal server-side durable JIT repository provisioned its Owner membership.
Real local browser login completed MFA/AAL2. Owner settings returned 200;
Owner-only configuration reached input validation (422 with empty body),
whereas a separate disposable Staff fixture was denied with 403. No existing
user was elevated, and no lifecycle history was reset.

WhatsApp test delivery now uses the existing durable send path, action-scoped
UUID idempotency, recipient allowlist, same-tenant/channel 24-hour inbound
window and opt-out gates. Provider details, transport exceptions, validation
inputs and undecryptable credentials cannot be reflected to the browser.
Only a genuine Meta message ID confirms acceptance; ambiguous results remain
pending and retries retain the same intent key. Webhook subscription requires
an actual success response, not just HTTP 200.

Local Meta verification token is prepared privately; sandbox mode is explicit
and background jobs remain off. No recipient is authorized yet. The Meta app
signature secret and a provider-reachable callback are not yet available.
Localhost alone cannot certify live Meta webhook receipt. No public exposure,
client message or live Meta send was performed.

## Provider evidence preserved

Real Calendar certification from `phase7-integrations-qa.md` is preserved and
was not repeated. Airtable PostgreSQL certification is preserved; external
Airtable/PMS sandboxes remain unavailable unless supplied separately.

Reviews OAuth succeeded in project `melpis-staging`, with `business.manage`.
After Account Management API activation, its genuine `accounts.list` request
returned 429 `RATE_LIMIT_EXCEEDED`, `quota_limit_value=0`. Account/location/review
access is **EXTERNAL BLOCKED — GOOGLE QUOTA**, not a real Reviews PASS.
The UI now distinguishes OAuth consent from an operational integration; a
completed resource sync is required before claiming it active.

Google states that zero quota means API access has not been granted. Request
Business Profile API access for this exact project through the official
[prerequisites/access process](https://developers.google.com/my-business/content/prereqs);
do not request an ordinary quota increase as a workaround for unapproved access.
See [usage limits](https://developers.google.com/my-business/content/limits).
Account/location IDs and review evidence remain pending Google approval.

## Remaining gates

Meta credentials have now been entered by the QA Owner through the local form.
Saved account status returned HTTP 200, connected=true. A read-only Meta probe
through the authenticated application returned HTTP 200, success=true; no
message was sent. The QA Owner subsequently saved the Meta App Secret through
a temporary loopback-only form outside Git and logs. That listener is closed.
Effective local runtime now has both App Secret and verify token configured;
sandbox-only remains true and background jobs remain disabled. Local HTTP probes
passed: correct challenge 200, incorrect challenge 403, missing/invalid signature
403, correctly signed empty payload 200, stale timestamp 403. These were synthetic
local probes, not incoming Meta events. Meta's read-only subscribed-apps request
returned 200 and confirmed the expected app subscription. No authorized
test-recipient allowlist is configured. Localhost is not a
publicly reachable Meta callback. Real webhook/inbound/outbound/delivery remain
blocked, not certified. No public exposure or production infrastructure started.

Browser QA found that the connected card incorrectly claimed ready-to-respond
and real-time reception from saved credentials alone. The card now distinguishes
credentials from webhook configuration and still requires real-message evidence
even when webhook configuration exists. Three new regression tests plus the two
existing retry-key tests passed (5/5) in both worktrees; frontend lint and diff
checks passed. The refreshed real browser shows incomplete webhook configuration.
Real Meta QA now requires a reachable callback and an explicitly authorized QA
recipient. Public exposure/infrastructure was not authorized by this mission,
so this is an external gate rather than a certified WhatsApp E2E result.

Final frontend checkpoint: **143/143 passed**, including conservative readiness,
auth/router/MFA/BFCache and retry keys. Frontend lint, i18n build/consistency, CSP,
assets/links/SEO/images/hardcoded checks and npm audit passed. A stale Reviews
source assertion was updated to require actual operational status instead of
OAuth alone; regenerated FullCalendar artifacts fixed Windows-line-ending drift.
Ruff CI, compilation, tenant guard, release-bootstrap static tests and diff checks
passed. Gitleaks reviewed 308 commits with no leaks, then checked the six new
integration commits with no leaks. The Python dependency gate audited 201 packages
and passed against the existing documented exception policy; it is not a claim of
zero advisories. At this checkpoint the single final isolated full Python suite
is still in progress; its completed result must be recorded in the integration PR.

One final combined full Python regression, complete frontend/static/dependency/
secret gates and CI on the exact integrated code remain required after all fixes
and available provider QA. Earlier green runs are not proof for new commits.
No final readiness or merge approval is claimed at this checkpoint.

Post-fix targeted verification: **60/60 Python tests passed** for pricing,
credential boundaries, actual PostgreSQL window scope and Reviews status.
Updated combined code: **149/149 passed**, including six real PostgreSQL/JWT
cases denying disabled or membership-revoked principals on Meta configuration,
Calendar OAuth and Reviews OAuth. Targeted frontend **8/8 passed**, Ruff CI,
frontend lint, i18n consistency, referenced assets and diff checks passed.
A frontend source assertion initially failed because it counted an unrelated
booking key; scoped assertion was corrected and its tests passed. These runs
are targeted checkpoints, not the final full suites or CI for new commits.
Phase 7 local checkpoint commit: `5c898f2`; remote PRs are not yet updated.

Next operational phase, not started: server, domain, DNS, public HTTPS, SMTP
and sender/SPF/DKIM/DMARC, encrypted off-host backup and restore drill, production
monitoring, reviewed production migrations/secrets, Stripe Live and legal/ops.
