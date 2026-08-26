#!/bin/bash
# Removes openssh-server so shipped machines don't carry a remote-access
# daemon by default -- minimal attack surface. Numbered 99- deliberately:
# it must run dead last, after every other script that might have needed
# sshd temporarily enabled for debugging a unit before it ships (see
# cyberbeest_autostart_rerun_bug.md-adjacent debugging session, 2026-08-26,
# where sshd was turned on by hand on a live unit to diagnose it -- this
# script is what turns it back off for good afterwards).
# Stops+disables the service before purging the package too, in case sshd
# was ever manually re-enabled or reinstalled outside the normal apt flow.
# Idempotent: safe to re-run (every step below is already a no-op if
# openssh-server isn't installed/running).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/99-remove-openssh-server.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : removing openssh-server ===" | tee -a "$LOG"

systemctl disable --now ssh.service ssh.socket 2>/dev/null || true

if dpkg -s openssh-server >/dev/null 2>&1; then
	apt-get -o DPkg::Lock::Timeout=60 purge -y openssh-server
	apt-get -o DPkg::Lock::Timeout=60 autoremove -y
else
	echo "openssh-server not installed -- nothing to purge." | tee -a "$LOG"
fi

echo "=== $(date) : done ===" | tee -a "$LOG"
