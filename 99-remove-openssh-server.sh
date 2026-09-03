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
#
# Also wipes every local user's ~/.ssh/authorized_keys(2) -- purging the
# server alone leaves any debugging pubkey sitting there, which would grant
# instant access again the moment sshd (or any SSH daemon) is ever
# reinstalled or re-enabled by accident. Deliberately targets only the
# authorized_keys files (the inbound-access grant), not the rest of ~/.ssh
# -- a private key generated on the machine for its own outbound git/ssh use
# isn't a backdoor and shouldn't be swept up here.
# Idempotent: safe to re-run (every step below is already a no-op if
# openssh-server isn't installed/running, or no authorized_keys exist).
#
# Bumped 2026-09-03: also purges fail2ban (see 51-fail2ban.sh), which only
# exists here to protect sshd -- touched so run-gui.py's log-newer-than-script
# skip check re-runs this on machines that already completed it.
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

# fail2ban (see 51-fail2ban.sh) exists here only to protect sshd -- with
# ssh gone it's dead weight, and the apt hook it installs will bring it
# straight back if sshd is ever reinstalled.
if dpkg -s fail2ban >/dev/null 2>&1; then
	echo "--- Purging fail2ban (no longer needed without sshd) ---" | tee -a "$LOG"
	apt-get -o DPkg::Lock::Timeout=60 purge -y fail2ban
fi

echo "--- Clearing authorized_keys for every local user (including root) ---" | tee -a "$LOG"
{
	echo "/root"
	getent passwd | awk -F: '$3 >= 1000 && $3 < 60000 {print $6}'
} | sort -u | while read -r home; do
	for f in "$home/.ssh/authorized_keys" "$home/.ssh/authorized_keys2"; do
		if [ -e "$f" ]; then
			rm -f "$f"
			echo "removed $f" | tee -a "$LOG"
		fi
	done
done

echo "=== $(date) : done ===" | tee -a "$LOG"
