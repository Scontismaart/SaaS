#!/usr/bin/env bash
# Offline/static guard tests: no package download, root access, Docker, UFW or cloud call.
set -euo pipefail
root=$(cd "$(/usr/bin/dirname "$0")/../.." && pwd)
script="$root/scripts/bootstrap_oracle_vm.sh"
doc="$root/docs/operations/oracle_vm_bootstrap.md"
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

/usr/bin/bash -n "$script"
expect_fail '--admin-cidr is required' /usr/bin/bash "$script"
expect_fail '--temp-host is required' /usr/bin/bash "$script" --admin-cidr 203.0.113.8/32
expect_fail '--ssh-authorized-key-file is required' /usr/bin/bash "$script" --admin-cidr 203.0.113.8/32 --temp-host temp.example.net

extract_function() {
  /usr/bin/sed -n "/^$1() {/,/^}$/p" "$script"
}

# Exercise the real firewall predicate against mocked UFW output only. Nothing
# invokes configure_firewall, UFW, Docker, or a privileged host operation.
fake_bin="$tmp/fake-bin"
/usr/bin/mkdir "$fake_bin"
/usr/bin/printf '%s\n' '#!/usr/bin/env bash' 'printf "%s\\n" "$UFW_FIXTURE"' > "$fake_bin/ufw"
/usr/bin/chmod 700 "$fake_bin/ufw"
firewall_lib="$tmp/firewall-lib.sh"
{
  extract_function firewall_status
  extract_function firewall_ipv6_enabled
  extract_function firewall_inbound_rules
  extract_function firewall_expected_inbound_rules
  extract_function firewall_is_exact
} > "$firewall_lib"

admin_cidr=203.0.113.8/32
UFW_DEFAULTS="$tmp/ufw-defaults"
/usr/bin/printf '%s\n' 'IPV6=yes' > "$UFW_DEFAULTS"
export UFW_FIXTURE
PATH="$fake_bin:/usr/bin:/bin"
# shellcheck disable=SC1090
. "$firewall_lib"
UFW_FIXTURE=$'Status: active\nTo                         Action      From\n--                         ------      ----\n22/tcp                     ALLOW IN    203.0.113.8/32\n80/tcp                     ALLOW IN    Anywhere\n443/tcp                    ALLOW IN    Anywhere\n22/tcp (v6)                ALLOW IN    2001:db8::/64\n80/tcp (v6)                ALLOW IN    Anywhere (v6)\n443/tcp (v6)               ALLOW IN    Anywhere (v6)\nDefault: deny (incoming), allow (outgoing), disabled (routed)'
if firewall_is_exact; then
  printf 'unexpectedly accepted a second SSH CIDR\n' >&2; exit 1
fi
UFW_FIXTURE=$'Status: active\nTo                         Action      From\n--                         ------      ----\n22/tcp                     ALLOW IN    203.0.113.8/32\n80/tcp                     ALLOW IN    Anywhere\n443/tcp                    ALLOW IN    Anywhere\n80/tcp (v6)                ALLOW IN    Anywhere (v6)\n443/tcp (v6)               ALLOW IN    Anywhere (v6)\nDefault: allow (incoming), allow (outgoing), disabled (routed)'
if firewall_is_exact; then
  printf 'unexpectedly accepted default incoming allow\n' >&2; exit 1
fi
UFW_FIXTURE=$'Status: active\nTo                         Action      From\n--                         ------      ----\n22/tcp                     ALLOW IN    203.0.113.8/32\n80/tcp                     ALLOW IN    Anywhere\n443/tcp                    ALLOW IN    Anywhere\n80/tcp (v6)                ALLOW IN    Anywhere (v6)\n443/tcp (v6)               ALLOW IN    Anywhere (v6)\nDefault: deny (incoming), allow (outgoing), disabled (routed)'
firewall_is_exact || { printf 'rejected the exact reviewed UFW policy\n' >&2; exit 1; }

# Run the production append/deduplicate/rotation function in a temporary home.
# The fake ownership commands ensure no local account or authorized_keys changes.
/usr/bin/printf '%s\n' '#!/usr/bin/env bash' \
  'set -euo pipefail' 'directory=false; args=()' \
  'while [[ $# -gt 0 ]]; do case "$1" in -d) directory=true; shift ;; -m|-o|-g) shift 2 ;; *) args+=("$1"); shift ;; esac; done' \
  'if "$directory"; then mkdir -p "${args[${#args[@]}-1]}"; else cp "${args[${#args[@]}-2]}" "${args[${#args[@]}-1]}"; fi' \
  > "$fake_bin/install"
/usr/bin/printf '%s\n' '#!/usr/bin/env bash' 'exit 0' > "$fake_bin/chown"
/usr/bin/chmod 700 "$fake_bin/install" "$fake_bin/chown"
key_lib="$tmp/key-lib.sh"
extract_function install_deploy_authorized_key > "$key_lib"
DEPLOY_HOME_ROOT="$tmp/home"
deploy_user=melpis
authorized_key_file="$tmp/new.pub"
replace_authorized_keys=false
/usr/bin/mkdir -p "$DEPLOY_HOME_ROOT/$deploy_user/.ssh"
/usr/bin/printf '%s\n' 'ssh-ed25519 RECOVERY recovery@example.test' > "$DEPLOY_HOME_ROOT/$deploy_user/.ssh/authorized_keys"
/usr/bin/printf '%s\n' 'ssh-ed25519 NEW deploy@example.test' > "$authorized_key_file"
# shellcheck disable=SC1090
. "$key_lib"
install_deploy_authorized_key
/usr/bin/grep -Fxq 'ssh-ed25519 RECOVERY recovery@example.test' "$DEPLOY_HOME_ROOT/$deploy_user/.ssh/authorized_keys"
/usr/bin/grep -Fxq 'ssh-ed25519 NEW deploy@example.test' "$DEPLOY_HOME_ROOT/$deploy_user/.ssh/authorized_keys"
install_deploy_authorized_key
[[ $(/usr/bin/grep -Fxc 'ssh-ed25519 NEW deploy@example.test' "$DEPLOY_HOME_ROOT/$deploy_user/.ssh/authorized_keys") -eq 1 ]]
replace_authorized_keys=true
install_deploy_authorized_key
/usr/bin/cmp -s "$authorized_key_file" "$DEPLOY_HOME_ROOT/$deploy_user/.ssh/authorized_keys"

for required in \
  'download.docker.com/linux/ubuntu' 'docker-compose-plugin' 'usermod -aG docker' \
  '--confirm-ssh-access' '--replace-authorized-keys' 'PermitRootLogin no' 'PasswordAuthentication no' \
  'ufw allow from' 'ufw allow 80/tcp' 'ufw allow 443/tcp' '/etc/cron.d/melpis-backup' \
  '/srv/melpis/app' 'root-owned mode 600' 'firewall_is_exact' 'firewall_has_saved_rules'; do
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
  'SENTRY_DSN' 'independent uptime' 'melpis-backup' 'restore drills' 'does not create an Oracle VM' \
  'Final release evidence gate' 'GitHub Actions' 'final branch code/security' \
  'committed secrets or production data' 'pull request is approved and merged'; do
  /usr/bin/grep -Fqi -- "$required" "$doc" || { printf 'missing runbook control: %s\n' "$required" >&2; exit 1; }
done

printf 'oracle VM bootstrap static tests passed\n'
