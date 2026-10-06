# Phase 6 — authenticated QA

Branch: `codex/phase6-authenticated-qa`, based on main
`53fdc92262fcd8a6c84ce5222e3c762695d1d102`. Evidence date: 2026-10-06.

## Scope and environment

Only isolated, loopback-bound local Supabase Auth and synthetic QA accounts and
organizations were used. Staging was not used because its non-production status
could not be established conclusively. Existing application containers, users
and data were not changed. JWT signature/issuer verification was not weakened.
Regression tests used a separate disposable database, never the QA Auth DB.
Runtime credentials and diagnostic harnesses are ignored and excluded from Git.
No secrets, OTPs, QR payloads, cookies or export contents are included here.
After QA, both disposable Auth users were deleted; their profiles and memberships
cascaded. Only their synthetic audit rows needed for cleanup were removed.
Existing users and data were untouched.

## Real authenticated checks

- Valid password login succeeded; an incorrect password was denied. Successful
  logout revoked the session; private API access and private hard refresh were
  denied afterwards.
- The real login → private page → completed logout → browser Back sequence
  showed no usable private shell. Back/forward and authenticated hard refresh
  also worked. A `pageshow.persisted=true` cache hit was not observed in this
  browser run; the actual history-security outcome passed, and handler tests
  additionally cover persisted restoration while private content stays hidden.
- Valid refresh succeeded. With the isolated Auth issuer temporarily configured
  for a 60-second access-token lifetime, natural expiry denied the old access
  token, valid refresh recovered access, and browser reload recovered correctly.
  Revoked/invalid refresh tokens returned 401; browser reload after revocation
  returned to login without a stale private shell. Auth was restored healthy with
  its original 3600-second lifetime and TOTP enrollment/verification enabled.
- Logout in one real tab invalidated another real private tab after the fix.
- All nine deep links completed real logout → unauthenticated direct navigation
  → login → exact requested destination: overview, inbox, bookings, reviews,
  team, ai-simulator, knowledge, ai-settings and settings.
- External URLs, protocol-relative URLs, encoded protocol-relative inputs,
  malformed encoding, javascript schemes and backslash-host inputs all kept
  successful login on the local overview fallback. OAuth next links stayed local.
- An owner role-update action succeeded; the same action by staff, including
  forged role/scope fields, returned 403. Cross-organization access returned 404;
  legitimate organization switching succeeded; an alien organization returned
  403. Revoking the exact synthetic membership denied its organization resource;
  the saved membership was restored immediately afterwards.
- Desktop sidebar navigation covered all primary sections and Settings, plus
  back/forward, hard refresh and logout. Actual 375-pixel mobile rendering covered
  the auth form, wrong/valid password, menu/sidebar, Inbox, Bookings, Reviews and
  logout without horizontal form overflow.
- Real 401/403, expired access, revoked refresh and an isolated Auth-service
  outage failed closed. The outage produced a controlled login error and denied
  private navigation. The Auth service was then restored. Automated tests also
  cover thrown refresh/network errors and prevent retry/redirect loops.

## Certified MFA gate retained

Real enrollment, QR decoding, valid OTP, invalid OTP denial, AAL1 before step-up,
AAL2 afterwards, logout, fresh login with a new MFA challenge and AAL1 403 versus
AAL2 200 on the actual protected endpoint passed. The user personally completed
valid authenticator-code entry. The previously certified 48/48 MFA/related tests
remain valid; live MFA was not repeated unnecessarily during the final QA pass.

## Minimal fixes and security review

- Read the current CSRF cookie on each mutation attempt, including the sole
  retry after refresh; remove stale caller headers when that cookie disappears.
- Hide private content and redirect on terminal authentication/refresh failure.
  Do not falsely report logout success if its API call fails.
- Hide the private shell before page caching and during persisted restoration;
  revalidate before reuse. Broadcast successful logout to same-origin tabs using
  only a non-secret event nonce, not credentials or user content.
- Distinguish enrollment 422 from invalid-code verification 422.
- Accept GoTrue's bounded rect-based QR SVG (up to 512 KiB), converting only its
  two literal black/white styles to allowlisted fill attributes. Tag/attribute,
  entity/doctype and node-count restrictions remain enforced; arbitrary CSS and
  external references remain rejected.

Changes do not grant roles, change tenant selection/authorization, weaken CSRF,
relax JWT validation or expose credentials. New focused regressions cover the
actual failures. No unrelated changes, merge, deployment or Phase 7 work.

## Automated gates

- Auth/session/CSRF/MFA/AAL2/safe-next/org/security suites: 477 passed, no skips,
  failures or errors.
- Complete frontend suite: 132 passed, no failures or skips. Frontend lint,
  dependency audit (zero vulnerabilities), i18n build/tests and CI CSP, assets,
  links, SEO, images and advisory hardcoded audits passed.
- Ruff CI selection, tracked Python compilation, tenant guard and diff check
  passed.
- Final full Python regression, executed once: **2424 passed, 0 failed, 0 errors**
  in 1255.68 seconds. The 33 skips are exclusively 13 external sandbox tests and
  20 explicitly opt-in live-LLM tests; **no Phase 6 tests were skipped**.

Graphify is non-blocking: no graph exists in this worktree. Delivery is a PR only;
merge and deployment remain explicitly excluded.
