#!/bin/bash
# Wires up fail2ban's sshd jail to install itself automatically the moment
# openssh-server shows up on the machine, instead of installing fail2ban
# unconditionally. Machines ship without sshd (99-remove-openssh-server.sh
# purges it last), so most units would otherwise carry an always-idle
# fail2ban daemon for no reason -- see lib/cyberbeest-fail2ban-autoinstall.sh
# for the actual install/configure logic and lib/99cyberbeest-fail2ban-on-ssh
# for the apt hook that triggers it on every future apt run.
#
# Also runs the autoinstall script once immediately, covering the case
# where openssh-server is already installed at provisioning time (e.g. it
# was turned on by hand to debug a unit before this script ran).
#
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/51-fail2ban.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : wiring up fail2ban-on-ssh-install hook ==="

install -o root -g root -m 755 \
	"$DIR/lib/cyberbeest-fail2ban-autoinstall.sh" \
	/usr/local/sbin/cyberbeest-fail2ban-autoinstall.sh

install -o root -g root -m 644 \
	"$DIR/lib/99cyberbeest-fail2ban-on-ssh" \
	/etc/apt/apt.conf.d/99cyberbeest-fail2ban-on-ssh

echo "--- Running the autoinstall check now (no-op unless openssh-server is already present) ---"
/usr/local/sbin/cyberbeest-fail2ban-autoinstall.sh

echo "=== $(date) : done ==="
