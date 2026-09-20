#!/usr/bin/env bash
# Create an encrypted PostgreSQL backup and upload it to Cloudflare R2.
# Intentionally does not enable xtrace: this process receives credentials.
set -euo pipefail
IFS=$'\n\t'
umask 077

readonly RETENTION_DAYS=7
readonly DEFAULT_PREFIX="supabase-backups"
work_dir=""

die() { printf 'backup: %s\n' "$*" >&2; exit 1; }
require_env() { [[ -n "${!1:-}" ]] || die "$1 is required"; }
require_command() { command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"; }
cleanup() { [[ -z "$work_dir" ]] || rm -rf -- "$work_dir"; }
trap cleanup EXIT HUP INT TERM

# Database credentials are deliberately supplied as libpq environment variables,
# never interpolated into a connection string or command-line argument.
for name in BACKUP_PGHOST BACKUP_PGPORT BACKUP_PGDATABASE BACKUP_PGUSER BACKUP_PGPASSWORD \
  BACKUP_AGE_RECIPIENT BACKUP_AGE_IDENTITY_FILE R2_ENDPOINT R2_BUCKET R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY; do
  require_env "$name"
done

[[ "${BACKUP_PGSSLMODE:-verify-full}" == "verify-full" ]] || die "BACKUP_PGSSLMODE must be verify-full"
[[ "$R2_ENDPOINT" =~ ^https:// ]] || die "R2_ENDPOINT must be an HTTPS URL"
[[ "$R2_BUCKET" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]] || die "R2_BUCKET is not a valid bucket name"
[[ "$BACKUP_AGE_RECIPIENT" == age1* ]] || die "BACKUP_AGE_RECIPIENT must be an age recipient"

require_command pg_dump
require_command pg_restore
require_command age
require_command aws
require_command sha256sum
require_command date
require_command stat
[[ -r "$BACKUP_AGE_IDENTITY_FILE" ]] || die "BACKUP_AGE_IDENTITY_FILE is not readable"
identity_mode=$(stat -c '%a' "$BACKUP_AGE_IDENTITY_FILE")
(( (8#$identity_mode & 077) == 0 )) || die "BACKUP_AGE_IDENTITY_FILE must not be group/world readable"

export PGHOST="$BACKUP_PGHOST" PGPORT="$BACKUP_PGPORT" PGDATABASE="$BACKUP_PGDATABASE"
export PGUSER="$BACKUP_PGUSER" PGPASSWORD="$BACKUP_PGPASSWORD"
export PGSSLMODE="verify-full"
[[ -z "${BACKUP_PGSSLROOTCERT:-}" ]] || export PGSSLROOTCERT="$BACKUP_PGSSLROOTCERT"
export AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"
export AWS_EC2_METADATA_DISABLED=true
export AWS_DEFAULT_REGION="${R2_AWS_REGION:-auto}"

prefix="${R2_PREFIX:-$DEFAULT_PREFIX}"
prefix="${prefix#/}"
prefix="${prefix%/}"
[[ "$prefix" =~ ^[A-Za-z0-9._/-]+$ ]] || die "R2_PREFIX contains unsupported characters"

work_dir=$(mktemp -d "${TMPDIR:-/tmp}/supabase-r2-backup.XXXXXX")
chmod 700 "$work_dir"
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
artifact_base="supabase-${timestamp}-${RANDOM}.dump.age"
dump_file="$work_dir/database.dump"
artifact_file="$work_dir/$artifact_base"
manifest_file="$work_dir/$artifact_base.sha256"
artifact_key="$prefix/$artifact_base"
manifest_key="$artifact_key.sha256"

# The custom format supports pg_restore verification and a transactional drill.
pg_dump --format=custom --no-owner --no-privileges --file="$dump_file"
age --encrypt --recipient "$BACKUP_AGE_RECIPIENT" --output "$artifact_file" "$dump_file"
rm -f -- "$dump_file"

# Authenticate/decrypt locally before an external copy is accepted as a backup.
# age returns non-zero for malformed or unauthenticated ciphertext.
age --decrypt --identity "$BACKUP_AGE_IDENTITY_FILE" "$artifact_file" \
  | pg_restore --list >/dev/null 2>&1 || die "encrypted artifact failed local authentication/archive verification"
sha256sum "$artifact_file" | awk -v n="$artifact_base" '{print $1 "  " n}' > "$manifest_file"

aws --endpoint-url "$R2_ENDPOINT" s3api put-object --bucket "$R2_BUCKET" --key "$artifact_key" \
  --body "$artifact_file" --metadata "sha256=$(awk '{print $1}' "$manifest_file")" --no-progress >/dev/null
aws --endpoint-url "$R2_ENDPOINT" s3api put-object --bucket "$R2_BUCKET" --key "$manifest_key" \
  --body "$manifest_file" --content-type text/plain --no-progress >/dev/null

# Confirm R2 stored the complete object and immutable digest metadata.
remote_size=$(aws --endpoint-url "$R2_ENDPOINT" s3api head-object --bucket "$R2_BUCKET" --key "$artifact_key" --query ContentLength --output text)
local_size=$(wc -c < "$artifact_file" | tr -d '[:space:]')
remote_sha=$(aws --endpoint-url "$R2_ENDPOINT" s3api head-object --bucket "$R2_BUCKET" --key "$artifact_key" --query 'Metadata.sha256' --output text)
local_sha=$(awk '{print $1}' "$manifest_file")
[[ "$remote_size" == "$local_size" && "$remote_sha" == "$local_sha" ]] || die "R2 post-upload verification failed"

# Delete only our generated artifact/manifest names older than seven UTC days.
cutoff=$(date -u -d "${RETENTION_DAYS} days ago" +%Y-%m-%dT%H:%M:%SZ)
while IFS= read -r old_key; do
  [[ -z "$old_key" || "$old_key" == "None" ]] && continue
  old_base=${old_key##*/}
  [[ "$old_key" == "$prefix/$old_base" ]] || die "refusing to delete nested R2 key"
  [[ "$old_base" =~ ^supabase-[0-9]{8}T[0-9]{6}Z-[0-9]+\.dump\.age(\.sha256)?$ ]] \
    || die "refusing to delete unexpected R2 key"
  aws --endpoint-url "$R2_ENDPOINT" s3api delete-object --bucket "$R2_BUCKET" --key "$old_key" >/dev/null
done < <(aws --endpoint-url "$R2_ENDPOINT" s3api list-objects-v2 --bucket "$R2_BUCKET" --prefix "$prefix/" \
  --query "Contents[?LastModified<=\`${cutoff}\`].Key" --output text | tr '\t' '\n')

printf 'backup: verified encrypted artifact uploaded: s3://%s/%s\n' "$R2_BUCKET" "$artifact_key"
