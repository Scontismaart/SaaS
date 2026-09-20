#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(/usr/bin/dirname "$0")/../.." && pwd)
clean_path=/usr/bin:/bin

expect_fail() {
  local expected=$1; shift
  local output
  if output=$("$@" 2>&1); then
    printf 'expected failure: %s\n' "$*" >&2; return 1
  fi
  [[ "$output" == *"$expected"* ]] || { printf 'missing %q in: %s\n' "$expected" "$output" >&2; return 1; }
}

expect_fail 'BACKUP_PGHOST is required' /usr/bin/env -i PATH="$clean_path" HOME="${HOME:-/tmp}" /usr/bin/bash "$root/scripts/backup_supabase_r2.sh"
expect_fail 'RESTORE_TARGET_ENV must be development, test, staging, or drill' \
  /usr/bin/env -i PATH="$clean_path" HOME="${HOME:-/tmp}" RESTORE_TARGET_ENV=production \
  /usr/bin/bash "$root/scripts/restore_supabase_drill.sh" --artifact-key supabase-backups/supabase-20260920T010203Z-1.dump.age
expect_fail 'set RESTORE_NON_PRODUCTION_CONFIRMATION=RESTORE_drill' \
  /usr/bin/env -i PATH="$clean_path" HOME="${HOME:-/tmp}" RESTORE_TARGET_ENV=drill \
  /usr/bin/bash "$root/scripts/restore_supabase_drill.sh" --artifact-key supabase-backups/supabase-20260920T010203Z-1.dump.age
printf 'backup/restore script guard tests passed\n'
