# Dashboard modularization 03C — Bookings

Base: PR #71 merge commit `0074b2c21c67f12b2a8e9e372916116586d7db4b`.
Main CI `38036977948` passed: 236 frontend tests, 2599 Python passed / 33 existing skips / zero failures or errors, Ruff, compile, tenant guard, API/web amd64+arm64 publication and both verified GHCR manifests. Publication is not deployment. Migration workflow is path-filtered; this frontend change contains no migrations.

## Boundary and contracts

`web/dashboard-bookings.js` is a classic-script frozen factory with explicit API, shared escaping/date/i18n, live context/session, vertical, confirmation, notification and CSV dependencies. Public API: `onEnter`, `onExit`, `invalidate`, `load`, `aggiornaPrenotazioni`, `aggiornaSemaforo`, `apriBookingModal`. The shell keeps auth/session/refresh/CSRF, routing, organization switching, MFA, notifications and the shared CSV implementation. Overview's existing availability dialog and Simulator's existing refresh callbacks remain wired.

Transferred 21 existing named functions, original calendar/form/detail/capacity/filter/export handlers and local state. `app.js`: 6718 to 5956 physical lines, 762 removed. One new production module; no duplicate booking implementations left in the shell. Production COPY and read-only development mount include the script exactly once before `app.js`.

No backend, schema, provider, auth helper, router, shared helper, CSS, visible HTML, translation, dependency, landing or pricing changes. Prices remain 29/69/149; no Report route restored. Endpoint/method/payload/date and fifteen-minute slot contracts remain unchanged. No invented idempotency header.

## Lifecycle and security

Live user/session/selected-org/route/epoch and role checks surround asynchronous work, including JSON and destructive confirmation. Selected date and form/detail generations protect current interactions. Internal read/load reuse is single-flight; explicit refresh can supersede an older read. Mutation locks persist across exit until the request settles. Exit stops polling and closes only owned dialogs/confirmation. Scope change/logout clears private rows, events, settings, details and drafts; permission denial clears sensitive records. CSV cannot download a blob after invalidation.

Backend remains the sole permission authority. Staff forged events cannot issue reserved writes. Plain text/attribute values are escaped; path IDs encoded; availability class tokens validated. API requests still use shell CSRF/refresh handling. No credentials or raw errors are logged. Scoped security review found no remaining P0/P1/P2 Block3C issues. Real-provider certification was not repeated or inferred from fixtures.

## Tests and real-browser evidence

41 added tests: 39 behavioral Bookings tests and two synthetic-fixture tests. Existing auth, lifecycle, router, i18n, focus and async-race assertions were preserved and migrated to the production factory/script location. A test-only observation seam exposes private functions only inside the race harness, never in shipped code.

Targeted tests cover exact reads/writes, rendering, form validation, create/edit/status/capacity, duplicate/pending locks, errors/timeouts/403, role revocation, late JSON, scope changes/logout, cleanup, focus/Escape, inert hostile text/IDs, local dates/DST/midnight, polling and CSV. One local full frontend run executed 277 tests: 276 passed and one new test incorrectly dereferenced a nonexistent toast container when no toast was emitted. Only that test assertion was corrected; the complete Bookings file then passed 39/39. No second local full run or local full Python run; final complete frontend/Python acceptance is required from exact-head CI.

Real Chromium: desktop 1440x900 and mobile 375x812; nine canonical routes, sidebar, history, reload, calendar views/date navigation, form validity/synthetic submit, confirmation/Escape/focus, owner/Staff/denied/error/loading/timeout and actual synthetic A/B organization switching. Logout during a pending booking write, Back and hard reload left login visible with no private content. Captured warning/error console logs were empty. Synthetic loopback API only; no database, paid model, external provider or real user mutation.

All 12 immutable Block 1 images compared as decoded RGB: zero changed pixels, identical dimensions. Pointer/focus and transient rasterization were stabilized through real UI observation/repaint at the original viewport; no tolerance, image editing or baseline replacement. Additional Bookings captures cover empty/populated/calendar/form/confirmation/error/mobile. Screenshots remain ignored under `scratch/dashboard-03c-captures/` and contain synthetic data only.

ESLint, CSP, i18n (3148 keys), FullCalendar stylesheet, assets, links, dependency audit, diff check and staged secret scan are delivery gates. Graphify update completed; optional SQL parser warnings are non-blocking for this frontend-only extraction.

Leave Block 3C PR open. No merge, deploy, Block 3D or provider changes.
