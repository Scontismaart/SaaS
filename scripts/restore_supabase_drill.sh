#!/usr/bin/env bash
# Restore a verified backup into an explicitly named non-production drill target.
set -euo pipefail
IFS=$'\n\t'
umask 077

work_dir=""
die() { printf 'restore-drill: %s\n' "$*" >&2; exit 1; }
require_env() { [[ -n "${!1:-}" ]] || die "$1 is required"; }
require_command() { command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"; }
cleanup() { [[ -z "$work_dir" ]] || rm -rf -- "$work_dir"; }
trap cleanup EXIT HUP INT TERM

[[ $# -eq 2 && "$1" == "--artifact-key" ]] || die "usage: $0 --artifact-key <R2 artifact key>"
artifact_key="$2"

# This guard is evaluated before providers or local files are touched.  A caller
# must intentionally label the target and prove it differs from production.
require_env RESTORE_TARGET_ENV
case "$RESTORE_TARGET_ENV" in development|test|staging|drill) ;; *) die "RESTORE_TARGET_ENV must be development, test, staging, or drill" ;; esac
[[ "${RESTORE_NON_PRODUCTION_CONFIRMATION:-}" == "RESTORE_${RESTORE_TARGET_ENV}" ]] \
  || die "set RESTORE_NON_PRODUCTION_CONFIRMATION=RESTORE_${RESTORE_TARGET_ENV}"
for name in RESTORE_PGHOST RESTORE_PGPORT RESTORE_PGDATABASE RESTORE_PGUSER RESTORE_PGPASSWORD \
  PRODUCTION_PGHOST PRODUCTION_PGDATABASE BACKUP_AGE_IDENTITY_FILE R2_ENDPOINT R2_BUCKET \
  R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY; do require_env "$name"; done
[[ "$RESTORE_PGHOST" != "$PRODUCTION_PGHOST" ]] || die "restore host matches production host"
[[ "$RESTORE_PGDATABASE" != "$PRODUCTION_PGDATABASE" ]] || die "restore database matches production database"
[[ "${RESTORE_PGHOST,,}" != *prod* && "${RESTORE_PGDATABASE,,}" != *prod* ]] \
  || die "restore host/database must not contain 'prod'"
[[ "${RESTORE_PGSSLMODE:-verify-full}" == "verify-full" ]] || die "RESTORE_PGSSLMODE must be verify-full"
[[ "$R2_ENDPOINT" =~ ^https:// ]] || die "R2_ENDPOINT must be an HTTPS URL"
[[ -r "$BACKUP_AGE_IDENTITY_FILE" ]] || die "BACKUP_AGE_IDENTITY_FILE is not readable"
identity_mode=$(stat -c '%a' "$BACKUP_AGE_IDENTITY_FILE")
(( (8#$identity_mode & 077) == 0 )) || die "BACKUP_AGE_IDENTITY_FILE must not be group/world readable"

prefix="${R2_PREFIX:-supabase-backups}"; prefix="${prefix#/}"; prefix="${prefix%/}"
artifact_base=${artifact_key##*/}
[[ "$artifact_key" == "$prefix/$artifact_base" ]] || die "artifact key must not contain nested paths"
[[ "$artifact_base" =~ ^supabase-[0-9]{8}T[0-9]{6}Z-[0-9]+\.dump\.age$ ]] \
  || die "artifact key is outside the backup prefix or has an invalid name"
[[ "$artifact_key" != *$'\n'* && "$artifact_key" != *$'\r'* ]] || die "invalid artifact key"

require_command aws; require_command age; require_command pg_restore; require_command psql; require_command sha256sum; require_command stat
export AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" AWS_EC2_METADATA_DISABLED=true
export AWS_DEFAULT_REGION="${R2_AWS_REGION:-auto}"
export PGHOST="$RESTORE_PGHOST" PGPORT="$RESTORE_PGPORT" PGDATABASE="$RESTORE_PGDATABASE" PGUSER="$RESTORE_PGUSER" PGPASSWORD="$RESTORE_PGPASSWORD" PGSSLMODE=verify-full
[[ -z "${RESTORE_PGSSLROOTCERT:-}" ]] || export PGSSLROOTCERT="$RESTORE_PGSSLROOTCERT"

work_dir=$(mktemp -d "${TMPDIR:-/tmp}/supabase-r2-restore.XXXXXX"); chmod 700 "$work_dir"
encrypted="$work_dir/$artifact_base"; manifest="$work_dir/manifest.sha256"; dump_file="$work_dir/database.dump"
aws --endpoint-url "$R2_ENDPOINT" s3 cp "s3://$R2_BUCKET/$artifact_key" "$encrypted" --no-progress >/dev/null
aws --endpoint-url "$R2_ENDPOINT" s3 cp "s3://$R2_BUCKET/$artifact_key.sha256" "$manifest" --no-progress >/dev/null

expected_line=$(cat "$manifest")
[[ "$expected_line" =~ ^[a-fA-F0-9]{64}\ \ "$artifact_base"$ ]] || die "manifest format or artifact binding is invalid"
actual_sha=$(sha256sum "$encrypted" | awk '{print $1}')
[[ "$actual_sha" == "${expected_line%% *}" ]] || die "artifact checksum does not match manifest"
age --decrypt --identity "$BACKUP_AGE_IDENTITY_FILE" --output "$dump_file" "$encrypted"
pg_restore --list "$dump_file" >/dev/null

# --clean is intentionally restricted by the guards above; no production route exists.
pg_restore --dbname "$PGDATABASE" --clean --if-exists --no-owner --no-privileges --exit-on-error --single-transaction "$dump_file"
table_count=$(psql -X -v ON_ERROR_STOP=1 -Atqc "SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname = 'public';")
constraint_count=$(psql -X -v ON_ERROR_STOP=1 -Atqc "SELECT count(*) FROM pg_constraint WHERE contype IN ('p', 'f', 'u', 'c');")
minimum_rows="${RESTORE_MINIMUM_ROWS:-1}"
[[ "$minimum_rows" =~ ^[0-9]+$ ]] || die "RESTORE_MINIMUM_ROWS must be a non-negative integer"
data_rows=$(psql -X -v ON_ERROR_STOP=1 -Atqc "ANALYZE; SELECT COALESCE(sum(n_live_tup), 0)::bigint FROM pg_stat_user_tables;")
[[ "$table_count" =~ ^[1-9][0-9]*$ ]] || die "integrity check failed: no public tables restored"
[[ "$constraint_count" =~ ^[1-9][0-9]*$ ]] || die "integrity check failed: no constraints restored"
[[ "$data_rows" =~ ^[0-9]+$ && "$data_rows" -ge "$minimum_rows" ]] \
  || die "integrity check failed: restored rows are below RESTORE_MINIMUM_ROWS"
printf 'restore-drill: verified restore completed for non-production target (%s); tables=%s constraints=%s rows=%s\n' "$RESTORE_TARGET_ENV" "$table_count" "$constraint_count" "$data_rows"
