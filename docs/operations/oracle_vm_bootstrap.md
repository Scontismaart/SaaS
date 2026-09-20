# Oracle VM bootstrap and release runbook

This runbook deploys a reviewed Melpis release to one Ubuntu 24.04 `amd64` or
`arm64` VM. It does not create an Oracle VM, purchase a domain, enable billing,
or assert that Oracle Always Free shapes, public IPs, block volumes, R2 quota,
or any other provider capacity are available. Check the actual tenancy, region,
quota, egress, backup-retention, billing, and recovery terms before proceeding.

The app remains tenant-isolated in application code; a VM firewall is not an
authorization boundary. Caddy is the only host-published container port. Do not
add `ports:` to the API, worker, web, or Valkey services.

## 1. Prepare the VM and SSH safely

Create a supported Ubuntu 24.04 image in an Oracle region where the selected
shape is presently available. Ampere A1 uses `arm64`; an x86 fallback uses
`amd64`. Confirm the image manifest supports the selected architecture before
deploying. Attach only storage and public networking the operator has approved.

In the Oracle network security group or security list, create these inbound
rules before changing the host firewall:

| Protocol | Destination port | Source |
| --- | --- | --- |
| TCP | 22 | the operator's explicit administration CIDR only |
| TCP | 80 | `0.0.0.0/0` and `::/0` |
| TCP | 443 | `0.0.0.0/0` and `::/0` |

Do not leave an Oracle-wide SSH rule in place merely because UFW is restricted:
both layers must enforce the administration CIDR. Keep the original cloud-console
or serial-console recovery path available. It is a recovery mechanism, not a
substitute for validating normal SSH access.

Choose a temporary FQDN under a DNS zone already controlled by the operator,
such as `melpis-vm.example.net`. Set its A record (and AAAA only if the VM is
reachable over IPv6) to the VM. Do not use `melpis.it` or `app.melpis.it` as the
temporary hostname. Use a real administration CIDR such as `203.0.113.8/32`,
not `0.0.0.0/0` or a guessed address.

Copy a **public** SSH key to the VM or make it readable by root. Never put a
private key in this repository, a command line, a shell history, or an env file.
From the VM console, run the initial non-destructive hardening stage:

```bash
sudo bash scripts/bootstrap_oracle_vm.sh \
  --admin-cidr '203.0.113.8/32' \
  --temp-host 'melpis-vm.example.net' \
  --ssh-authorized-key-file /root/melpis-deploy.pub
```

This installs Docker Engine and the Compose plugin only from Docker's official
Ubuntu repository, creates the `melpis` non-root account, adds it to the Docker
group, prepares persistent directories, creates swap, and installs a backup cron
wrapper. Docker-group membership is root-equivalent; grant it only to the
dedicated deployment account. The script makes no application, DNS, Oracle, R2,
or paid-provider change.

Open a *second* terminal and prove the deployment account can log in with the
new key before changing either SSH or UFW:

```bash
ssh melpis@VM_PUBLIC_IP
```

Keep the original console/SSH session open. Only after the second login works,
run the explicit hardening phase from the original session:

```bash
sudo bash scripts/bootstrap_oracle_vm.sh \
  --admin-cidr '203.0.113.8/32' \
  --temp-host 'melpis-vm.example.net' \
  --ssh-authorized-key-file /root/melpis-deploy.pub \
  --apply-firewall --apply-ssh-hardening --confirm-ssh-access
```

The script rejects absent CIDR/temporary hostname, any pre-existing UFW SSH
allow rule outside the requested CIDR, an untested hardening request, unsupported
OS/architecture, or an invalid public key. It does not reset UFW or delete
unrelated firewall rules. Re-run is
safe: packages, account, directories, swap, cron wrapper and restrictive SSH
configuration converge to the same state. Verify the active rules and a fresh
login before closing either existing session:

```bash
sudo ufw status verbose
ssh melpis@VM_PUBLIC_IP
```

## 2. Install the reviewed release and secrets

`/srv/melpis/app` is persistent across container recreation. Place only a
reviewed repository checkout/release bundle there as `melpis`; do not build an
unreviewed branch directly on the production VM. Ensure it contains the reviewed
`compose.production.yml`, `Caddyfile`, and `scripts/backup_supabase_r2.sh`.
Validate architecture and immutable image tags before a pull:

```bash
sudo -iu melpis
cd /srv/melpis/app
docker buildx imagetools inspect "$MELPIS_API_IMAGE:$MELPIS_IMAGE_TAG"
docker buildx imagetools inspect "$MELPIS_WEB_IMAGE:$MELPIS_IMAGE_TAG"
exit
```

The values above are intentionally not supplied by this document. Use an image
digest or the immutable release tag produced by CI; never use `latest`.

Create production configuration directly on the VM from the reviewed example.
It contains production credentials and must never be copied back to a workstation
repository, committed, logged, or passed as a command-line argument:

```bash
cd /srv/melpis/app
sudo install -o root -g melpis -m 0640 /dev/null .env.production
sudoedit .env.production
sudo stat -c '%U:%G %a %n' .env.production
# expected: root:melpis 640 /srv/melpis/app/.env.production
```

