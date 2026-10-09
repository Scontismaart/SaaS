# Dashboard visual baseline 01

This set contains six real-browser dashboard states at two viewport sizes, captured in the Codex in-app Chromium browser on Windows on 2026-10-08. All twelve repeated captures match the decoded RGB baseline exactly (zero changed pixels). These are initial baselines, not a claim about cross-platform pixel identity.

| Case | Route/state | Desktop | Mobile |
| --- | --- | --- | --- |
| Overview | `/app/overview`, empty activity data | `desktop-overview.jpg` | `mobile-overview.jpg` |
| Inbox | `/app/inbox`, no conversations | `desktop-inbox.jpg` | `mobile-inbox.jpg` |
| Bookings | `/app/bookings`, no bookings | `desktop-bookings.jpg` | `mobile-bookings.jpg` |
| Settings | `/app/settings?tab=generale`, synthetic organization | `desktop-settings.jpg` | `mobile-settings.jpg` |
| Simulator | `/app/ai-simulator`, empty synthetic conversation | `desktop-simulator.jpg` | `mobile-simulator.jpg` |
| Sidebar | Overview with desktop account dropdown open / mobile primary navigation drawer open | `desktop-sidebar.jpg` | `mobile-sidebar.jpg` |

Capture metadata is in `manifest.json`: Italian locale, dark theme, fixed time `2026-10-08T10:00:00.000Z`, synthetic owner, empty datasets, desktop 1440×900 and mobile 375×812. Capture the desktop account dropdown through `#sidebar-account-trigger`; capture the mobile drawer open through `#nav-toggle`.

## Synthetic capture setup

Run `node scripts/dashboard-baseline-server.cjs` and capture only from its loopback origin, `http://127.0.0.1:4190`. The server serves the real dashboard assets with an isolated synthetic API fixture. The fixture uses a reserved `.invalid` account and fake organization IDs, performs no database or provider calls, permits only the explicitly implemented synthetic message POST, and fails closed for unknown API reads and writes. Do not point it at a real backend or account.

The server injects `/__qa/bootstrap.js` only into the dashboard response. Its readiness marker waits for `document.fonts.ready`, lets finite production transitions finish, and pauses infinite live-status animations at frame zero. These are screenshot stabilization controls in the QA response only; they do not alter shipped dashboard files.

Wait for `body[data-qa-ready="true"].authenticated`, observe the resulting DOM/active panel before taking the screenshot, and keep the pointer away from controls. Use the same viewport, browser/OS, local Outfit font assets, route, empty fixture data and UI state for comparisons. Baselines have no live account or provider credentials. Readiness is not a substitute for checking the actual visible page.

## Comparison

The manual pixel comparison uses Pillow through `python scripts/compare_dashboard_baseline.py <baseline.jpg> <capture.jpg>`. It compares decoded RGB pixels strictly and exits nonzero if dimensions differ or any pixel changes. Pillow is a manual QA dependency, not a dashboard runtime dependency. The manifest test checks every mapped JPEG's file header and dimensions without Pillow or any added Node dependency.

The visual fixture is frontend-only coverage. It does not verify backend authorization, tenant isolation in a deployed service, or real provider/OAuth E2E behavior.
