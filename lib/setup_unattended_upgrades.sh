#!/bin/bash
# Sets up unattended-upgrades to apply Debian security updates only, on a daily timer.
# Run with: sudo bash ~/provisioning/lib/setup_unattended_upgrades.sh (normally invoked via ../05-unattended-upgrades-security.sh)
set -euo pipefail

LOG="$(dirname "$(readlink -f "$0")")/setup_unattended_upgrades.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date -Is) : setup_unattended_upgrades.sh starting ==="

if [ "$(id -u)" -ne 0 ]; then
    echo "This script must be run with sudo." >&2
    exit 1
fi

echo "--- Installing unattended-upgrades ---"
apt-get -o DPkg::Lock::Timeout=60 update
apt-get -o DPkg::Lock::Timeout=60 install -y unattended-upgrades

CODENAME="$(. /etc/os-release && echo "$VERSION_CODENAME")"
echo "Detected codename: $CODENAME"

echo "--- Writing security-only origins config ---"
cat > /etc/apt/apt.conf.d/51unattended-upgrades-local <<EOF
// Managed by provisioning/lib/setup_unattended_upgrades.sh -- security updates only.
Unattended-Upgrade::Origins-Pattern {
    "origin=Debian,codename=${CODENAME}-security,label=Debian-Security";
};
Unattended-Upgrade::Remove-Unused-Dependencies "true";
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::SyslogEnable "true";
EOF

echo "--- Enabling daily periodic checks ---"
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

echo "--- Enabling systemd timers ---"
systemctl enable --now apt-daily.timer apt-daily-upgrade.timer

echo "--- Dry-run test ---"
unattended-upgrades --dry-run --debug

echo "=== $(date -Is) : setup_unattended_upgrades.sh finished successfully ==="
echo "Log written to: $LOG"
