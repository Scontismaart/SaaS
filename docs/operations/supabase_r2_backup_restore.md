# Encrypted Supabase backup and restore drill

`scripts/backup_supabase_r2.sh` creates a PostgreSQL custom-format dump over TLS, encrypts it locally with [age](https://age-encryption.org/) authenticated encryption, verifies the decrypted archive, and uploads the encrypted artifact plus SHA-256 manifest to Cloudflare R2. It never accepts `sslmode=require`: database TLS must use `verify-full`.

Install on Ubuntu 24.04: `sudo apt-get install postgresql-client age awscli coreutils`. Use a dedicated R2 API token scoped only to the backup bucket (read/write/list/delete); do not use an account-wide token. Inject all values with the host or CI secret manager, never a committed `.env` file.

Required backup variables: `BACKUP_PGHOST`, `BACKUP_PGPORT`, `BACKUP_PGDATABASE`, `BACKUP_PGUSER`, `BACKUP_PGPASSWORD`, `BACKUP_AGE_RECIPIENT`, `BACKUP_AGE_IDENTITY_FILE`, `R2_ENDPOINT`, `R2_BUCKET`, `R2_ACCESS_KEY_ID`, and `R2_SECRET_ACCESS_KEY`. `BACKUP_PGSSLROOTCERT` is optional when the system trust store cannot validate the Supabase certificate. `R2_PREFIX` defaults to `supabase-backups`; `R2_AWS_REGION` defaults to R2's `auto`.

The backup identity is needed only because the job performs a local authenticated decrypt/archive check. Store it as an owner-only (`0600`) secret; keep a separate offline recovery copy. The public age recipient is safe to distribute. Run the backup daily through a systemd timer or CI scheduler, capture stderr/exit status, and alert on any non-zero exit or on no successful backup in 26 hours. The script removes only its own generated R2 objects older than seven UTC days.

R2 is usage-metered. Its free allowance and pricing can change; budget for storage, operations, egress, and retention rather than assuming zero cost. Set a Cloudflare usage/billing alert and periodically check bucket lifecycle/usage. Seven-day retention is operational convenience, not a compliance retention policy.

## Restore drill

The drill has no production path. It requires all of the following: `RESTORE_TARGET_ENV` equal to `development`, `test`, `staging`, or `drill`; `RESTORE_NON_PRODUCTION_CONFIRMATION=RESTORE_<environment>`; and values for `PRODUCTION_PGHOST` and `PRODUCTION_PGDATABASE` that are both different from the restore host/database. It also requires the restore `RESTORE_PG*` variables, the same R2 variables, and `BACKUP_AGE_IDENTITY_FILE` (owner-only).

Example, after injecting secrets into the environment:

```bash
RESTORE_TARGET_ENV=drill \
RESTORE_NON_PRODUCTION_CONFIRMATION=RESTORE_drill \
scripts/restore_supabase_drill.sh --artifact-key supabase-backups/supabase-20260920T010203Z-12345.dump.age
```

The drill downloads the artifact and manifest, checks their binding and SHA-256 digest, authenticates/decrypts with age, verifies the PostgreSQL archive, restores in one transaction, then requires non-empty public tables and constraints plus at least one analyzed user-table row (`RESTORE_MINIMUM_ROWS` can raise that threshold). It rejects any target host or database containing `prod`. It is destructive to the named non-production database. Do not point it at a shared staging database without a maintenance window; use an isolated drill project/database instead. This is not point-in-time recovery, does not back up Supabase Auth/Storage/configuration outside PostgreSQL, and cannot recover data newer than the latest successful dump.
