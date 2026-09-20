#!/bin/bash
# Restore only into a root-managed, explicitly allowlisted non-production target.
set -euo pipefail
IFS=$'\n\t'
umask 077
export PATH=/usr/bin:/bin

readonly TARGET_CONFIG_ROOT="/etc/whatsapp-ai-responder/backup-drill-targets"
readonly TARGET_CONFIG_OWNER_UID=0
work_dir=""

die() { printf 'restore-drill: %s\n' "$*" >&2; exit 1; }
require_env() { [[ -n "${!1:-}" ]] || die "$1 is required"; }
require_binary() { [[ -x "$1" ]] || die "required trusted binary not found: $1"; }
cleanup() { [[ -z "$work_dir" ]] || /usr/bin/rm -rf -- "$work_dir"; }
trap cleanup EXIT HUP INT TERM

secure_directory() {
  local path=$1 mode owner
  [[ -d "$path" && ! -L "$path" ]] || die "trusted configuration directory is missing or is a symlink"
  owner=$(/usr/bin/stat -c '%u' "$path"); mode=$(/usr/bin/stat -c '%a' "$path")
  [[ "$owner" == "$TARGET_CONFIG_OWNER_UID" ]] || die "trusted configuration directory is not admin-owned"
  (( (8#$mode & 022) == 0 )) || die "trusted configuration directory is group/world writable"
}

secure_secret_file() {
  local path=$1 description=$2 mode owner
  [[ -f "$path" && ! -L "$path" ]] || die "$description is missing or is a symlink"
  owner=$(/usr/bin/stat -c '%u' "$path"); mode=$(/usr/bin/stat -c '%a' "$path")
  [[ "$owner" == "$TARGET_CONFIG_OWNER_UID" ]] || die "$description is not admin-owned"
  (( (8#$mode & 077) == 0 )) || die "$description must be owner-only"
}

load_target_config() {
  local line key value
  declare -A seen=()
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -n "$line" && "$line" != \#* ]] || continue
    [[ "$line" == *=* ]] || die "target configuration contains an invalid line"
    key=${line%%=*}; value=${line#*=}
    [[ "$key" =~ ^(TARGET_ID|TARGET_ENV|PGHOST|PGPORT|PGDATABASE|PGUSER|PGPASSWORD|PGSSLROOTCERT)$ ]] \
      || die "target configuration contains an unsupported key"
    [[ -z "${seen[$key]+x}" ]] || die "target configuration contains a duplicate key"
    [[ -n "$value" && "$value" != *$'\r'* ]] || die "target configuration contains an empty or invalid value"
    seen[$key]=1
    case "$key" in
      TARGET_ID) config_target_id=$value ;; TARGET_ENV) config_target_env=$value ;;
      PGHOST) config_pghost=$value ;; PGPORT) config_pgport=$value ;;
      PGDATABASE) config_pgdatabase=$value ;; PGUSER) config_pguser=$value ;;
      PGPASSWORD) config_pgpassword=$value ;; PGSSLROOTCERT) config_pgsslrootcert=$value ;;
    esac
  done < "$target_config"
  for key in TARGET_ID TARGET_ENV PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD; do
    [[ -n "${seen[$key]+x}" ]] || die "target configuration is missing $key"
  done
  [[ "$config_target_id" == "$target_id" ]] || die "target configuration identifier does not match requested target"
  case "$config_target_env" in development|test|staging|drill) ;; *) die "target configuration is not marked non-production" ;; esac
  [[ "$config_pghost" != *$'\n'* && "$config_pgdatabase" != *$'\n'* ]] || die "target configuration has an invalid database identity"
  # Defense in depth only: exact root-managed allowlisting above is authorization.
  [[ "${config_pghost,,}" != *prod* && "${config_pgdatabase,,}" != *prod* ]] \
    || die "allowlisted target host/database must not contain 'prod'"
  [[ "$config_pgport" =~ ^[0-9]{1,5}$ && "$config_pgport" -ge 1 && "$config_pgport" -le 65535 ]] \
    || die "target configuration has an invalid PGPORT"
}

