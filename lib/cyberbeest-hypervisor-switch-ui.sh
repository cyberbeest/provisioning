#!/bin/bash
# User-facing entry point for switching the active hypervisor (see
# cyberbeest-hypervisor-switch.sh for why this is needed at all: VirtualBox
# and KVM can't both hold VT-x/AMD-V at once). Runs the privileged switch
# via pkexec (graphical password prompt, via the polkit agent already
# running as part of the Xfce session -- no custom polkit policy needed,
# same pattern as 44-wipe-app-data.sh's i2pd entry), then reports success
# or failure as a desktop notification.
#
# Usage: cyberbeest-hypervisor-switch-ui.sh <vbox|kvm>
set -uo pipefail

TARGET="${1:?usage: cyberbeest-hypervisor-switch-ui.sh <vbox|kvm>}"
SWITCH_SCRIPT="$HOME/.local/bin/cyberbeest-hypervisor-switch.sh"

case "$TARGET" in
	vbox) LABEL="VirtualBox" ;;
	kvm)  LABEL="QEMU/KVM" ;;
	*) echo "usage: cyberbeest-hypervisor-switch-ui.sh <vbox|kvm>" >&2; exit 1 ;;
esac

notify() {
	DISPLAY=:0 DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus" \
		notify-send -i computer -a "Cyberbeest" "$@" 2>/dev/null || true
}

if pkexec "$SWITCH_SCRIPT" "$TARGET"; then
	notify "Hypervisor gewechselt" "Aktiv ist jetzt: $LABEL"
else
	notify "Wechsel fehlgeschlagen" "Konnte nicht auf $LABEL wechseln -- siehe Details im Terminal."
fi
