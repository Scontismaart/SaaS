# Phase 7 — integration hardening / QA progress

Status: **CONDITIONAL — technical gates PASS**. Real Calendar and Reviews consent,
callback, refresh and grant revocation have been exercised; real Calendar event
and scheduler QA passed. The final full regression passed with zero failures
and errors. Reviews resource access is externally blocked by Google quota zero.
Phase 7 is technically ready, not fully real-provider certified. Delivery is
authorized as a CONDITIONAL PR only; no merge or deployment is authorized.

Branch: `codex/phase7-integrations`, based on updated `origin/main`
`2383640889fd1ef12cd141e076caccf489ed2eaa` (Phase 6 merged).

## Scoped fixes

- Calendar scheduler uses the actual `organization_id` credential key.
- Calendar reconnect preserves the owner's existing `sync_enabled=false` and
  chosen calendar instead of implicitly re-enabling sync. A real PostgreSQL
  callback regression reproduced the old `true` result before the one-line
  fix and verifies refreshed encrypted tokens, future expiry, unchanged calendar
  and disabled sync afterward; a fresh connection retains the existing default.
- Airtable stale reaper uses a bounded, ordered CTE, `FOR UPDATE SKIP LOCKED`,
  and correlates both event ID and organization ID. PostgreSQL tests cover
  batch/age/status filtering, repeated execution and a concurrent row lock.
- Calendar event creation uses a stable tenant/booking ID and verifies private
  ownership before reconciling a conflict. A missing/foreign booking is denied
  before provider mutation. Failed deletes retain the local reference; absent
  remote events are idempotent success. Failed updates do not report success.
- Meta and Airtable do not blindly retry ambiguous outbound mutations after
  read/write timeout or HTTP 5xx. Explicit 429 rejection and pre-connect errors
  retain bounded retry; safe Airtable reads retain their retry behavior.
- Provider exceptions/logs are sanitized. SMTP retries only definite temporary
  rejection; ambiguous delivery is not repeated, and worker logs omit message
  subjects and raw exception text.
- Reviews uses the actual v4 `parent` resource parameter, canonical account/
  location matching, and the official discovery URL. Regression tests use a
  generated Google API client with a network-free recording HTTP transport.
- Airtable live QA requires dedicated sandbox variables and explicit
  `AIRTABLE_SANDBOX_CONFIRMED=true`; incidental general credentials never opt in.
- Tenant guard exceptions were updated only for the two exact, previously
  authorized worker SQL literals. No function-wide exemption was introduced.
- Google OAuth start preserves the selected organization during browser
  navigation. Its query selector is validated only on integration start routes,
  requires exact owner membership, rejects conflicting header/query selectors,
  and retains the existing AAL2 and session-bound callback gates. Frontend
  preflight failures do not continue navigation.
- Live Google callback reproduced `InvalidGrantError`: the installed SDK
  automatically sent a PKCE challenge, but the separately created callback
  flow lost its verifier. Both integrations now derive a server-only verifier
  from a domain-separated keyed MAC of channel, organization and bound nonce.
  PKCE remains enabled; no verifier is exposed in authorization URLs or stored
  client-side. Callback diagnostics log exception class only, never provider
  exception messages or tokens.
- The next live callback exposed OAuthlib's scope-change `Warning`: Google
  returned additional grants previously authorized for the same client. Token
  exchange accepts that specific validated SDK warning only when every required
  scope remains present and the original requested scope set matches exactly.
  Missing required grants and unrelated warnings still fail closed; no global
  scope-validation bypass is enabled and extra grants do not confer app rights.
- A targeted security review reproduced a missing-scope bypass when an external
  runtime enabled `OAUTHLIB_RELAX_TOKEN_SCOPE`. The application now verifies
  returned scopes unconditionally after exchange, independently of SDK flags.
  Scope omission retains RFC 6749's requested-scope default; explicit missing
  grants are denied before credential persistence. Regression was RED before
  the fix and GREEN afterwards; the scoped review confirmed the blocker closed.

