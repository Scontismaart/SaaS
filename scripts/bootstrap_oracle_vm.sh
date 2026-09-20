#!/usr/bin/env bash
# Bootstrap a single Ubuntu 24.04 VM for a reviewed Melpis release.
# This script deliberately does not accept or create application credentials.
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

readonly APP_ROOT=/srv/melpis
readonly SECRET_ROOT=/etc/whatsapp-ai-responder
readonly DOCKER_KEYRING=/etc/apt/keyrings/docker.asc
readonly DOCKER_SOURCE=/etc/apt/sources.list.d/docker.list

die() { printf 'bootstrap: %s\n' "$*" >&2; exit 1; }
note() { printf 'bootstrap: %s\n' "$*"; }

usage() {
  cat <<'USAGE'
Usage: bootstrap_oracle_vm.sh --admin-cidr <IPv4-or-IPv6-CIDR> --temp-host <FQDN>
       --ssh-authorized-key-file <public-key-file> [options]

Required:
  --admin-cidr CIDR              Only CIDR permitted to SSH after firewall apply.
  --temp-host FQDN               A DNS hostname you control for pre-domain TLS.
  --ssh-authorized-key-file PATH Public key installed for the deployment account.

Options:
  --deploy-user NAME             Deployment account (default: melpis).
  --swap-gib N                   /swapfile size in GiB, 1..16 (default: 2).
  --apply-firewall               Apply UFW rules (requires the confirmation below).
  --apply-ssh-hardening          Disable root/password SSH (requires confirmation).
  --confirm-ssh-access           Attest a second SSH login as the deployment user works.
  --help                         Show this help.

The first safe run installs Docker, creates directories and installs the public
key. Test a second login, then rerun with --confirm-ssh-access and the desired
hardening flags. No application images, secrets, cloud resources or DNS records
are created by this script.
USAGE
}

