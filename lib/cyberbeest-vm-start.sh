#!/bin/bash
# Idempotently starts (or resumes) the Cyberbeest sandbox VM and opens it
# in GNOME Boxes. Also ensures the close-watcher and title-fix loop are
# running. Installed to ~/.local/bin by lib/download-and-create-sandbox-vm-kvm.sh
# and wired to a Whisker menu launcher (with the VM name baked into the
# launcher's Exec= line as $1, so a custom vm-name at install time still
# works end-to-end).
#
# Usage: cyberbeest-vm-start.sh [vm-name] [display-name]
set -euo pipefail

VM_NAME="${1:-Cyberbeest-Sandbox}"
DISPLAY_NAME="${2:-$VM_NAME}"
CONNECT="qemu:///session"
WATCHER="$HOME/.local/bin/cyberbeest-vm-watcher.sh"
TITLE_FIX="$HOME/.local/bin/cyberbeest-vm-title-fix.sh"

notify() {
	DISPLAY=:0 DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus" \
		notify-send -i computer -a "Cyberbeest" "$@" 2>/dev/null || true
}

state=$(virsh --connect "$CONNECT" domstate "$VM_NAME" 2>/dev/null || echo "shut off")

case "$state" in
	"shut off"|"crashed")
		notify "Virtuelle Maschine wird gestartet" "$DISPLAY_NAME wird hochgefahren…"
		virsh --connect "$CONNECT" start "$VM_NAME"
		;;
	"paused")
		notify "Virtuelle Maschine wird fortgesetzt" "$DISPLAY_NAME wird fortgesetzt…"
		virsh --connect "$CONNECT" resume "$VM_NAME"
		;;
	"running")
		: # already running, nothing to do
		;;
esac

# Make sure exactly one watcher is running for this VM.
if ! pgrep -f "cyberbeest-vm-watcher.sh $VM_NAME" >/dev/null 2>&1; then
	nohup "$WATCHER" "$VM_NAME" >/tmp/cyberbeest-vm-watcher.log 2>&1 &
	disown
fi

# Make sure exactly one title-fix loop is running for this VM.
if ! pgrep -f "cyberbeest-vm-title-fix.sh $VM_NAME" >/dev/null 2>&1; then
	nohup "$TITLE_FIX" "$VM_NAME" "$DISPLAY_NAME" >/tmp/cyberbeest-vm-title-fix.log 2>&1 &
	disown
fi

uuid=$(virsh --connect "$CONNECT" domuuid "$VM_NAME")
gnome-boxes --open-uuid="$uuid" >/dev/null 2>&1 &
disown
