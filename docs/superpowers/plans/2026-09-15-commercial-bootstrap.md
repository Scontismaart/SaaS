# Commercial Bootstrap Release Plan

## Objective

Prepare Melpis for a real Day-1 commercial launch with Stripe Live while keeping fixed infrastructure and AI spend at EUR 0 until the user explicitly authorizes a paid provider. The release remains blocked until CI, deployment drills, legal identity data, production credentials, DNS, and live webhooks are complete.

## Global Constraints

- Production profile: `APP_ENV=production`, `LAUNCH_PROFILE=commercial_bootstrap`, `SANDBOX_ONLY=false`.
- Stripe production credentials must be Live (`sk_live_`, `pk_live_`, `whsec_`) and all six monthly/annual Price IDs must be configured. Test credentials remain valid only in an explicit sandbox profile.
- AI remains free-only: `LLM_COST_POLICY=free_only`, Groq allow-listed models only, `GROQ_FREE_ACCOUNT_CONFIRMED=true`, and `GROQ_ZDR_CONFIRMED=true`. No automatic paid upgrade, card attachment, or provider switch is authorized.
- Google Calendar and Google Business integrations default disabled through explicit feature flags.
- No secret is committed, logged, rendered to clients, or requested in chat. `.env.production` exists only on the server.
- Preserve tenant isolation, quick webhook acknowledgement, idempotency, deterministic authorization, opt-out fail-closed behavior, guardrails, cost attribution/kill switches, traceability, and human escalation.
- `melpis.it` serves the landing page, `/app/` serves the application, and `app.melpis.it` redirects to `https://melpis.it/app/`. A temporary TLS hostname may be used before domain purchase.
- Deployment images are immutable and support `linux/amd64` and `linux/arm64`.
- Backup data is encrypted before leaving the host. Restore drills never overwrite production and require an explicit non-production target.
- R2 and other usage-metered services are not described as unconditionally free; deployment documentation must state quotas and cost-control responsibilities.
- Legal entity data must never be fabricated. Missing identity fields remain explicit go-live blockers in a single, easy-to-complete configuration surface.

## Task 1: Commercial launch safety profile

Update `src/core/startup_guard.py`, `scripts/release_preflight.py`, production environment examples, and focused tests so the commercial bootstrap profile accepts Stripe Live together with Groq free-only. Fail closed on mixed Stripe modes, placeholders, missing live Price IDs, absent Groq free-account confirmation, absent Groq ZDR confirmation, non-allow-listed models, or paid AI policy. Keep a separately explicit sandbox profile for test credentials. Add disabled-by-default Google Calendar and Google Business flags. Document the manual reauthorization requirement before any paid AI upgrade.

## Task 2: Frontend claims and legal completion surface

Remove every claim of automatic SDI invoicing from customer-facing pages and replace it with accurate wording: immediate Stripe receipt and fiscal invoice on request. Search all public assets for equivalent claims. Prepare privacy, terms, DPA, and legal guidance so definitive company identity fields are centralized, conspicuous go-live blockers without inventing legal facts. Add focused regression checks where practical.

## Task 3: Multi-architecture CI and release containers

Extend GitHub Actions to run the existing Python, frontend, tenant-isolation, and deployment checks, then build and publish immutable GHCR images for `linux/amd64` and `linux/arm64` only after validation succeeds. Ensure Dockerfiles and `compose.production.yml` work on Oracle Ampere A1 and x86 fallback. Configure Caddy for a temporary TLS hostname and final `melpis.it`/`app.melpis.it` routing without exposing application ports directly. Do not publish mutable production releases from pull requests.

## Task 4: Encrypted Supabase backup and restore drill

Create `scripts/backup_supabase_r2.sh` and `scripts/restore_supabase_drill.sh`. The backup must use TLS `pg_dump`, encrypt locally with authenticated strong encryption before upload, use the R2 S3-compatible API, avoid secrets in process output, and delete objects older than seven days. The restore drill must default fail-closed, accept only an explicitly marked non-production target, validate/decrypt the artifact, restore it, and perform useful integrity checks. Document required tools, variables, quotas, scheduling, alerts, and recovery limitations.

## Task 5: Oracle VM bootstrap and operator runbook

Provide an idempotent Ubuntu 24.04 bootstrap script and release runbook for ARM64 or x86: Docker Engine/Compose, non-root deployment account, SSH/UFW hardening (22 restricted to an explicit CIDR, 80/443 public), swap, persistent application directories, Caddy/container startup, temporary-host flow, final DNS flow, health checks, rollback, backup cron, Sentry/uptime setup, and secret-file permissions. The script must never embed credentials, silently weaken SSH, or claim Oracle/R2 capacity is guaranteed.

## Task 6: Reconcile concurrent frontend and localization work

Audit and integrate the user's current uncommitted multilingual frontend/i18n work without losing intended content. Keep product source, generated localized routes, required assets, build/audit scripts, and focused tests; exclude screenshots, browser-QA scratch scripts, prototypes, and unreferenced duplicate assets from the release commit while preserving them locally. Remove any CSP regression: production `script-src` and `style-src` must not use broad `'unsafe-inline'`; executable inline scripts and style blocks must be externalized or protected by reproducible CSP hashes, while the minimum documented `style-src-attr` compatibility exception may remain for existing dynamic geometry. Verify all referenced local assets exist, no production page depends on third-party demo imagery, no secret is present, localization generation is deterministic, and lint/i18n/link/SEO/image/frontend tests pass. This task is intentionally combined with Task 2 because the legal/pricing pages are generated into every locale.

## Release Gate

- All local and GitHub Actions checks green.
- Task-scoped reviews and final branch security/code review approved.
- No committed secrets or production data.
- User supplies legal identity data and all production credentials directly on the VM.
- Oracle VM, R2 checkout/billing safeguards, Resend domain, Sentry, Stripe Live products/prices, and Groq ZDR settings verified by the user.
- Temporary-host end-to-end smoke test succeeds before domain purchase.
- Final DNS, TLS, Stripe Live webhook, Meta webhook, email authentication, backup restore drill, and monitored health check succeed.
- Tag is created only after PR approval/merge and green CI; this plan does not authorize an automatic merge or paid-provider activation.