Contracts: [Calendar event IDs](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert),
[Reviews list](https://developers.google.com/my-business/reference/rest/v4/accounts.locations.reviews/list),
[Business discovery](https://developers.google.com/my-business/reference/rest).

## Executed checks

- Integration/security batch: **765 passed, 3 skipped, 0 failed/errors**,
  including OAuth session/user/org binding and replay, Reviews, WhatsApp,
  Instagram, webhook persistence/identity/signatures, Airtable, email code QA,
  tenant guard regressions and preserved Phase 5 AI safety.
- Additional generated-client Reviews contract regressions: **6/6 passed**.
- Malformed Meta response regressions: **4/4 passed**; missing provider message
  IDs are denied without exposing response details or blindly retrying.
- Meta client suite after this final fix: **19/19 passed**.
- Additional PMS/external booking repository, Beds24 adapter and integration
  route tests: **47/47 passed** (no real provider credentials/network).
- Total distinct targeted regressions: **822 passed**, plus **3 unavailable
  Airtable live sandbox tests skipped**. This is not a full Python suite run.
- Updated Reviews API suite: **35/35 passed** after the contract fix.
- Frontend: **132/132 passed** after the CI-prescribed i18n/FullCalendar build;
  lint, i18n and CSP/assets/links/SEO/images gates passed. No substantive web diff.
- Ruff CI selection, tenant guard and diff check passed.
- Final Python compilation passed for **473 files**; Ruff CI selection,
  tenant guard and diff check passed after the final code changes.
- Graphify code graph updated; SQL extraction dependency is unavailable and
  semantic document extraction is non-blocking.
- After the multi-org navigation fix: OAuth/session/Google flag regressions
  **78/78 passed**, and new browser-navigation unit regressions **6/6 passed**.
  These targeted checks do not constitute a full regression run.
- After PKCE hardening: **113/113 targeted OAuth/credential-security tests
  passed**, including real SDK instances, matching S256 challenge/verifier,
  channel/org/nonce/key separation and secret-safe diagnostics. The new real
  Google consent attempt remains pending; automated PASS is not live certification.
- After scope-change handling: **117/117 targeted OAuth/credential-security
  tests passed**, including actual SDK token parsing for exact grants,
  supersets and denied missing grants for both integrations.
- Current frontend suite: **138/138 passed**. All CI frontend gates passed;
  npm dependency audit reports **0 vulnerabilities**. Generated web files have
  no substantive diff; `web/app.js` contains the scoped navigation fix.
- Current Ruff CI selection, compilation of **470 source/test/script Python
  files**, tenant guard and diff check passed.
- Real isolated local API checks: **41/41 passed** for both Calendar and
  Reviews start, anonymous/foreign/malformed/conflicting selectors, selected
  organization A/B, S256 challenge, required scopes, provider denial,
  one-time state replay rejection and absence of credential writes on denial.
  This check did not contact Google or exchange a provider token.
- After the runtime-flag bypass fix: **123/123 targeted OAuth/security tests
  passed**, including exact, superset, missing, relaxed-missing,
  relaxed-superset and omitted scopes with actual SDK instances. Both missing
  cases assert zero credential writes. The local API check remained **41/41
  passed** after loading the fix. Ruff and tenant guard passed again;
  final container-based compilation covered **474 Python files**.
- Gitleaks **v8.30.1** scanned the tracked Phase 7 diff and new scoped
  source/test/script/documentation files in a network-disabled container:
  **no leaks found**. Ignored private QA files were not submitted to the scan.
- After the reconnect preference fix on 2026-10-08: focused reconnect/scheduler
  checks **2/2 PASS**, complete affected Reviews/API suite **39/39 PASS**.
  Affected Python compilation, Ruff CI selectors and diff check PASS. Graphify
  code update completed without LLM calls (SQL parser remains unavailable,
  non-blocking). These targeted runs do not replace the pending final full suite.
- Final scoped security diff review found **P0=0, P1=0, P2 Phase7=0** in
  authorization/PKCE/required scopes, Calendar ownership/idempotency, bounded
  retries and sensitive logging. This does not certify blocked real providers.
- Final frontend rerun: **138/138 PASS**; lint, i18n, FullCalendar CSS,
  CSP/assets/links/SEO/images gates PASS. Current Ruff CI selectors, Python
  compilation, tenant guard and diff check PASS. Fresh secret scans of the
  tracked diff and new scoped test/documentation files found no leaks.

DB-backed automated tests used disposable regression databases on isolated
test networks. Local API boundary checks used only the temporary QA account
and its two synthetic organizations in isolated local Auth. No real provider
credentials were passed to automated regression containers.

The single full Python regression completed on newly created,
internal-network-only `phase7-regression-db`: **2516 passed, 33 skipped,
2 failed, 0 errors** in 1293.90 seconds. It received an ephemeral encryption
key and synthetic DB credentials only. The two failures were Reviews test
fixtures that lacked real database membership for their simulated Auth user
after the new exact-membership check. They were reproduced separately and
corrected by provisioning synthetic Auth/profile/owner membership rows, not
by bypassing the new authorization check. The complete affected suite then
passed **35/35**; three new real-PostgreSQL denial regressions passed **3/3**
(foreign org, revoked membership, limited role denied before nonce creation).
Thus the affected suite was **38/38 passing** before the additional reconnect
regression. The original full run's two failures remain historical evidence;
the subsequent final clean full run below supersedes its release result.

On 2026-10-08, after all source fixes and available provider QA, a single final
full Python run completed on a newly created internal-only disposable database:
**2522 passed, 33 skipped, 0 failed, 0 errors** in **1243.075 seconds**.
Its fresh JUnit artifact reports 2555 tests, 33 skips and no failures/errors.
The runner received only synthetic database credentials and an ephemeral
encryption key; no real provider credentials. Source remained unchanged during
the run. Frontend **138/138**, npm audit **0 vulnerabilities**, Ruff CI selectors,
Python compilation (**470 files**), tenant guard and diff check all PASS.

The 33 skips are explicit external/opt-in tests: **20 live LLM**, **3 Airtable**,
**3 Apaleo**, **4 SimplyBook**, **3 WuBook ZaK**. No configured sandbox or
confirmed free live-LLM account was supplied to this isolated run.

Final regression is complete; delivery proceeds conditionally. Real Calendar QA is complete;
Business resource QA is externally blocked. Temporary local Auth QA fixtures
were removed after the provider checks. Regression containers,
databases and their isolated network are disposable and removed after tests.

## Provider availability / hand-off

The initial presence-only inventory was corrected: a Google callback URL in an
example file is not a configured OAuth client, and a Meta app secret is not an
Instagram outbound access token. No usable Google client secret, WhatsApp/
Instagram sandbox access token or Airtable sandbox token was found locally.

Browser inspection found the existing `Melpis Staging Web` OAuth client in
Google Cloud project `melpis-staging`. The user created a parallel secret.
An inspection accidentally included its value in tool output; the user then
disabled and deleted that new secret, leaving the original secret enabled.
The replacement JSON was verified without displaying its value and is used
only in a Git-ignored local runtime environment. The user saved Calendar and
Reviews callback URLs for `http://localhost:4187`; the existing Supabase
callback is unchanged. Do not copy secrets into reports or source control.

The dedicated Phase 7 runtime serves current Phase 7 source on loopback port
4187, reuses only the isolated local Auth/database, and has background jobs
disabled. One clearly named temporary QA owner and two synthetic organizations
were created there; they must be cleaned up at the end of provider QA. A local
test-only bootstrap performs real login/MFA and transfers the resulting
HttpOnly session cookies without displaying passwords, tokens or TOTP secrets.
The real Calendar connect button reached Google's account picker. Google
account selection and consent remain a human gate; no real Calendar sync or
Business location access is certified yet. The existing application on port
4174 was not restarted or modified.

On 2026-10-08 the user completed real Calendar consent with the requested test
account. The live callback logged successful connection for the synthetic QA
organization and `/api/calendar/status` confirmed it. Sync was immediately
disabled through the authorized settings endpoint; background jobs remain OFF.
An isolated credential probe verified encrypted access/refresh persistence,
forced only this QA row's expiry, performed the real Google token refresh, and
verified the refreshed encrypted access token and future expiry persisted.
The QA organization has zero bookings; no Calendar event mutation was made.
This proves consent/callback/refresh, not complete Calendar certification:
provider revocation, reconnect/disconnect and test-calendar sync remain pending.
Reviews real consent/callback also succeeded on 2026-10-08. The isolated QA
probe verified encrypted access/refresh storage, forced only the synthetic QA
credential expiry and successfully refreshed against Google, verifying encrypted
persistence and future expiry afterward. No account/location is selected.
Read-only `GET https://mybusinessaccountmanagement.googleapis.com/v1/accounts`
returned HTTP **403**, Google ErrorInfo reason **SERVICE_DISABLED**. Thus Business
account/location access is externally blocked, not certified by successful OAuth.
No reviews were read or mutated. The user enabled the corresponding API in the
test project. The next read-only request returned HTTP **429**, ErrorInfo
**RATE_LIMIT_EXCEEDED**, with **quota_limit_value=0**. This is an evidenced
external API-access/quota approval gate, not a failed OAuth implementation.
Real account/location selection and reviews access remain EXTERNAL BLOCKED.
[Official accounts.list contract](https://developers.google.com/my-business/reference/accountmanagement/rest/v1/accounts/list)
and [GBP prerequisites/access request](https://developers.google.com/my-business/content/prereqs).

The authorized QA lifecycle check then POSTed the QA refresh token in the body
to Google's documented revocation endpoint (never printed): HTTP **200**.
Both real provider refreshes subsequently failed closed; Calendar sync remained
disabled. Both authenticated local disconnect endpoints succeeded and `/status`
confirmed no stored connection. No account/profile/calendar data was deleted.
Calendar reconnection after real grant revocation succeeded on 2026-10-08;
the fresh connection and a further real Google refresh were verified, with
encrypted persistence and zero QA bookings. Sync was disabled again immediately.
At that checkpoint the configured calendar was still `primary`; no event
operation was run against it. Business reconnection/provider functionality remains conditional
on external access.
The user subsequently created the dedicated `Melpis Phase7 QA` calendar and
supplied its public resource ID. The narrow application grant cannot enumerate
calendars (`calendarList.list` returns HTTP 403 `insufficientPermissions`), so no
additional OAuth scope was requested. A read-only events-list probe against the
specified QA calendar initially returned HTTP 403 `accessNotConfigured`.
After the user enabled Calendar API, the real events-list response confirmed
the exact QA calendar name, owner/write access, no events and no default
reminders. Only then was this synthetic organization's calendar changed to the
dedicated QA resource and one synthetic booking inserted in the local database.
The actual scheduler ran with that organization as the sole enabled credential,
created the deterministic Google event and persisted its ID/last-sync timestamp.
A direct create retry reconciled Google's 409 to the same owned event; another
scheduler run left exactly one event. Create/update/delete with the other QA
organization were denied. A real update was read back from Google; cancellation
deleted the event and cleared the local reference; repeated deletion succeeded
idempotently. A missing-event lookup produced real HTTP 404. Remote cleanup
confirmed no active events, the synthetic booking was removed and sync returned
OFF. Global background jobs remained OFF throughout; no attendees or effective
reminders existed, no personal calendar was modified. **Calendar real E2E PASS**.
The browser-control module currently fails bootstrap with EPERM;
this limitation is not treated as evidence of a successful live browser test.
Final provider cleanup revoked the remaining QA grant (HTTP 200), verified
refresh denial, disconnected both integrations and confirmed disconnected status.
Only the verified `phase7-owner-*` local test account and its two named synthetic
organizations were deleted; obsolete local QA credentials/session files were
removed. The user's dedicated calendar was retained empty. Google client
configuration remains Git-ignored and was never included in regression runners.
WhatsApp/Instagram are **not available** without verified test identities and
access tokens. Airtable live tests are safely skipped without dedicated sandbox
credentials; its code and actual PostgreSQL gates passed.

DNS/domain verification, SPF/DKIM/DMARC, real email provider/SMTP setup and
deliverability are **DEFERRED — WAITING FOR DOMAIN**, explicitly non-blocking.
`roadmap-pubblicazione.md` was not found; this QA follows the explicit Phase 7
request and existing integration documentation instead.
