#!/bin/bash
# Watches a libvirt VM for GNOME Boxes pausing it (which is what Boxes does
# when its window is closed) and gracefully shuts the VM down instead, so
# "close window" behaves like it does in VirtualBox: the VM actually stops,
# rather than sitting paused in the background indefinitely holding its
# full RAM allocation -- confusing for a non-technical user who expects
# closing a window to actually close it.
#
# Uses the qemu-guest-agent channel to shut down (--mode agent), not a
# plain ACPI `virsh shutdown`: XFCE's power manager intercepts the ACPI
# power-button event with a confirmation dialog instead of acting on it,
# which would leave the VM sitting there waiting for a click no one sees.
# Requires qemu-guest-agent installed and running in the guest -- baked
# into the donor image itself (see build-kvm-donor-image.sh), not
# something this script sets up.
#
# Usage: cyberbeest-vm-watcher.sh <vm-name>
set -uo pipefail

VM_NAME="${1:?usage: cyberbeest-vm-watcher.sh <vm-name>}"
CONNECT="qemu:///session"
GRACE_SECONDS=5      # ignore momentary pauses shorter than this
SHUTDOWN_TIMEOUT=30  # fall back to a hard stop if the guest doesn't respond

notify() {
	DISPLAY=:0 DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus" \
		notify-send -i computer -a "Cyberbeest" "$@" 2>/dev/null || true
}

shutdown_vm() {
	echo "$(date '+%F %T') shutting down $VM_NAME (agent mode)"
	notify "Virtuelle Maschine wird heruntergefahren" "$VM_NAME: Fenster geschlossen, fahre sauber herunter…"
	virsh --connect "$CONNECT" shutdown "$VM_NAME" --mode agent >/dev/null 2>&1

	waited=0
	while [ "$waited" -lt "$SHUTDOWN_TIMEOUT" ]; do
		state=$(virsh --connect "$CONNECT" domstate "$VM_NAME" 2>/dev/null || echo "shut off")
		[ "$state" = "shut off" ] && break
		sleep 2
		waited=$((waited + 2))
	done

	state=$(virsh --connect "$CONNECT" domstate "$VM_NAME" 2>/dev/null || echo "shut off")
	if [ "$state" != "shut off" ]; then
		virsh --connect "$CONNECT" destroy "$VM_NAME" >/dev/null 2>&1
		notify "Virtuelle Maschine gestoppt" "$VM_NAME: reagierte nicht, wurde hart gestoppt."
		echo "$(date '+%F %T') $VM_NAME did not shut down in ${SHUTDOWN_TIMEOUT}s, hard-stopped"
	else
		notify "Virtuelle Maschine gestoppt" "$VM_NAME wurde sauber heruntergefahren."
		echo "$(date '+%F %T') $VM_NAME shut down cleanly"
	fi
}

virsh --connect "$CONNECT" event --domain "$VM_NAME" --event lifecycle --loop --timestamp 2>/dev/null |
while read -r line; do
	case "$line" in
		*"Suspended Paused"*)
			sleep "$GRACE_SECONDS"
			state=$(virsh --connect "$CONNECT" domstate "$VM_NAME" 2>/dev/null || echo "shut off")
			[ "$state" = "paused" ] && shutdown_vm
			;;
		*"Stopped"*|*"Undefined"*)
			exit 0
			;;
	esac
done
