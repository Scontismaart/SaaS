# Task 3 report — Multi-architecture CI and release containers

Status: **DONE_WITH_CONCERNS**

Commits:

- `02be1deb3805b71f78979268be4ce0db61f944f9 ci: publish multi-architecture release images`
- `76cf8a6 fix: support immutable image digest refs`

## Implementation

- Extended GitHub Actions so tests, frontend checks, tenant-scoping checks, Compose validation, and release-container checks gate the image job.
- Added Buildx builds for API and web on `linux/amd64` and `linux/arm64`; pull requests build without publishing, while authorized push events publish SHA-only GHCR tags.
- Added Caddy routing for a temporary TLS host, final `melpis.it`, and redirect from `app.melpis.it` to `/app/`.
- Kept API/web ports internal; only Caddy publishes 80/443.
- Production Compose accepts immutable SHA tags or complete digest references.
- Added focused static/regression tests for workflow topology, platforms, tags, routing, and Compose exposure.
- Preserved all pre-existing dirty frontend/i18n files, including `web/Dockerfile` and `web/nginx.conf`.

## Verification

Implementer evidence before its reporting turn hit the usage limit:

```text
48 focused tests passed.
Tenant guard passed.
YAML topology passed.
Compose config passed.
Caddy validation passed.
Oracle bootstrap checks passed.
```

Controller verification of the final committed fix:

```text
python -m pytest tests/unit/test_release_containers.py tests/unit/test_release_preflight.py -q --basetemp <external>
31 passed in 0.86s

python scripts/check_tenant_scoping.py
TENANT SCOPING CHECK: OK
```

The local non-escalated Docker CLI did not expose the Compose plugin (`unknown flag: --env-file`); the implementer had already recorded successful Compose validation. The Buildx/QEMU multi-architecture smoke was running when its reporting turn hit the usage limit, so GitHub Actions remains the authoritative full multi-architecture build gate.

## Self-review and concerns

- No pull-request event can publish images.
- Image tags are full commit-SHA tags; digest references are also accepted by Compose.
- No mutable production tag is generated.
- No user-owned dirty frontend file was staged or committed.
- A real GHCR push and both-platform build require GitHub Actions credentials and must be observed in the PR before release.

## Round 1 remediation

- `compose.production.yml` now requires only `MELPIS_API_IMAGE_REF` and
  `MELPIS_WEB_IMAGE_REF`; the tag/name fallback has been removed. The read-only
  release preflight accepts only lowercase `repository@sha256:<64 hex>` values
  and rejects tag-only, uppercase, shortened, missing, or placeholder refs.
- The publishing job records `MELPIS_API_IMAGE_REF` / `MELPIS_WEB_IMAGE_REF`
  using Buildx's emitted digest in the GitHub Actions job summary for deployment
  operators. The SHA tag remains a traceability tag, not a deploy reference.
- Caddy is now explicitly selected with `CADDY_SITE_MODE`. `temporary` mounts
  only `Caddyfile.temporary` and names only `PUBLIC_HOST`; `final` mounts
  `Caddyfile.final` and is enabled only after final DNS resolves. This avoids
  premature certificate requests for `melpis.it` and `app.melpis.it`.
- The operator documentation now uses digest references and the two-stage Caddy
  switch. Focused tests block mutable refs and accidental final-host inclusion in
  temporary Caddy configuration.

Verification after remediation:

```text
python -m pytest tests/unit/test_release_containers.py tests/unit/test_release_preflight.py -q --basetemp C:\tmp\melpis-task3-tests
39 passed, 1 warning in 0.20s

git diff --check -- compose.production.yml Caddyfile Caddyfile.temporary Caddyfile.final .github/workflows/ci.yml scripts/release_preflight.py tests/unit/test_release_containers.py tests/unit/test_release_preflight.py .env.production.example docs/DEPLOY.md docs/operations/oracle_vm_bootstrap.md
passed

python compose/workflow YAML static validation
compose YAML/static digest selection passed
workflow YAML passed
```

The local Docker binary has no Compose plugin and its user config is unreadable,
so local `docker compose config` and Caddy-container validation remain delegated
to the existing GitHub Actions deployment-check step.
