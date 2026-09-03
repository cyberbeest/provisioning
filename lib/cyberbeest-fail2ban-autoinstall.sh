#!/bin/bash
# Installs and configures fail2ban's sshd jail, but only actually does
# anything once openssh-server is present on the machine -- see
# 51-fail2ban.sh, which installs *this* script plus the apt hook that
# triggers it. Machines ship without sshd by default, so this keeps
# fail2ban's ~15-20MB idle footprint off every unit that never installs
# ssh, while still auto-protecting the ones where a user (or a debugging
# session, see 99-remove-openssh-server.sh) turns sshd on.
#
# Safe to call any time (checks openssh-server itself); safe to re-run
# (fail2ban install + jail config are idempotent).
set -uo pipefail
LOG=/var/log/cyberbeest-fail2ban-autoinstall.log
exec >>"$LOG" 2>&1

if ! dpkg -s openssh-server >/dev/null 2>&1; then
	exit 0
fi

echo "=== $(date) : openssh-server present, ensuring fail2ban ==="

# Called from an apt hook that fires right as the triggering apt-get is
# still finishing up -- give its locks a chance to clear before starting
# our own apt-get, rather than fighting over DPkg::Lock::Timeout.
for _ in $(seq 1 60); do
	fuser /var/lib/dpkg/lock-frontend /var/lib/apt/lists/lock >/dev/null 2>&1 || break
	sleep 1
done

if ! dpkg -s fail2ban >/dev/null 2>&1; then
	apt-get -o DPkg::Lock::Timeout=60 install -y fail2ban
fi

install -d -m 755 /etc/fail2ban/jail.d
cat > /etc/fail2ban/jail.d/cyberbeest-sshd.conf <<'EOF'
# Managed by Cyberbeest provisioning (lib/cyberbeest-fail2ban-autoinstall.sh).
# Edits here are safe to make locally but will be overwritten the next time
# this runs (any apt install/remove while openssh-server is present).
[sshd]
enabled = true
backend = systemd
maxretry = 4
bantime = 1h
findtime = 10m
EOF

systemctl enable --now fail2ban.service
systemctl restart fail2ban.service

echo "=== $(date) : done ==="
