# Dashboard modularization 03C — Bookings

Base: PR #71 merge commit `0074b2c21c67f12b2a8e9e372916116586d7db4b`.
Main CI `38036977948` passed: 236 frontend tests, 2599 Python passed / 33 existing skips / zero failures or errors, Ruff, compile, tenant guard, API/web amd64+arm64 publication and both verified GHCR manifests. Publication is not deployment. Migration workflow is path-filtered; this frontend change contains no migrations.

## Boundary and contracts

`web/dashboard-bookings.js` is a classic-script frozen factory with explicit API, shared escaping/date/i18n, live context/session, vertical, confirmation, notification and CSV dependencies. Public API: `onEnter`, `onExit`, `invalidate`, `load`, `aggiornaPrenotazioni`, `aggiornaSemaforo`, `apriBookingModal`. The shell keeps auth/session/refresh/CSRF, routing, organization switching, MFA, notifications and the shared CSV implementation. Overview's existing availability dialog and Simulator's existing refresh callbacks remain wired.

Transferred 21 existing named functions, original calendar/form/detail/capacity/filter/export handlers and local state. `app.js`: 6718 to 5957 physical lines, 761 removed. One new production module; no duplicate booking implementations left in the shell. Production COPY and read-only development mount include the script exactly once before `app.js`. Shared callback aliases are explicitly assigned before Overview and Simulator construction.

No backend, schema, provider, auth helper, router, shared helper, CSS, visible HTML, translation, dependency, landing or pricing changes. Prices remain 29/69/149; no Report route restored. Endpoint/method/payload/date and fifteen-minute slot contracts remain unchanged. No invented idempotency header.

## Lifecycle and security

Live user/session/selected-org/route/epoch and role checks surround asynchronous work, including JSON and destructive confirmation. Selected date and form/detail generations protect current interactions. Internal read/load reuse is single-flight; explicit refresh can supersede an older read. Mutation locks persist across exit until the request settles. Exit stops polling and closes only owned dialogs/confirmation. Scope change/logout clears private rows, events, settings, details and drafts; permission denial clears sensitive records. CSV cannot download a blob after invalidation.

Backend remains the sole permission authority. Staff forged events cannot issue reserved writes. Plain text/attribute values are escaped; path IDs encoded; availability class tokens validated. API requests still use shell CSRF/refresh handling. No credentials or raw errors are logged. Scoped security review found no remaining P0/P1/P2 Block3C issues. Real-provider certification was not repeated or inferred from fixtures.

## Tests and real-browser evidence

43 added tests: 41 behavioral Bookings tests and two synthetic-fixture tests. Existing auth, lifecycle, router, i18n, focus and async-race assertions were preserved and migrated to the production factory/script location. A test-only observation seam exposes private functions only inside the race harness, never in shipped code.

Targeted tests cover exact reads/writes, rendering, form validation, create/edit/status/capacity, duplicate/pending locks, errors/timeouts/403, role revocation, late JSON, scope changes/logout, cleanup, focus/Escape, inert hostile text/IDs, local dates/DST/midnight, polling and CSV. One local full frontend run executed 277 tests: 276 passed and one new test incorrectly dereferenced a nonexistent toast container when no toast was emitted. Only that test assertion was corrected; the complete Bookings file then passed 39/39. Final wiring review found unassigned shared callback aliases: two new real-shell tests reproduced Overview setup failure and Simulator's spurious technical-error bubble after a successful reply. Assigning the three aliases fixes both without changing their implementations. Final inventory: 279 tests. No second local full run or local full Python run; complete frontend/Python acceptance is required from exact-head CI.

Real Chromium: desktop 1440x900 and mobile 375x812; nine canonical routes, sidebar, history, reload, calendar views/date navigation, form validity/synthetic submit, confirmation/Escape/focus, owner/Staff/denied/error/loading/timeout and actual synthetic A/B organization switching. Logout during a pending booking write, Back and hard reload left login visible with no private content. Captured warning/error console logs were empty. Synthetic loopback API only; no database, paid model, external provider or real user mutation.

All 12 immutable Block 1 images compared as decoded RGB: zero changed pixels, identical dimensions. Pointer/focus and transient rasterization were stabilized through real UI observation/repaint at the original viewport; no tolerance, image editing or baseline replacement. Additional Bookings captures cover empty/populated/calendar/form/confirmation/error/mobile. Screenshots remain ignored under `scratch/dashboard-03c-captures/` and contain synthetic data only.

ESLint, CSP, i18n (3148 keys), FullCalendar stylesheet, assets, links, dependency audit, diff check and staged secret scan are delivery gates. Graphify update completed; optional SQL parser warnings are non-blocking for this frontend-only extraction.

Leave Block 3C PR open. No merge, deploy, Block 3D or provider changes.

## Hourly capacity follow-up

Real browser reproduction found an empty hourly grid when settings were null or omitted `fasce_orarie`; Save could then send an empty map and trigger the backend default. The editor now normalizes successful null settings, falls back to all 24 hourly slots when the configured list is absent/empty, and includes valid saved capacity keys missing from that list. Explicit zero capacities survive rendering, save and reload; a standard-capacity change still preserves closed slots. Empty grids and invalid integer/range inputs cannot issue a settings mutation. Failed settings reads do not invent defaults.

Eleven added regression tests first failed against the old implementation, then passed with the fix. Bookings 52/52 and the complete frontend suite 290/290 passed; ESLint, CSP, i18n, assets, links and diff check passed. Read-only security review confirmed unchanged organization/role/session/CSRF boundaries. Real Chromium desktop 1440x900 and mobile 375x812 verified per-hour changes, zero, Save and hard reload with an isolated synthetic in-memory API; warning/error console logs were empty. Captures stay ignored under `scratch/`. No backend, HTML, CSS or production/staging changes.

## Server-side capacity certification before merge

Disposable PostgreSQL reproduced five failures: closed-slot canceled-booking confirmation, settings closure racing admission, different accepted date spellings bypassing the hourly lock, unsafe notification compensation, and single-connection pool starvation. Additional inspection found the same admission requirement for completion and a cancellation race in no-show processing. These are ordinary lifecycle actions, not documented administrative overrides.

The scoped backend follow-up canonicalizes dates, serializes settings changes against admission using organization advisory locks, reuses the lock's task-owned repository connection, and atomically validates free-to-occupied transitions. Existing reserved confirmations and positive-capacity reactivation remain allowed. Notification compensation restores only when the original capacity and current snapshot permit it; otherwise the safe new reservation remains flagged for human intervention. No provider retry, schema/migration, auth, frontend, or production/staging changes. The existing empty/partial settings policy is unchanged.

Twenty-four added PostgreSQL cases cover zero persistence, manual API/internal adapter and both real AI admission paths with offline LLM inputs, positive/full limits, tenant scope, concurrency, date/hour/DST semantics, lifecycle conflicts, and conditional mutation safety. Targeted booking QA: 288 passed / 10 existing external sandbox skips; concurrency unit tests: 3 passed. Ruff CI selection, compile and diff checks passed. Full Python remains an exact-head CI gate; publication is not deployment.
