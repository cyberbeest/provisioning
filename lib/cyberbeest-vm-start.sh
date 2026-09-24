#!/bin/bash
# Starts (or resumes) the Cyberbeest VM, shows it in a virt-viewer window,
# and shuts it down cleanly once that window is closed -- so the VM runs
# exactly as long as it's visible, like any other app. Clicking the menu
# entry again while the window is open just brings that window to the
# front. Installed to ~/.local/bin by lib/download-and-create-sandbox-vm-kvm.sh
# and wired to the Whisker menu launcher (with the VM name baked into the
# launcher's Exec= line as $1).
#
# virt-viewer rather than GNOME Boxes (dropped 2026-09-24): one window for
# one VM, no library of VMs to choose from. The full list, including the
# backup VM an update leaves behind, is in Virtual Machine Manager.
#
# Shuts down via the qemu-guest-agent channel (--mode agent), not a plain
# ACPI `virsh shutdown`: XFCE's power manager answers the ACPI power button
# with a confirmation dialog, which would leave the VM waiting for a click
# no one sees once its window is gone.
#
# Usage: cyberbeest-vm-start.sh [vm-name] [display-name]
set -uo pipefail
VM_NAME="${1:-Cyberbeest-VM}"
DISPLAY_NAME="${2:-$VM_NAME}"
CONNECT="qemu:///session"
SHUTDOWN_TIMEOUT=300  # hard stop only if the guest ignores the agent this long -- generous, since
                      # a shutdown waits for running updates to finish
RUN_DIR="${XDG_RUNTIME_DIR:-/tmp}"
LOCK="$RUN_DIR/cyberbeest-vm-$VM_NAME.lock"
PID_FILE="$RUN_DIR/cyberbeest-vm-$VM_NAME.viewer-pid"
LOG="$RUN_DIR/cyberbeest-vm-$VM_NAME.log"

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$SELF_DIR/i18n.sh"

notify() {
	notify-send -i computer -a "Cyberbeest" "$@" 2>/dev/null || true
}

msg() {
	local text
	text="$(t "$1")"
	printf '%s' "${text//NAME/$DISPLAY_NAME}"
}

domstate() {
	LC_ALL=C virsh --connect "$CONNECT" domstate "$VM_NAME" 2>/dev/null || echo "shut off"
}

exec 9>"$LOCK"
if ! flock -n 9; then
	# Already open: raise the existing window instead of a second viewer.
	pid="$(cat "$PID_FILE" 2>/dev/null)"
	if [ -n "$pid" ]; then
		winid="$(wmctrl -lp 2>/dev/null | awk -v p="$pid" '$3 == p {print $1; exit}')"
		[ -n "$winid" ] && wmctrl -i -a "$winid"
	fi
	exit 0
fi
exec >>"$LOG" 2>&1

case "$(domstate)" in
	"shut off"|crashed)
		notify "$(msg vm_start.starting_title)" "$(msg vm_start.starting_body)"
		virsh --connect "$CONNECT" start "$VM_NAME" || {
			notify "$(msg vm_start.failed_title)" "$(msg vm_start.failed_body)"
			exit 1
		}
		;;
	paused)
		virsh --connect "$CONNECT" resume "$VM_NAME"
		;;
esac

# virt-viewer's title bar is full of icon buttons without tooltips (send
# keys, USB, CD, machine menu, fullscreen, main menu) -- noise for people
# who just want to use the VM. It has no option to hide them outside of
# fullscreen kiosk mode, so a stylesheet does it: GTK3 loads
# $XDG_CONFIG_HOME/gtk-3.0/gtk.css on top of the current theme, and pointing
# XDG_CONFIG_HOME somewhere private for this one process keeps the rule
# away from every other app. GTK3 CSS can't remove a widget, only make it
# invisible and as small as possible, so a few px of each button remain
# (still clickable, but nothing shows there). The bar is made lower too.
# The title keeps virt-viewer's own " (1)" (its display number): virt-viewer
# draws the title itself, so it can't be renamed from outside. The theme
# itself still comes from XFCE's settings daemon, and virt-viewer's own
# settings dir is linked through so it keeps finding them.
VIEWER_CONFIG="$RUN_DIR/cyberbeest-vm-viewer-config"
mkdir -p "$VIEWER_CONFIG/gtk-3.0" "$HOME/.config/virt-viewer"
ln -sfn "$HOME/.config/virt-viewer" "$VIEWER_CONFIG/virt-viewer"
cat >"$VIEWER_CONFIG/gtk-3.0/gtk.css" <<'EOF'
headerbar button:not(.titlebutton) {
	opacity: 0;
	min-width: 0;
	min-height: 0;
	padding: 0;
	margin: 0;
	border: none;
	box-shadow: none;
	background: none;
}
headerbar button:not(.titlebutton) image {
	-gtk-icon-transform: scale(0);
}
/* With its buttons gone the bar only holds the title and the window
   controls, so it needn't be button-height tall any more. */