Populate all launch-profile and provider values by hand. Run the release gate
without printing the file:

```bash
sudo -u melpis python3 scripts/release_preflight.py --env-file .env.production
```

`/etc/whatsapp-ai-responder` and backup-drill allowlists are root-only. Keep
`backup.env`, R2 credentials, age identities, TLS roots, and restore target files
outside the checkout, root-owned and mode `0600`. Files readable by the deploy
group are already accessible to a Docker-privileged account, so do not treat that
group as a secrets boundary.

## 3. Temporary-host deployment and health gate

Set `PUBLIC_HOST=melpis-vm.example.net` in the root-managed `.env.production`.
The reviewed Caddy configuration must use this setting and must publish only
ports 80/443. Pull and start it as the deployment user:

```bash
sudo -iu melpis
cd /srv/melpis/app
docker compose --env-file .env.production -f compose.production.yml config --quiet
docker compose --env-file .env.production -f compose.production.yml pull
docker compose --env-file .env.production -f compose.production.yml up -d --remove-orphans
docker compose --env-file .env.production -f compose.production.yml ps
docker ps --format 'table {{.Names}}\t{{.Ports}}'
exit
```

The final command must show host bindings only for Caddy's `80` and `443`; API
port `8000`, web port `80` inside its container, workers, and Valkey must have
no host binding. Named Caddy and Valkey volumes survive `up`/`down`; never use
`docker compose down -v` in a routine rollback.

From an external administration host, test DNS/TLS and both health semantics:

```bash
curl --fail --show-error --resolve 'melpis-vm.example.net:443:VM_PUBLIC_IP' \
  https://melpis-vm.example.net/api/health/live
curl --fail --show-error --resolve 'melpis-vm.example.net:443:VM_PUBLIC_IP' \
  https://melpis-vm.example.net/api/health/ready
```

`live` proves the API/worker liveness contract; `ready` also checks required
dependencies and configuration. Do the full sandbox smoke test before buying or
switching the final domain: login/MFA, two-tenant isolation, signed webhook fast
ACK plus durable processing, STOP consent persistence, guardrailed reply,
escalation, and idempotent retry. See `docs/DEPLOY.md` for the full release gate.

## 4. Final DNS and canonical host cutover

Only after temporary-host smoke tests pass, create DNS records for `melpis.it`
and `app.melpis.it` at the VM IPs. Wait until authoritative DNS resolves from
outside the VM. Update the reviewed configuration to include both final hostnames
and ensure its host matcher redirects `app.melpis.it` with HTTP 308 to
`https://melpis.it/app/`; `melpis.it` is the landing-page canonical host and
`/app/` is the application path. Do not remove the temporary DNS record until
final TLS and webhook checks pass.

Apply the reviewed Caddy/compose release and verify:

```bash
sudo -iu melpis docker compose --env-file /srv/melpis/app/.env.production \
  -f /srv/melpis/app/compose.production.yml up -d
curl --fail --show-error https://melpis.it/api/health/ready
curl --fail --show-error --location --max-redirs 1 https://app.melpis.it/
```

Then update external webhook callback URLs and permitted redirect URLs only after
the TLS checks pass. Validate Stripe Live webhook signing, Meta signed webhook
ACK, Resend domain authentication, and final externally monitored health before
removing the temporary route. This runbook never authorizes a provider upgrade,
paid AI, R2 billing, or a domain purchase.

## 5. Backup, monitoring, rollback and recovery

The bootstrap installs `/etc/cron.d/melpis-backup` for 03:17 daily. It is inert
until an operator creates `/etc/whatsapp-ai-responder/backup.env` as root mode
`0600` with the variables required by `scripts/backup_supabase_r2.sh`, including
the age recipient/identity and R2 endpoint/bucket credentials. The script
encrypts before upload and verifies the artifact, but that is not a substitute
for a restore drill or a guarantee about R2 cost/retention. Configure an alert
for nonzero cron exits and inspect the first manual run:

```bash
sudo /usr/local/sbin/melpis-backup
sudo journalctl -t melpis-backup --since '24 hours ago'
```

Perform restore drills only against the fixed, root-managed non-production
targets accepted by `scripts/restore_supabase_drill.sh`; never aim a drill at
production. Confirm a recoverable artifact and a documented RTO/RPO before
calling backups complete.

Set `SENTRY_DSN` only in `.env.production`, retain appropriate PII scrubbing and
sampling, restart the compose stack, and send a controlled error from a sandbox
workflow to confirm the project receives it. Configure an independent uptime
monitor for `https://melpis.it/api/health/ready` (and alert delivery), with no
credentials in the monitor URL. Uptime checks do not replace Sentry, logs, or
the end-to-end webhook/worker checks.

For an application rollback, retain the prior immutable image tag and a private
copy of the prior root-managed env file. Change only `MELPIS_IMAGE_TAG` back to
the prior tag and rerun `docker compose ... up -d`; inspect `ps`, logs and both
health endpoints. Do not delete volumes or roll back additive database migrations
as part of image rollback. If data recovery is required, stop and use a verified
encrypted backup plus the non-production restore drill procedure; production
restore requires an explicit incident decision and a separate approved runbook.
