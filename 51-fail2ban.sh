#!/bin/bash
# Installs fail2ban as a default, near-zero-cost security bonus. Machines
# ship without sshd (99-remove-openssh-server.sh purges it last), so the
# sshd jail configured here normally has nothing to watch and just sits
# idle -- but if a user (or a future debugging session, see
# 99-remove-openssh-server.sh's header) re-enables openssh-server, they get
# brute-force ban protection automatically instead of a bare unauthenticated
# daemon on the network.
#
# Ships jail.local with the sshd jail explicitly enabled (Debian's default
# jail.conf ships it commented out under [sshd] with enabled left to the
# distro default, which is off) plus modestly stricter-than-default
# thresholds. Uses systemd backend so it reads the journal directly --
# no logfile path assumptions to get wrong.
#
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/51-fail2ban.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing fail2ban ==="

apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y fail2ban

install -d -m 755 /etc/fail2ban/jail.d
cat > /etc/fail2ban/jail.d/cyberbeest-sshd.conf <<'EOF'
# Managed by Cyberbeest provisioning (51-fail2ban.sh). Edits here are safe
# to make locally but will be overwritten if provisioning re-runs this
# script.
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
