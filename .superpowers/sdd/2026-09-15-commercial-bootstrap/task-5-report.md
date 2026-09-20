# Task 5 report — Oracle VM bootstrap and operator runbook

## Status

Complete and ready for parent integration. This task did not modify the dirty
frontend/i18n worktree, `docker-compose.yml`, `compose.production.yml`, or the
production `Caddyfile`.

## Delivered

- `scripts/bootstrap_oracle_vm.sh`: idempotent Ubuntu 24.04 `amd64`/`arm64`
  bootstrap. It installs Docker Engine/Compose from Docker's official repository,
  provisions a non-root Docker-privileged deployment user, persistent layouts,
  swap, restrictive secret locations, a root-only backup cron wrapper, and
  opt-in UFW/SSH hardening.
- `docs/operations/oracle_vm_bootstrap.md`: precise VM, Oracle network, temporary
  hostname, final-DNS/canonical redirect, deployment, health, backup, Sentry,
  uptime, rollback, and recovery operator procedure.
- `tests/scripts/test_oracle_vm_bootstrap.sh`: offline syntax/argument/static
  controls. It never reaches apt, Docker, UFW, SSH, Oracle, DNS, or a provider.

## Security review

The bootstrap fails closed without an administration CIDR, temporary FQDN, and a
single valid public-key file. SSH/UFW changes require explicit attestation of a
separate deployment-user login; the script never resets UFW, removes unrelated
rules, or disables SSH before that attestation. It rejects any current UFW SSH
allow rule outside the requested CIDR. It contains no credentials, no automatic
cloud/DNS/provider purchase action, and does not publish application ports.

## Verification

```text
C:\Program Files\Git\bin\bash.exe tests/scripts/test_oracle_vm_bootstrap.sh
oracle VM bootstrap static tests passed

git diff --check -- scripts/bootstrap_oracle_vm.sh docs/operations/oracle_vm_bootstrap.md tests/scripts/test_oracle_vm_bootstrap.sh
passed
```

## Remaining operator-controlled gates

Oracle availability/network rules, DNS, TLS issuance, CI-produced multi-arch
image availability, production secrets, external webhooks, R2 billing/quota,
backup restore drill, Sentry, and uptime alerts must be verified by the operator.
The existing production Caddy/compose configuration is intentionally consumed by
the runbook but was left to Task 3, which owns release-container routing changes.
