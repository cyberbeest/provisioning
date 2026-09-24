#!/bin/bash
# Sets the sandbox VM's "cyberbeest" password to the host user's, so the
# host's short password also works for sudo prompts inside the VM. Takes a
# crypt(3) hash on stdin -- never the password itself -- and writes it as
# the guest account's hash:
#   - VM running: through the guest agent (guest-set-user-password, crypted)
#   - VM shut off: offline, into the disk image (virt-customize)
#   - anything else (paused, saved state, starting up): skipped and logged;
#     editing a disk that belongs to a saved RAM state would corrupt it
# Only the current VM: a backup left by an update keeps its old password,
# being a snapshot of the old state.
#
# Called by 56-cyberbeest-sandbox-vm-kvm.sh (with the hash from the host's
# /etc/shadow, so a new VM starts with the current password, and a password
# changed elsewhere catches up on the next run) and by the change-password
# dialog (disk_password_gui.py, with a fresh hash of the new password).
# Runs as the user who owns the VM (qemu:///session).
#
# Usage: <hash> | cyberbeest-vm-set-password-hash.sh [vm-name]
set -uo pipefail
VM_NAME="${1:-Cyberbeest-VM}"
CONNECT="qemu:///session"
# qemu:///session finds the user's libvirt daemon through XDG_RUNTIME_DIR.
# Run via sudo -u (as 56- does), that's unset, and virsh then starts a
# second, separate daemon that doesn't know about VMs the desktop session
# is running -- a running VM looks "shut off" to it. Seen 2026-09-24; it
# would have let an update rename a running VM and move its disk.
if [ -z "${XDG_RUNTIME_DIR:-}" ] && [ -d "/run/user/$(id -u)" ]; then
	export XDG_RUNTIME_DIR="/run/user/$(id -u)"
fi
GUEST_USER="cyberbeest"
LOG="${XDG_RUNTIME_DIR:-/tmp}/cyberbeest-vm-set-password.log"

log() { echo "$(date '+%F %T') $*" | tee -a "$LOG" >&2; }

hash="$(head -n1)"
# A usable crypt hash starts with "$"; "!" or "*" means a locked account.
if [[ "$hash" != \$* ]]; then
	log "no usable password hash given -- not touching $VM_NAME"
	exit 1
fi

names="$(virsh --connect "$CONNECT" list --all --name 2>/dev/null)" || { log "virsh failed"; exit 1; }
grep -qxF "$VM_NAME" <<<"$names" || exit 0

state="$(LC_ALL=C virsh --connect "$CONNECT" domstate "$VM_NAME" 2>/dev/null)"
info="$(LC_ALL=C virsh --connect "$CONNECT" dominfo "$VM_NAME" 2>/dev/null)"

case "$state" in
	running)
		# Fed to virsh on stdin rather than as an argument, so the hash
		# doesn't show up in other users' process listings. Base64 has no
		# quote characters, so single-quoting the JSON is safe.
		json="{\"execute\":\"guest-set-user-password\",\"arguments\":{\"username\":\"$GUEST_USER\",\"password\":\"$(printf '%s' "$hash" | base64 -w0)\",\"crypted\":true}}"
		for _ in $(seq 1 24); do  # the agent may still be starting
			# Output captured first: `virsh | grep -q` under pipefail
			# fails whenever grep's early exit SIGPIPEs virsh -- turning a
			# password that *was* set into a retry loop.
			out="$(printf "qemu-agent-command %s '%s'\n" "$VM_NAME" "$json" \
				| virsh --connect "$CONNECT" 2>/dev/null)"
			if [[ "$out" == *'{"return":'* ]]; then
				log "$VM_NAME: password updated (running, via guest agent)"
				exit 0
			fi
			sleep 5
		done
		log "$VM_NAME: guest agent didn't answer -- password not updated"
		exit 1
		;;
	"shut off")
		if grep -q '^Managed save: *yes' <<<"$info"; then
			log "$VM_NAME has a saved state -- password not updated"
			exit 1
		fi
		tmp="$(mktemp "${XDG_RUNTIME_DIR:-/tmp}/cyberbeest-vm-hash.XXXXXX")"
		trap 'rm -f "$tmp"' EXIT
		printf '%s\n' "$hash" >"$tmp"
		disk="$(LC_ALL=C virsh --connect "$CONNECT" domblklist "$VM_NAME" | awk '$1 == "vda" {print $2}')"
		if virt-customize -q -a "$disk" \
			--upload "$tmp:/root/.cyberbeest-password-hash" \
			--run-command "usermod -p \"\$(cat /root/.cyberbeest-password-hash)\" $GUEST_USER; rm -f /root/.cyberbeest-password-hash" \
			>>"$LOG" 2>&1; then
			log "$VM_NAME: password updated (shut off, offline)"
			exit 0
		fi
		log "$VM_NAME: offline update failed -- password not updated"
		exit 1
		;;
	*)
		log "$VM_NAME is $state -- password not updated"
		exit 1
		;;
esac
