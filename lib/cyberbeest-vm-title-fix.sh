#!/bin/bash
# GNOME Boxes (GTK4/libadwaita) never updates its real X11 window title --
# the box's name is only drawn inside its own client-side header bar, so
# the xfce4-panel tasklist (which reads the actual X11 title) always shows
# the generic app name "Boxes" instead of the VM's name. This forces the
# X11 title to match, so the taskbar entry looks like any other app's.
#
# Matches the window by its WM_CLASS (org.gnome.Boxes), not by its current
# title text -- the title changes as soon as this script does its job, so
# matching by title would lose track of the window after the first fix.
#
# Usage: cyberbeest-vm-title-fix.sh <vm-name> <display-name>
set -uo pipefail

VM_NAME="${1:?usage: cyberbeest-vm-title-fix.sh <vm-name> <display-name>}"
DISPLAY_NAME="${2:?usage: cyberbeest-vm-title-fix.sh <vm-name> <display-name>}"
CONNECT="qemu:///session"

while :; do
	state=$(virsh --connect "$CONNECT" domstate "$VM_NAME" 2>/dev/null || echo "shut off")
	[ "$state" = "shut off" ] && exit 0

	winid=$(wmctrl -lx 2>/dev/null | awk '$3 ~ /org\.gnome\.Boxes/ {print $1; exit}')
	if [ -n "$winid" ]; then
		wmctrl -i -r "$winid" -N "$DISPLAY_NAME" 2>/dev/null || true
	fi

	sleep 3
done
