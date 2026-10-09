# Dashboard modularization 02 — shared helpers

Base: `d45d0b3111675f54849456b5c63f50dfcfccd8e7` (PR #68 merge commit).
Its main CI run `37929779209` passed, including API/web amd64/arm64 and both verified GHCR manifests. No deployment was performed.

## Boundary and contracts

One classic IIFE, `web/dashboard-shared.js`, exposes a frozen `MelpisDashboardShared` namespace with five helpers: `escapeHtml`, `sanitize`, `toast`, `confirmDestructive`, `toDateKey`.
`app.js` binds local aliases once; existing call sites remain unchanged. Implementations were moved, not duplicated or replaced with wrappers. The module registers no startup listeners, timers, application state or API calls. Script order remains dialog-focus → router → shared → app → MFA. Docker COPY, local compose bind mount and the integration harness include the module.

Security review preserved the exact DOMPurify default policy, dynamic provider lookup and escaped-text fallback. Text-only toast/confirmation labels, default durations, action callback, modal fallback, Tab/Escape, focus restoration and per-invocation listener cleanup retain their behavior. Date keys still use local calendar fields, including the previous ISO-shaped string shortcut and invalid-date behavior. Feature-specific review/knowledge/Inbox formatting and message-link sanitization stay in their sections because their policies differ.

No CSS, visible HTML, routes, landing, backend, auth/session/CSRF/MFA/AAL2, tenant/role checks, polling, API semantics, locale bundles or pricing (29/69/149) changed. The only dashboard HTML change is the same-origin classic script reference. No new framework or bundler.

## Metrics and automated verification

- `app.js`: 9,332 → 9,208 lines (−124).
- One new runtime module; five implementations extracted; nine new tests.
- Frontend suite: 169/169 pass, including the unchanged Block1 contracts and auth/CSRF/MFA/BFCache/org/async-race suites.
- Seven helper tests cover inert startup, actual bundled DOMPurify/XSS/unsafe URLs, dynamic lookup/fallback, toast ARIA/text/timers/action, confirmation keyboard/focus/cleanup/fallback and date edge cases.
- Two synthetic interaction-fixture tests prove default baseline equivalence, logout denial and fail-closed unapproved mutations.
- Lint, i18n (3,148 keys), CSP, assets, links, SEO, images, FullCalendar CSS and npm audit including dev dependencies pass. Relevant Ruff and diff checks pass. No Python backend change warranted another local full Python run; the PR CI retains its full regression gate.

## Real browser / visual proof

Codex in-app Chromium, Windows; synthetic identities only. Browser QA and Security Review skills guided the isolated fixture and text/sanitizer boundary checks. Luna performed extraction and mechanical tests; Sol reviewed architecture/security and performed browser checks because Luna's browser session lacked the in-app browser.

The 12 committed Block1 JPEGs and their manifest remain unmodified. Captures use the same empty datasets, clock `2026-10-08T10:00:00.000Z`, Italian locale, dark theme, fonts and desktop 1440×900 / mobile 375×812 states. All 12 decoded RGB comparisons pass with zero changed pixels, no tolerance or baseline replacement. Initial transient counter/SVG rasterization differences were eliminated by observing settled UI and matching pointer/focus/navigation state, not by changing shipped rendering. Captures are ignored local artifacts under `scratch/dashboard-02-captures`.

Desktop and mobile smoke passed all nine canonical routes, menu/account sidebar, settings/security tabs, Back/Forward/reload, booking form invalid submission and Escape/focus return, shared document confirmation Tab/Escape/cancel/focus return, exactly one text-safe warning toast, synthetic simulator submission, logout and private reload redirect to login. No console errors/warnings; request log has only expected 200s and post-logout 401s. No document deletion, booking creation or provider call was executed.

Reproduce baseline mode: `node scripts/dashboard-baseline-server.cjs` on port 4190, following the Block1 README. Interactive smoke is explicitly opt-in via `DASHBOARD_QA_INTERACTIONS=1` and a separate `DASHBOARD_QA_PORT=4191`: it adds one synthetic document, permits synthetic logout and serves existing login assets. An HttpOnly test-only signed-out marker denies subsequent API calls. Unknown reads and all other unapproved mutations still fail closed. The default baseline fixture and deployed Docker image exclude this test-only mode; it is not evidence of real backend/provider authorization.

PR delivery only. Do not merge Block2, deploy, start Block3 or claim Meta/Google provider certification from these checks.
