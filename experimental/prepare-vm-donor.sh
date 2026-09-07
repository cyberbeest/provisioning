#!/bin/bash
# Prepares the dev "Fresh VM" to be used as the donor disk image for the
# sandbox-VM-in-a-box feature (host installs VirtualBox, downloads this
# image, and boots a same-OS guest VM from it -- see 53-virtualbox.sh).
# Host-only helper -- not part of provisioning, never runs on real
# hardware, and not something an end user's machine ever runs.
#
# Does exactly three things, in order:
#   1. Runs 99-remove-openssh-server.sh (purges sshd/fail2ban, wipes every
#      user's authorized_keys) -- the donor image must not carry a remote-
#      access daemon or this VM's own dev SSH key into every clone of it.
#   2. Clears shell history for every local user (including root) --
#      command history from testing/provisioning runs on this specific VM
#      has no business being in an image every end user's guest VM starts
#      from.
#   3. Shuts the machine down cleanly, so the disk is left in a quiescent
#      state ready to be copied/exported.
#
# Deliberately narrow: this does NOT touch machine-id, the systemd
# journal, or the apt cache -- those are worth cleaning for a proper golden
# image too (avoiding duplicate machine-ids across every clone, mainly),
# but are a separate, not-yet-decided step.
#
# Usage: sudo bash prepare-vm-donor.sh
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== $(date) : preparing VM as donor image ==="

echo "--- Running 99-remove-openssh-server.sh ---"
bash "$DIR/99-remove-openssh-server.sh"

echo "--- Clearing shell history for every local user ---"
{
	echo "/root"
	getent passwd | awk -F: '$3 >= 1000 && $3 < 60000 {print $6}'
} | sort -u | while read -r home; do
	for f in "$home/.bash_history" "$home/.local/share/fish/fish_history" "$home/.zsh_history"; do
		if [ -e "$f" ]; then
			rm -f "$f"
			echo "removed $f"
		fi
	done
done
# Also drop this very session's own in-memory history, in case this script
# is sourced/run interactively rather than as a clean subprocess.
history -c 2>/dev/null || true

echo "--- Shutting down ---"
systemctl poweroff
