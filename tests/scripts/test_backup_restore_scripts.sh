#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(/usr/bin/dirname "$0")/../.." && pwd)
clean_path=/usr/bin:/bin
tmp=$(/usr/bin/mktemp -d)
trap '/usr/bin/rm -rf -- "$tmp"' EXIT

expect_fail() {
  local expected=$1; shift
  local output
  if output=$("$@" 2>&1); then
    printf 'expected failure: %s\n' "$*" >&2; return 1
  fi
  [[ "$output" == *"$expected"* ]] || { printf 'missing %q in: %s\n' "$expected" "$output" >&2; return 1; }
}

expect_fail 'BACKUP_PGHOST is required' /usr/bin/env -i PATH="$clean_path" HOME="${HOME:-/tmp}" /usr/bin/bash "$root/scripts/backup_supabase_r2.sh"

# Test a copied script with a test-only rewritten compile-time root. Production
# code has no config-root override; these cases make no provider calls.
config_root="$tmp/backup-drill-targets"
/usr/bin/mkdir -p "$config_root"
/usr/bin/chmod 700 "$tmp" "$config_root"
test_restore="$tmp/restore.sh"
/usr/bin/sed \
  -e "s|^readonly TARGET_CONFIG_ROOT=.*|readonly TARGET_CONFIG_ROOT=\"$config_root\"|" \
  -e "s|^readonly TARGET_CONFIG_OWNER_UID=.*|readonly TARGET_CONFIG_OWNER_UID=$(/usr/bin/id -u)|" \
  "$root/scripts/restore_supabase_drill.sh" > "$test_restore"
/usr/bin/chmod 700 "$test_restore"

write_config() {
  /usr/bin/printf '%s\n' \
    'TARGET_ID=drill-safe' 'TARGET_ENV=drill' 'PGHOST=db.drill.example' 'PGPORT=5432' \
    'PGDATABASE=drill_db' 'PGUSER=drill_restore' 'PGPASSWORD=not-a-real-secret' \
    > "$config_root/drill-safe.conf"
  /usr/bin/chmod 600 "$config_root/drill-safe.conf"
}

# Caller-provided production labels/credentials cannot make an unlisted target
# runnable: the fixed allowlist path is consulted before tools/providers.
expect_fail 'requested target is not allowlisted' /usr/bin/env -i PATH="$clean_path" HOME="${HOME:-/tmp}" \
  RESTORE_NON_PRODUCTION_CONFIRMATION=RESTORE_attacker RESTORE_TARGET_ENV=drill \
  RESTORE_PGHOST=prod-hidden.example RESTORE_PGDATABASE=live PGHOST=prod-hidden.example PGPASSWORD=production \
  /usr/bin/bash "$test_restore" --target attacker --artifact-key supabase-backups/supabase-20260920T010203Z-1.dump.age

write_config
expect_fail 'BACKUP_AGE_IDENTITY_FILE is required' /usr/bin/env -i PATH="$clean_path" HOME="${HOME:-/tmp}" \
  RESTORE_NON_PRODUCTION_CONFIRMATION=RESTORE_drill-safe PGHOST=prod-hidden.example PGPASSWORD=production \
  /usr/bin/bash "$test_restore" --target drill-safe --artifact-key supabase-backups/supabase-20260920T010203Z-1.dump.age

fake_bin="$tmp/fake-bin"
/usr/bin/mkdir "$fake_bin"
/usr/bin/printf '%s\n' '#!/usr/bin/env bash' \
  'if [[ "$1" == "-c" && "$2" == "%a" && "$3" == *drill-safe.conf ]]; then printf "644\\n"; else exec /usr/bin/stat "$@"; fi' \
  > "$fake_bin/stat"
/usr/bin/chmod 700 "$fake_bin/stat"
expect_fail 'target configuration must be owner-only' /usr/bin/env -i PATH="$fake_bin:$clean_path" HOME="${HOME:-/tmp}" \
  RESTORE_NON_PRODUCTION_CONFIRMATION=RESTORE_drill-safe \
  /usr/bin/bash "$test_restore" --target drill-safe --artifact-key supabase-backups/supabase-20260920T010203Z-1.dump.age

write_config
/usr/bin/sed -i 's/^TARGET_ENV=drill$/TARGET_ENV=production/' "$config_root/drill-safe.conf"
expect_fail 'target configuration is not marked non-production' /usr/bin/env -i PATH="$clean_path" HOME="${HOME:-/tmp}" \
  RESTORE_NON_PRODUCTION_CONFIRMATION=RESTORE_drill-safe \
  /usr/bin/bash "$test_restore" --target drill-safe --artifact-key supabase-backups/supabase-20260920T010203Z-1.dump.age
printf 'backup/restore script guard tests passed\n'