headerbar {
	min-height: 0;
	padding-top: 0;
	padding-bottom: 0;
}
headerbar button.titlebutton {
	min-height: 0;
	min-width: 0;
	padding: 2px;
	margin-top: 2px;
	margin-bottom: 2px;
}
EOF

# --attach: take the display straight from libvirt, no network port.
# Without --reconnect virt-viewer exits when the guest shuts itself down,
# so shutting down from inside the VM closes the window too.
XDG_CONFIG_HOME="$VIEWER_CONFIG" virt-viewer --connect "$CONNECT" --attach \
	--auto-resize=always --hotkeys=release-cursor=ctrl+alt "$VM_NAME" &
viewer_pid=$!
echo "$viewer_pid" >"$PID_FILE"
wait "$viewer_pid"
rm -f "$PID_FILE"

[ "$(domstate)" = "shut off" ] && exit 0

# Whether the guest is installing packages right now, asked through its
# agent (so only possible before the shutdown starts, while the agent still
# answers). unattended-upgrades is matched on its full command line: its
# process name is cut to "unattended-upgr", which the always-running
# /usr/share/unattended-upgrades/unattended-upgrade-shutdown helper shares.
guest_updating() {
	local pid out
	pid="$(virsh --connect "$CONNECT" qemu-agent-command "$VM_NAME" \
		'{"execute":"guest-exec","arguments":{"path":"/bin/sh","arg":["-c","pgrep -x \"dpkg|apt|apt-get\" || pgrep -f \"^/usr/bin/python3 /usr/bin/unattended-upgrades?( |$)\""]}}' \
		2>/dev/null | sed -n 's/.*"pid":\([0-9]*\).*/\1/p')"
	[ -n "$pid" ] || return 1
	for _ in 1 2 3 4 5 6 7 8 9 10; do
		out="$(virsh --connect "$CONNECT" qemu-agent-command "$VM_NAME" \
			"{\"execute\":\"guest-exec-status\",\"arguments\":{\"pid\":$pid}}" 2>/dev/null)"
		case "$out" in
			*'"exited":true'*) [[ "$out" == *'"exitcode":0'* ]]; return ;;
		esac
		sleep 0.5
	done
	return 1
}

# Notifications stay up (-t 0) until the VM is actually off, then get
# closed -- rather than vanishing after the notification daemon's default
# few seconds while the shutdown is still going on.
note_id=""
if guest_updating; then
	# Shutting down now would interrupt dpkg (the guest's shutdown only
	# waits for unattended-upgrades, not for a manual apt run), so wait for
	# the updates to finish first -- up to 30 minutes, then shut down anyway.
	echo "$(date '+%F %T') window closed while $VM_NAME is installing updates, waiting for them"
	note_id="$(notify-send -p -t 0 -i computer -a "Cyberbeest" \
		"$(msg vm_start.updating_title)" "$(msg vm_start.updating_body)" 2>/dev/null)"
	for _ in $(seq 1 180); do
		sleep 10
		guest_updating || break
	done
fi
echo "$(date '+%F %T') window closed, shutting down $VM_NAME (agent mode)"
note_id="$(notify-send -p -t 0 ${note_id:+-r "$note_id"} -i computer -a "Cyberbeest" \
	"$(msg vm_start.stopping_title)" "$(msg vm_start.stopping_body)" 2>/dev/null)"
waited=0
while [ "$waited" -lt "$SHUTDOWN_TIMEOUT" ]; do
	virsh --connect "$CONNECT" shutdown "$VM_NAME" --mode agent >/dev/null 2>&1
	sleep 3
	waited=$((waited + 3))
	[ "$(domstate)" = "shut off" ] && break
done
if [ "$(domstate)" != "shut off" ]; then
	virsh --connect "$CONNECT" destroy "$VM_NAME" >/dev/null 2>&1
	notify ${note_id:+-r "$note_id"} "$(msg vm_start.killed_title)" "$(msg vm_start.killed_body)"
	echo "$(date '+%F %T') $VM_NAME ignored the shutdown for ${SHUTDOWN_TIMEOUT}s, hard-stopped"
else
	[ -n "$note_id" ] && gdbus call --session --dest org.freedesktop.Notifications \
		--object-path /org/freedesktop/Notifications \
		--method org.freedesktop.Notifications.CloseNotification "$note_id" >/dev/null 2>&1
	echo "$(date '+%F %T') $VM_NAME shut down cleanly"
fi
