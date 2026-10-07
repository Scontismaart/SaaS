# Phase 8 — closed beta gate

Status: **FAIL / NO-GO**. Phase 7 is incomplete and temporarily deferred.
An application-wide access-revocation blocker was found in final review.
Baseline: `origin/main` `2383640889fd1ef12cd141e076caccf489ed2eaa`.
This separate branch does not contain unmerged Phase 7 changes. No deploy,
provider configuration, production credentials or real users are in scope.

## Deferred register

| Gate | Classification | Release boundary |
| --- | --- | --- |
| Calendar real consent/certification | BLOCKER CLOSED BETA | Disabled until Phase 7 certification |
| Business/Reviews real consent/certification | BLOCKER CLOSED BETA | Disabled until Phase 7 certification |
| WhatsApp and Instagram sandbox unavailable | BLOCKER CLOSED BETA for those channels | No real outbound activation |
| Airtable sandbox unavailable | DEFERRED BEFORE PUBLIC/PRODUCTION | No provider activation |
| Phase 7 final full Python rerun | BLOCKER CLOSED BETA | Phase 8 cannot certify unmerged Phase 7 |
| Email provider, DNS/domain | DEFERRED BEFORE PUBLIC/PRODUCTION | No deliverability claim |
| Calendar scheduler/Airtable reaper fixes | DEFERRED in unmerged Phase 7 | Known fixes are not imported into this branch |
| python-jose residual CVE-2026-85394 | NON-BLOCKING, mitigated not fixed | RS256/ES256-only verification; exact-version/advisory policy and regression |
| Staging deployment and provider smoke | DEFERRED BEFORE PUBLIC/PRODUCTION | No deployment in this task |
| Backup/restore for real customer data | BLOCKER BEFORE REAL CUSTOMER DATA | `docs/DEPLOY.md` explicitly requires a verified encrypted backup/restore drill |
| Complete access revocation / JIT provisioning | P1 BLOCKER CLOSED BETA | Removing all memberships can create a fresh owner org for a still-valid JWT; an explicit application-level revocation/provisioning policy is required |

`roadmap-pubblicazione.md` is absent from this baseline. `docs/product/roadmap.md`
is a stub; the historical master launch roadmap is not current certification.
Use the explicit Phase 8 instructions, the current release runbook and recent
merged Phase 5/6 evidence. Phase 6 live MFA/auth evidence is retained; no human
MFA, provider consent or credential change is requested.

## Evidence

Autonomous checks and final results are recorded here before delivery. Passing
local checks does not prove a cloud deployment, provider consent, live channel
delivery, legal approval, production secret rotation or backup recovery.

### Scoped release corrections

- A TLS substring in a database password/fragment previously passed preflight.
  Preflight and production startup now share effective PostgreSQL URL parsing:
  one `sslmode=require`, `verify-ca` or `verify-full`; malformed/duplicate modes,
  missing database and default credentials are rejected without printing values.
- Production startup also rejects missing/unsafe Auth configuration, wildcard,
  HTTP or unapproved CORS/CSRF origins, and non-private/unbounded proxy networks.
  Origins must match `PUBLIC_APP_URL`; the two canonical Melpis HTTPS origins
  remain supported. Temporary hosts require their own explicit origin. Use the
  compose proxy subnet `172.30.0.0/24`, not an entire private address space.
- A Windows checkout reproduced web entrypoint exit 127 before legal validation.
  The web image now normalizes that shell script to LF during build. The normal
  nginx entrypoint is retained; missing legal configuration still blocks startup.

### Autonomous verification

- Disposable PostgreSQL 16/pgvector: base schemas, triggers and all 55 ordered
  `0*.sql` migrations applied from zero and reapplied successfully; 41 RLS
  tables and 43 policies. No staging/production database used.
- Selected auth/MFA/AAL2, CSRF, tenant/IDOR, OAuth state, GDPR export/delete,
  retention, AI safety, webhook security, logging/audit and release tests:
  696 passed. Final release-only additions are covered by the final full suite.
- Recent merged live Auth/session/desktop/mobile/MFA certification is reused
  from `docs/phase6-authenticated-qa.md` (2026-10-06); no redundant human MFA run.
- Frontend: 132/132 DOM tests, lint, i18n (3,148 keys), CSP, assets, links, SEO,
  images and advisory hardcoded checks passed; npm audit high: zero findings.
- Python dependency audit: 201 packages; only exact-version/advisory reviewed
  residuals accepted. No new exception, dependency change or claim of upstream
  python-jose remediation. The algorithm-confusion regressions remain required.
- Compose production syntax and both Caddy configurations validated with only
  synthetic/public configuration; no deployment or image publication.
- Existing offline bootstrap and backup/restore shell guard tests PASS; no VM,
  provider request or actual production restore was invoked.
