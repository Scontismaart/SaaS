#!/usr/bin/env bash
# Offline/static guard tests: no package download, root access, Docker, UFW or cloud call.
set -euo pipefail
root=$(cd "$(/usr/bin/dirname "$0")/../.." && pwd)
script="$root/scripts/bootstrap_oracle_vm.sh"
doc="$root/docs/operations/oracle_vm_bootstrap.md"

expect_fail() {
  local expected=$1; shift
  local output
  if output=$("$@" 2>&1); then
    printf 'expected failure: %s\n' "$*" >&2; return 1
  fi
  [[ "$output" == *"$expected"* ]] || { printf 'missing %q in: %s\n' "$expected" "$output" >&2; return 1; }
}

/usr/bin/bash -n "$script"
expect_fail '--admin-cidr is required' /usr/bin/bash "$script"
expect_fail '--temp-host is required' /usr/bin/bash "$script" --admin-cidr 203.0.113.8/32
expect_fail '--ssh-authorized-key-file is required' /usr/bin/bash "$script" --admin-cidr 203.0.113.8/32 --temp-host temp.example.net

for required in \
  'download.docker.com/linux/ubuntu' 'docker-compose-plugin' 'usermod -aG docker' \
  '--confirm-ssh-access' 'PermitRootLogin no' 'PasswordAuthentication no' \
  'ufw allow from' 'ufw allow 80/tcp' 'ufw allow 443/tcp' '/etc/cron.d/melpis-backup' \
  '/srv/melpis/app' 'root-owned mode 600'; do
  /usr/bin/grep -Fq -- "$required" "$script" || { printf 'missing bootstrap control: %s\n' "$required" >&2; exit 1; }
done

for forbidden in 'curl -fsSL https://get.docker.com | sh' 'ufw reset' 'ufw allow 22/tcp'; do
  if /usr/bin/grep -Fq -- "$forbidden" "$script"; then
    printf 'unsafe bootstrap pattern present: %s\n' "$forbidden" >&2; exit 1
  fi
done

for required in \
  'Oracle network security group or security list' 'temporary-host deployment' \
  'app.melpis.it' 'https://melpis.it/app/' 'api/health/live' 'api/health/ready' \
  'SENTRY_DSN' 'independent uptime' 'melpis-backup' 'restore drills' 'does not create an Oracle VM'; do
  /usr/bin/grep -Fqi -- "$required" "$doc" || { printf 'missing runbook control: %s\n' "$required" >&2; exit 1; }
done

printf 'oracle VM bootstrap static tests passed\n'
