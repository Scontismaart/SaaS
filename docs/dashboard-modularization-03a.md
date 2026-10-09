# Dashboard modularization 03A — Overview and Reviews

Base: `6b49bfecb1caa7d6ab4f898f19a61c770142a67f`, merge commit of PR #69.
Main CI run `37953269552` passed, including 169 frontend tests and the
API/web amd64/arm64 publications and both immutable multi-architecture manifests.
No deployment was performed.

## Boundaries

- `web/dashboard-overview.js`: onboarding checklist, priority/activity rendering,
  KPI formatting/sparklines/trends and the existing five-second polling lifecycle.
- `web/dashboard-reviews.js`: review list, filters, detail/draft, analysis and
  approval handlers, sentiment/trends and view-local state/listeners.
- `web/app.js`: creates both factories once, supplies explicit dependencies and
  session/organization/route snapshots, coordinates entry/exit and logout.
  Shared helpers still come from `dashboard-shared.js` and the existing app helpers.

These are two flat, same-origin classic scripts loaded after the shared helpers
and before `app.js`; no framework, dynamic loader, module bundler or new CSP grant.
The web image and local compose mounts include both files. Public module methods
are limited to lifecycle and existing cross-view refresh/navigation operations.

Scope/transition epochs and request sequences reject stale responses after route,
organization or session changes. Entry preserves same-organization view state;
scope changes and logout clear sensitive view data. Exit stops polling and tracked
timers. Reviews mutation locks survive route exits until the request settles;
listener attachment occurs only during factory creation. Auth-denied list reads
never fall back to another endpoint and clear the open draft. Ordinary transient
list errors preserve edited drafts and prior metrics, while showing history retry.
Authorization, CSRF, session refresh, MFA and tenant checks remain server-owned
and use the original `apiFetch` transport.

## Metrics

`app.js`: 9,208 → 8,139 lines (net reduction 1,069).
21 existing function implementations transferred, without copies in `app.js`.
Overview: 574 lines; Reviews: 806 lines, including scoped lifecycle safeguards.
25 tests added: 7 Overview, 16 Reviews, 2 synthetic view-fixture contracts.
Existing fragment-based auth/router fixtures declare the new coordinator
dependencies; pagehide/logout assertions additionally verify module cleanup.

## Verification

- Targeted view, race, contract, i18n and auth/router suites passed. A single local
  full frontend run identified outdated isolated-fragment fixtures; all 44 tests
  in the affected files passed after fixing those fixture dependencies. CI runs
  the complete final frontend suite again as the delivery gate.
- ESLint, i18n schema/key verification, CSP, referenced assets, links, images,
  SEO and FullCalendar static CSS checks passed; npm audit found zero vulnerabilities.
  The existing hardcoded-text advisory is unchanged and non-blocking.
- Final scoped architecture/security review: P0/P1/P2 = 0/0/0.
- No backend/Python change: no repeated local full Python run. GitHub CI retains
  full Python, Ruff, py_compile, tenant guard and image-build gates.

## Real-browser evidence

Codex in-app Chromium on Windows, desktop 1440×900 and mobile 375×812,
Italian/dark, local deterministic fonts and clock `2026-10-08T10:00:00.000Z`.
All 12 immutable Block 1 captures matched decoded RGB exactly (zero changed
pixels); no baseline image, manifest or tolerance was changed. Pointer/focus and
viewport repaint were normalized when Chromium temporarily rasterized SVGs
differently. The comparison still required exact identity.

Both viewports exercised all nine canonical routes, the correct visible panel,
sidebar/menu, Overview → review detail, Back/Forward, reload, organization A → B,
synthetic records/filters/draft and logout. Mobile had no horizontal overflow.
Loading, empty, API errors and denied reads were observed in the real browser.
Logout followed by Back and reload returned to login with private UI hidden.
No console warnings/errors were captured in the final QA tab.

Only the opt-in loopback fixture (`DASHBOARD_QA_INTERACTIONS=1` and
`DASHBOARD_QA_VIEW_STATES=1`) enables synthetic state scenarios. Baseline/default
responses remain unchanged. Unknown reads/writes and unknown organizations fail
closed; no database, model or provider call is made. Explicit `/__qa/start` starts
a new synthetic journey; normal private reload does not clear the logout marker.
Screenshots under ignored `scratch/` contain synthetic `.invalid` identity only.

Google Reviews credential-saved versus operational state remains distinct.
Google Business Profile quota zero is still an external blocker; this QA does
not certify Google/Meta provider E2E. No OAuth backend or quota setting changed.

No CSS, visible HTML, landing, API endpoint, pricing (29/69/149), framework or
feature change. Daily Report was not reintroduced. Legacy internal report code
and other view logic remain unextracted. No Block 3B or deployment is authorized.

## Skills

Frontend Patterns guided explicit dependencies and view-local lifecycle; Security
Review required stale-scope rejection and fail-closed denial coverage; Browser QA
required real desktop/mobile evidence; GitHub Ops governs green-CI delivery with
the Block 3A pull request left open.