admin_cidr=""
temp_host=""
authorized_key_file=""
deploy_user=melpis
swap_gib=2
apply_firewall=false
apply_ssh_hardening=false
confirm_ssh_access=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --admin-cidr) [[ $# -ge 2 ]] || die '--admin-cidr needs a value'; admin_cidr=$2; shift 2 ;;
    --temp-host) [[ $# -ge 2 ]] || die '--temp-host needs a value'; temp_host=$2; shift 2 ;;
    --ssh-authorized-key-file) [[ $# -ge 2 ]] || die '--ssh-authorized-key-file needs a value'; authorized_key_file=$2; shift 2 ;;
    --deploy-user) [[ $# -ge 2 ]] || die '--deploy-user needs a value'; deploy_user=$2; shift 2 ;;
    --swap-gib) [[ $# -ge 2 ]] || die '--swap-gib needs a value'; swap_gib=$2; shift 2 ;;
    --apply-firewall) apply_firewall=true; shift ;;
    --apply-ssh-hardening) apply_ssh_hardening=true; shift ;;
    --confirm-ssh-access) confirm_ssh_access=true; shift ;;
    --help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[[ -n "$admin_cidr" ]] || die '--admin-cidr is required; refusing to leave SSH unrestricted'
[[ -n "$temp_host" ]] || die '--temp-host is required; refusing to guess a TLS hostname'
[[ -n "$authorized_key_file" ]] || die '--ssh-authorized-key-file is required; refusing to create an inaccessible deployment account'
[[ "$deploy_user" =~ ^[a-z_][a-z0-9_-]{0,31}$ && "$deploy_user" != root ]] || die 'deploy user is invalid'
[[ "$swap_gib" =~ ^[0-9]+$ && "$swap_gib" -ge 1 && "$swap_gib" -le 16 ]] || die '--swap-gib must be an integer from 1 to 16'

# python3 ships with Ubuntu 24.04. Use ipaddress instead of guessing CIDR syntax.
command -v python3 >/dev/null 2>&1 || die 'python3 is required to validate --admin-cidr'
python3 - "$admin_cidr" <<'PY' || die '--admin-cidr must be one explicit IPv4 or IPv6 CIDR'
import ipaddress
import sys
ipaddress.ip_network(sys.argv[1], strict=False)
PY

temp_host=${temp_host,,}
[[ "$temp_host" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$ ]] \
  || die '--temp-host must be a DNS FQDN, not a URL, IP address, wildcard, or placeholder'
[[ "$temp_host" != melpis.it && "$temp_host" != app.melpis.it ]] \
  || die '--temp-host must be a temporary hostname; use the final-domain procedure later'

[[ $EUID -eq 0 ]] || die 'run as root via sudo on the target VM'
[[ -r /etc/os-release ]] || die 'cannot identify operating system'
# shellcheck disable=SC1091
. /etc/os-release
[[ "${ID:-}" == ubuntu && "${VERSION_ID:-}" == 24.04 ]] || die 'this bootstrap supports Ubuntu 24.04 only'

architecture=$(dpkg --print-architecture)
[[ "$architecture" == amd64 || "$architecture" == arm64 ]] || die "unsupported architecture: $architecture (expected amd64 or arm64)"
[[ -f "$authorized_key_file" && ! -L "$authorized_key_file" && -r "$authorized_key_file" ]] \
  || die 'SSH public-key file is missing, unreadable, or a symlink'
[[ $(wc -l < "$authorized_key_file") -eq 1 ]] || die 'SSH public-key file must contain exactly one key'
grep -Eq '^(ssh-(ed25519|rsa)|ecdsa-sha2-nistp(256|384|521)) [^[:space:]]+' "$authorized_key_file" \
  || die 'SSH public-key file does not contain a supported OpenSSH public key'

if [[ "$apply_firewall" == true || "$apply_ssh_hardening" == true ]]; then
  [[ "$confirm_ssh_access" == true ]] || die 'hardening requires --confirm-ssh-access after a tested second deployment-user SSH login'
fi

install_docker() {
  note 'installing Docker Engine and Compose plugin from Docker’s official Ubuntu repository'
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends ca-certificates curl gnupg ufw openssh-server cron age awscli postgresql-client
  install -d -m 0755 /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o "$DOCKER_KEYRING"
  chmod a+r "$DOCKER_KEYRING"
  printf '%s\n' \
    "deb [arch=$architecture signed-by=$DOCKER_KEYRING] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" \
    > "$DOCKER_SOURCE"
  apt-get update
  apt-get install -y --no-install-recommends docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
}

install_deploy_user() {
  if ! id "$deploy_user" >/dev/null 2>&1; then
    useradd --create-home --shell /bin/bash "$deploy_user"
  fi
  usermod -aG docker "$deploy_user"
  install -d -m 0700 -o "$deploy_user" -g "$deploy_user" "/home/$deploy_user/.ssh"
  install -m 0600 -o "$deploy_user" -g "$deploy_user" "$authorized_key_file" "/home/$deploy_user/.ssh/authorized_keys"
}

install_persistent_layout() {
  install -d -m 0750 -o "$deploy_user" -g "$deploy_user" "$APP_ROOT"
  install -d -m 0700 -o root -g root "$SECRET_ROOT" "$SECRET_ROOT/backup-drill-targets"
  install -d -m 0700 -o root -g root "$APP_ROOT/backups"
  install -d -m 0755 /var/log/melpis
}

configure_swap() {
  if [[ ! -e /swapfile ]]; then
    note "creating ${swap_gib} GiB encrypted-at-rest-by-provider-dependent swapfile (verify VM volume encryption separately)"
    if ! fallocate -l "${swap_gib}G" /swapfile; then
      dd if=/dev/zero of=/swapfile bs=1M count=$((swap_gib * 1024)) status=progress
    fi
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
  fi
  [[ -f /swapfile && ! -L /swapfile ]] || die '/swapfile is not a regular file'
  chmod 600 /swapfile
  if ! swapon --show=NAME --noheadings | grep -Fxq /swapfile; then
    swapon /swapfile
  fi
  grep -Fqx '/swapfile none swap sw 0 0' /etc/fstab || printf '%s\n' '/swapfile none swap sw 0 0' >> /etc/fstab
}

write_backup_wrapper() {
  install -d -m 0755 /usr/local/sbin
  cat > /usr/local/sbin/melpis-backup <<'WRAPPER'
#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
readonly config=/etc/whatsapp-ai-responder/backup.env
readonly backup_script=/srv/melpis/app/scripts/backup_supabase_r2.sh
[[ -f "$config" && ! -L "$config" ]] || { logger -t melpis-backup 'backup.env absent; backup not configured'; exit 0; }
[[ $(stat -c '%u:%a' "$config") == '0:600' ]] || { logger -t melpis-backup 'backup.env must be root-owned mode 600'; exit 1; }
[[ -x "$backup_script" && ! -L "$backup_script" ]] || { logger -t melpis-backup 'reviewed backup script is missing'; exit 1; }
set -a
# The root-owned, mode-600 configuration is intentionally the only sourced file.
. "$config"
set +a
exec "$backup_script"
WRAPPER
  chmod 0700 /usr/local/sbin/melpis-backup
  cat > /etc/cron.d/melpis-backup <<'CRON'
# Managed by bootstrap_oracle_vm.sh. Output is captured by cron/syslog; configure alerting separately.
17 3 * * * root /usr/local/sbin/melpis-backup
CRON
  chmod 0644 /etc/cron.d/melpis-backup
}

firewall_has_unexpected_ssh_rule() {
  # A narrower-but-different source would also broaden the declared
  # administration boundary. Refuse to silently retain it.
  LC_ALL=C ufw status | grep -E '^22(/|[[:space:]])' | grep -Fv "$admin_cidr" | grep -q 'ALLOW IN'
}

configure_firewall() {
  if firewall_has_unexpected_ssh_rule; then
    die 'UFW has an SSH allow rule outside --admin-cidr; review/remove it manually after validating access, then rerun'
  fi
  if ! LC_ALL=C ufw status | grep -Fq 'Status: active'; then
    ufw default deny incoming
    ufw default allow outgoing
  fi
  # Additive rules avoid resetting or deleting any unrelated operator firewall policy.
  ufw allow from "$admin_cidr" to any port 22 proto tcp
  ufw allow 80/tcp
  ufw allow 443/tcp
  if ! LC_ALL=C ufw status | grep -Fq 'Status: active'; then
    ufw --force enable
  fi
  note "UFW permits SSH only from $admin_cidr and HTTP/HTTPS publicly; mirror these rules in Oracle NSGs/security lists"
}

configure_ssh_hardening() {
  install -d -m 0755 /etc/ssh/sshd_config.d
  cat > /etc/ssh/sshd_config.d/99-melpis.conf <<'SSH'
# Installed only after an independently tested deployment-user key login.
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
SSH
  sshd -t || die 'refusing to reload SSH: generated configuration is invalid'
  systemctl reload ssh
  note 'SSH root and password authentication disabled after explicit access confirmation'
}

install_docker
install_deploy_user
install_persistent_layout
configure_swap
write_backup_wrapper

if [[ "$apply_firewall" == true ]]; then configure_firewall; fi
if [[ "$apply_ssh_hardening" == true ]]; then configure_ssh_hardening; fi

note "complete for $architecture. Deploy as $deploy_user in $APP_ROOT; temporary TLS hostname: $temp_host"
note 'No secrets, images, DNS changes, Oracle capacity assertions, or paid-provider resources were created.'