[[ $# -eq 4 && "$1" == "--target" && "$3" == "--artifact-key" ]] \
  || die "usage: $0 --target <approved-target-id> --artifact-key <R2 artifact key>"
target_id="$2"; artifact_key="$4"
[[ "$target_id" =~ ^[a-z0-9][a-z0-9-]{0,62}$ ]] || die "target id is invalid"
[[ "${RESTORE_NON_PRODUCTION_CONFIRMATION:-}" == "RESTORE_${target_id}" ]] \
  || die "set RESTORE_NON_PRODUCTION_CONFIRMATION=RESTORE_${target_id}"

require_binary /usr/bin/stat; require_binary /usr/bin/readlink
config_root=$(/usr/bin/readlink -f -- "$TARGET_CONFIG_ROOT") || die "trusted configuration directory is missing"
[[ "$config_root" == "$TARGET_CONFIG_ROOT" ]] || die "trusted configuration directory must not be redirected"
secure_directory "${TARGET_CONFIG_ROOT%/*}"
secure_directory "$config_root"
target_config="$config_root/$target_id.conf"
[[ -e "$target_config" ]] || die "requested target is not allowlisted"
canonical_config=$(/usr/bin/readlink -f -- "$target_config") || die "requested target is not allowlisted"
[[ "$canonical_config" == "$target_config" ]] || die "target configuration must not be redirected"
secure_secret_file "$target_config" "target configuration"
load_target_config

require_env BACKUP_AGE_IDENTITY_FILE; require_env R2_ENDPOINT; require_env R2_BUCKET
require_env R2_ACCESS_KEY_ID; require_env R2_SECRET_ACCESS_KEY
[[ "$R2_ENDPOINT" =~ ^https:// ]] || die "R2_ENDPOINT must be an HTTPS URL"
[[ -r "$BACKUP_AGE_IDENTITY_FILE" ]] || die "BACKUP_AGE_IDENTITY_FILE is not readable"
identity_mode=$(/usr/bin/stat -c '%a' "$BACKUP_AGE_IDENTITY_FILE")
(( (8#$identity_mode & 077) == 0 )) || die "BACKUP_AGE_IDENTITY_FILE must not be group/world readable"
[[ -z "${config_pgsslrootcert:-}" ]] || secure_secret_file "$config_pgsslrootcert" "target TLS root certificate"

prefix="${R2_PREFIX:-supabase-backups}"; prefix="${prefix#/}"; prefix="${prefix%/}"
artifact_base=${artifact_key##*/}
[[ "$artifact_key" == "$prefix/$artifact_base" ]] || die "artifact key must not contain nested paths"
[[ "$artifact_base" =~ ^supabase-[0-9]{8}T[0-9]{6}Z-[0-9]+\.dump\.age$ ]] \
  || die "artifact key is outside the backup prefix or has an invalid name"
[[ "$artifact_key" != *$'\n'* && "$artifact_key" != *$'\r'* ]] || die "invalid artifact key"

require_binary /usr/bin/aws; require_binary /usr/bin/age; require_binary /usr/bin/pg_restore
require_binary /usr/bin/psql; require_binary /usr/bin/sha256sum; require_binary /usr/bin/awk
require_binary /usr/bin/mktemp; require_binary /usr/bin/chmod
export AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" AWS_EC2_METADATA_DISABLED=true
export AWS_DEFAULT_REGION="${R2_AWS_REGION:-auto}"
# Ignore every caller-controlled libpq target setting; only the root-owned file
# above supplies database identity and credentials.
unset PGHOST PGHOSTADDR PGPORT PGDATABASE PGUSER PGPASSWORD PGSSLMODE PGSSLROOTCERT \
  PGSERVICE PGSERVICEFILE PGPASSFILE PGOPTIONS PGTARGETSESSIONATTRS PGREQUIRESSL
export PGHOST="$config_pghost" PGPORT="$config_pgport" PGDATABASE="$config_pgdatabase"
export PGUSER="$config_pguser" PGPASSWORD="$config_pgpassword" PGSSLMODE=verify-full
[[ -z "${config_pgsslrootcert:-}" ]] || export PGSSLROOTCERT="$config_pgsslrootcert"

work_dir=$(/usr/bin/mktemp -d "/var/tmp/supabase-r2-restore.XXXXXX"); /usr/bin/chmod 700 "$work_dir"
encrypted="$work_dir/$artifact_base"; manifest="$work_dir/manifest.sha256"; dump_file="$work_dir/database.dump"
/usr/bin/aws --endpoint-url "$R2_ENDPOINT" s3 cp "s3://$R2_BUCKET/$artifact_key" "$encrypted" --no-progress >/dev/null
/usr/bin/aws --endpoint-url "$R2_ENDPOINT" s3 cp "s3://$R2_BUCKET/$artifact_key.sha256" "$manifest" --no-progress >/dev/null

expected_line=$(<"$manifest")
[[ "$expected_line" =~ ^[a-fA-F0-9]{64}\ \ "$artifact_base"$ ]] || die "manifest format or artifact binding is invalid"
actual_sha=$(/usr/bin/sha256sum "$encrypted" | /usr/bin/awk '{print $1}')
[[ "$actual_sha" == "${expected_line%% *}" ]] || die "artifact checksum does not match manifest"
/usr/bin/age --decrypt --identity "$BACKUP_AGE_IDENTITY_FILE" --output "$dump_file" "$encrypted"
/usr/bin/pg_restore --list "$dump_file" >/dev/null

/usr/bin/pg_restore --dbname "$PGDATABASE" --clean --if-exists --no-owner --no-privileges --exit-on-error --single-transaction "$dump_file"
table_count=$(/usr/bin/psql -X -v ON_ERROR_STOP=1 -Atqc "SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname = 'public';")
constraint_count=$(/usr/bin/psql -X -v ON_ERROR_STOP=1 -Atqc "SELECT count(*) FROM pg_constraint WHERE contype IN ('p', 'f', 'u', 'c');")
minimum_rows="${RESTORE_MINIMUM_ROWS:-1}"
[[ "$minimum_rows" =~ ^[0-9]+$ ]] || die "RESTORE_MINIMUM_ROWS must be a non-negative integer"
data_rows=$(/usr/bin/psql -X -v ON_ERROR_STOP=1 -Atqc "ANALYZE; SELECT COALESCE(sum(n_live_tup), 0)::bigint FROM pg_stat_user_tables;")
[[ "$table_count" =~ ^[1-9][0-9]*$ ]] || die "integrity check failed: no public tables restored"
[[ "$constraint_count" =~ ^[1-9][0-9]*$ ]] || die "integrity check failed: no constraints restored"
[[ "$data_rows" =~ ^[0-9]+$ && "$data_rows" -ge "$minimum_rows" ]] \
  || die "integrity check failed: restored rows are below RESTORE_MINIMUM_ROWS"
printf 'restore-drill: verified restore completed for allowlisted %s target (%s); tables=%s constraints=%s rows=%s\n' "$config_target_env" "$target_id" "$table_count" "$constraint_count" "$data_rows"
