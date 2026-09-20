# Encrypted Supabase backup and restore drill

`scripts/backup_supabase_r2.sh` creates a PostgreSQL custom-format dump over TLS, encrypts it locally with [age](https://age-encryption.org/) authenticated encryption, verifies the decrypted archive, and uploads the encrypted artifact plus SHA-256 manifest to Cloudflare R2. It never accepts `sslmode=require`: database TLS must use `verify-full`.

Install on Ubuntu 24.04: `sudo apt-get install postgresql-client age awscli coreutils`. The scripts execute fixed `/usr/bin` utilities under `/bin/bash`, rather than resolving provider or trust-check commands through caller `PATH`; run them only on managed Ubuntu hosts with those administrator-maintained binaries. Use a dedicated R2 API token scoped only to the backup bucket (read/write/list/delete); do not use an account-wide token. Inject all values with the host or CI secret manager, never a committed `.env` file.

Required backup variables: `BACKUP_PGHOST`, `BACKUP_PGPORT`, `BACKUP_PGDATABASE`, `BACKUP_PGUSER`, `BACKUP_PGPASSWORD`, `BACKUP_AGE_RECIPIENT`, `BACKUP_AGE_IDENTITY_FILE`, `R2_ENDPOINT`, `R2_BUCKET`, `R2_ACCESS_KEY_ID`, and `R2_SECRET_ACCESS_KEY`. `BACKUP_PGSSLROOTCERT` is optional when the system trust store cannot validate the Supabase certificate. `R2_PREFIX` defaults to `supabase-backups`; `R2_AWS_REGION` defaults to R2's `auto`.

The backup identity is needed only because the job performs a local authenticated decrypt/archive check. Store it as an owner-only (`0600`) secret; keep a separate offline recovery copy. The public age recipient is safe to distribute. Run the backup daily through a systemd timer or CI scheduler, capture stderr/exit status, and alert on any non-zero exit or on no successful backup in 26 hours. The script removes only its own generated R2 objects older than seven UTC days.

R2 is usage-metered. Its free allowance and pricing can change; budget for storage, operations, egress, and retention rather than assuming zero cost. Set a Cloudflare usage/billing alert and periodically check bucket lifecycle/usage. Seven-day retention is operational convenience, not a compliance retention policy.

## Restore drill

The drill has no production path and never reads `RESTORE_PG*`, `PRODUCTION_PG*`, `PG*`, service-file, or caller-supplied connection settings. Its only database identity is an exact target ID selected from the fixed root-managed directory `/etc/whatsapp-ai-responder/backup-drill-targets`. The parent directory and target directory must be owned by root and not group/world writable; each target file must be a root-owned, owner-only regular file, not a symlink. The path itself is canonicalized and may not be redirected.

An administrator creates one file per approved target, for example `/etc/whatsapp-ai-responder/backup-drill-targets/drill-eu1.conf` (mode `0600`, root-owned):

```ini
TARGET_ID=drill-eu1
TARGET_ENV=drill
PGHOST=db.drill-project.supabase.co
PGPORT=5432
PGDATABASE=postgres
PGUSER=backup_drill_restore
PGPASSWORD=injected-only-into-this-root-owned-file
# Optional, root-owned mode 0600 certificate path:
# PGSSLROOTCERT=/etc/whatsapp-ai-responder/supabase-ca.pem
```

Only `development`, `test`, `staging`, and `drill` target labels are accepted. A `prod` substring rejection remains a supplemental tripwire, not authorization: the root-managed exact allowlist is the authorization boundary. Do not add production endpoints, database names, or credentials to this directory.

The runtime identity must have read access only to this non-production target configuration and no production database secret, network route, DNS override, cloud IAM role, or security-group/e-gress rule that can reach production. Use a dedicated non-production restore role, distinct projects/accounts, and network policy that denies production database endpoints. Keep the production backup and deployment roles separate from the drill host/service account.

The caller supplies the same R2 variables as backup, `BACKUP_AGE_IDENTITY_FILE` (owner-only), and an explicit `RESTORE_NON_PRODUCTION_CONFIRMATION=RESTORE_<target-id>`. Example:

```bash
RESTORE_NON_PRODUCTION_CONFIRMATION=RESTORE_drill-eu1 \
scripts/restore_supabase_drill.sh --target drill-eu1 \
  --artifact-key supabase-backups/supabase-20260920T010203Z-12345.dump.age
```

The drill downloads the artifact and manifest, checks their binding and SHA-256 digest, authenticates/decrypts with age, verifies the PostgreSQL archive, restores in one transaction, then requires non-empty public tables and constraints plus at least one analyzed user-table row (`RESTORE_MINIMUM_ROWS` can raise that threshold). It is destructive to the named non-production database. Do not point it at a shared staging database without a maintenance window; use an isolated drill project/database instead. This is not point-in-time recovery, does not back up Supabase Auth/Storage/configuration outside PostgreSQL, and cannot recover data newer than the latest successful dump.