- One final full Python: **2449 passed / 33 skipped / 0 failed / 0 errors**, 1117.70s.
  Skip audit: 20 explicitly opt-in live LLM tests; 13 provider sandbox tests
  (Airtable 3, Apaleo 3, SimplyBook 4, WuBook/ZaK 3). No Phase 8 test skipped.
- Ruff CI selectors, tracked Python `py_compile`, tenant guard and diff check PASS.
- Gitleaks main history PASS with the existing main-version exact fingerprint
  policy. An initial scan used the old primary-checkout policy and reported the
  three already-reviewed fingerprints; no exception was added or broadened.
- API amd64 and web amd64/arm64 built locally without push. API arm64 requires
  the native-runner PR CI build; local emulation initially hit a download timeout
  and was retried. Do not treat a pending architecture build as certification.
  API live/ready 200;
  unauthenticated API denied; all nine private deep links and private JS denied;
  public auth/legal pages 200; direct legal templates 404. Web tested non-root,
  read-only and with capabilities dropped using its normal entrypoint. Missing
  legal config blocks web; incomplete production config blocks API startup.
- Graphify: one successful update; optional SQL parser unavailable, non-blocking.

## Operational safety and objective stop criteria

The first permitted local cohort uses synthetic data only, at most **10 named
users**, and an operator-maintained roster. This is an operational cap, not a
new application invite feature. Before any externally accessible beta, verify
public signup is disabled at Supabase Auth and add only reviewed invitees.
The existing `/api/auth/register` is not itself an invite-only boundary.
No production/staging Auth settings were changed or certified here.
[Auth configuration](https://supabase.com/docs/guides/auth/general-configuration)
documents the provider-side control.

**Access-removal gate: FAIL.** Removing all memberships is not a reliable account
lockout. `get_organization_context` auto-provisions an owner organization when
memberships are empty, and the OAuth callback invokes the same provisioning
method. `OrganizationRepository.get_or_create_organization_with_owner` creates a
fresh trial/owner membership for an existing profile. A valid JWT can therefore
regain application access, although it does not regain the removed tenant's data.
The actual dependency was reproduced with an already-verified synthetic identity
and empty-then-created memberships; repository SQL was reviewed to confirm that
this is not an invented mock-only behavior.

Provider ban and global logout stop new login/refresh but are not instant
invalidation of every issued JWT. Application logout only deny-lists tokens
presented by that logout; it is not a user-wide revocation mechanism. Do not use
membership deletion, browser cookie deletion or destructive profile deletion as
a claimed safe global lockout. See [admin ban](https://supabase.com/docs/reference/javascript/auth-admin-updateuserbyid)
and [session semantics](https://supabase.com/docs/guides/auth/sessions).

Closing this gate requires a separately reviewed application account/session
revocation policy that also constrains both JIT call sites. This changes the Auth
provisioning model, not release configuration, so Phase 8 stops short of that
architectural change. No auth/tenant source behavior was altered to conceal the
finding. Until resolved and regression-tested, do not onboard external beta users.

The automated security suite remains green, but does not test account-wide
revocation after deleting **every** membership; a passing suite is not proof of
this missing operational capability. Auth/session certification from Phase 6 is
preserved for its original scope, not extended to this newly identified case.

CRM AI tools remain source-owned OFF and cannot be enabled by clients/prompts.
Tenant suspension/quota, budget/rate-limit kill switches and deterministic
mutation authorization remain the controls for allowed AI. No live model call
or provider side effect was needed for this gate. Keep Calendar/Business off,
and do not configure Meta/Airtable channels before their Phase 7 certification.

Incident triage uses trace/org/conversation/message identifiers, sanitized
structured logging, audit events, ready/live checks and existing error capture.
Before external users, assign an incident owner and verify deployed alert delivery,
secret-rotation evidence, controlled onboarding and legal approvals. Local tests
prove mechanisms, not their activation in an untested deployment.

**GO (technical):** all required local regressions/build/static gates green;
P0/P1/P2 release findings zero; tenant and AI controls green; no unreviewed
secret/dependency finding. **GO (closed beta):** additionally close required
Phase 7 gates and operational rollout evidence, including verified separate
encrypted backup/restore before real customer data. These remain blocking.

**STOP immediately:** cross-tenant access, secret exposure, privileged model
mutation, false booking success, duplicate side effects, failed revocation,
quota/accounting bypass, failed DB readiness/migration or unrecoverable data loss.
Stop beta traffic and new onboarding, suspend affected tenant AI and preserve redacted
trace/audit evidence. Do not re-enable until a targeted regression passes.

Rollback follows `docs/DEPLOY.md`: retain previous API/web digest references,
restore those references together, and do not remove additive migrations. A
failed migration requires stopped traffic and a verified restore. Artifact and
runbook checks do not certify a real host rollback or encrypted off-site recovery.
