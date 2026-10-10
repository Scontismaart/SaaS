# Dashboard modularization 03B

Base: merge commit `4f996e0e4ec6b53551d0a564c0d3f2a5e32e8666` (PR #70).
Main CI run `37966491289` passed, including API/web amd64/arm64 publication and both verified GHCR manifests. Publication is not deployment.

## Boundaries and contracts

- `dashboard-knowledge.js`: FAQ/document/web/business-data loading, forms, uploads, source actions and document queries. Explicit dependencies: the existing `apiFetch`, shared escaping/sanitization, translation/locale, confirmation and live shell context. Public API: `onEnter`, `onExit`, `invalidate`, `aggiornaConoscenzaCompleta`.
- `dashboard-team.js`: members, invitations, organization options and permitted member actions. Explicit live session/context plus existing API/error/MFA/translation/toast/confirmation helpers. Public API: lifecycle and `caricaTeam`. Invitation-link acceptance and the organization-switch/reload handler remain in the shell.
- `dashboard-ai-simulator.js`: chat bubbles, typing, form and suggestion submission, conversation identity and the six original ordered refresh callbacks. Public API: lifecycle only. AI text stays `textContent`; the application server remains the authorization/guardrail authority.

All three are classic-script frozen factories, loaded exactly once before `app.js`. Production image COPY and development read-only mounts include them. No new framework, dependency, backend, migration, provider configuration, CSS, visible HTML, pricing or landing changes.

The shell owns routing, session/refresh/CSRF, MFA/AAL2, revocation/JIT and organization selection. Each view rejects asynchronous work after route/session/organization changes. Reads are single-flight where needed; mutation locks survive route exit until the actual request settles. Owned confirmations close on exit. Private records/drafts/history clear on organization change or logout; same-organization return retains permitted local state. Destructive Escape cancellation restores focus only in the current view, without stealing focus after navigation.

Security review covered DOM sinks, URL schemes, stale response/row actions, Staff/manager restrictions, denied responses, secrets and unchanged server authorization. Team identifiers/attributes are escaped and path identifiers encoded; unsafe Knowledge source schemes are inert text. No secrets or raw request/error payloads are logged. Existing authentication/MFA/router/shared helpers remain unchanged.

## Measured extraction

- `app.js`: 8139 -> 6718 lines; **1421 lines removed**.
- Three new view modules; **20 existing named functions transferred** (11 Knowledge, 5 Team, 4 Simulator), plus their original event handlers. No implementations left duplicated in the shell.
- **42 new tests**: 15 Knowledge, 13 Team, 11 Simulator and 3 synthetic-fixture tests. Total frontend inventory: 236 tests.
- Preserved existing assertions and adapted only source locations/script fixtures. The local full run discovered an old keyboard test still looking for its moved function in `app.js`; the corrected location passes all four focus/keyboard tests. The final complete frontend and Python results are required from the exact PR-head CI, not inferred from targeted runs.

## Real browser QA (2026-10-10)

Real in-app Chromium, synthetic loopback API only. Desktop 1440x900; mobile 375x812; Italian/dark theme, local fonts and fixed clock `2026-10-08T10:00:00.000Z`. No provider, paid model, real account, database or credentials used.

- All nine canonical routes smoke-tested on both viewports; sidebar navigation, Back/Forward and hard reload exercised.
- Knowledge: populated/empty/error/loading/403; FAQ form, cancellation/focus, file upload, text upload, web import, business-data save and document query. Rejected uploads, duplicate requests, detached actions and logout races covered in automated tests.
- Team: populated/empty/error/loading/403; synthetic invite, role change, destructive dialog/Escape, owner versus Staff visibility, MFA-required rejection, and actual organization-selector A/B reload with tenant-specific rows.
- Simulator: normal and hostile canned output (zero executable nodes), API error and delayed HTTP 504; pending controls disabled, typing removed and controls restored on completion. Same-org history on return, epoch races and persistent request locks covered by regression tests.
- Logout during a delayed simulator request, cross-tab logout, Back and reload show login with no private chat/team content; mobile logout verified separately. Captured error/warning console logs are empty.

## Immutable visual comparison

All 12 Block 1 baseline JPEGs compared as decoded RGB: **12/12 identical, zero changed pixels**, unchanged dimensions. Baselines were not edited. Transient SVG rasterization was resolved by real UI repaint/re-observation at the original viewport; no tolerance, image editing or baseline update used.

Captures stay ignored under `scratch/dashboard-03b-captures/` (synthetic content only). Capture/compare procedure remains in `tests/frontend/baselines/dashboard-01/README.md`. The opt-in view-state server supports only fixed synthetic records/actions and logs only method/path/status; default baseline responses remain unchanged.

## Delivery gates and scope

ESLint, i18n, CSP, assets, links, dependency audit, diff check, staged-diff secret scan and scoped security review must pass. CI must pass the complete frontend/Python validation and all four PR image builds on the exact head. No local full Python rerun for this frontend-only change.

Block 3B PR stays open. No merge, deploy, next block or real-provider certification. Meta E2E, Google quota and operational prerequisites remain separate, unresolved provider gates.
