#!/bin/bash
# Starts (or resumes) the Cyberbeest VM, shows it in a virt-viewer window,
# and shuts it down cleanly once that window is closed -- so the VM runs
# exactly as long as it's visible, like any other app. Clicking the menu
# entry again while the window is open just brings that window to the
# front. Installed to ~/.local/bin by lib/download-and-create-sandbox-vm-kvm.sh
# and wired to the Whisker menu launcher (with the VM name baked into the
# launcher's Exec= line as $1).
#
# Closing the window normally *saves* the VM (hibernation) rather than
# shutting it down, so the next start is a restore in seconds; it only
# really shuts down when the guest needs a fresh boot -- see the end.
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

close_note() {
	[ -n "${1:-}" ] && gdbus call --session --dest org.freedesktop.Notifications \
		--object-path /org/freedesktop/Notifications \
		--method org.freedesktop.Notifications.CloseNotification "$1" >/dev/null 2>&1
}

has_saved_state() {
	local info
	info="$(LC_ALL=C virsh --connect "$CONNECT" dominfo "$VM_NAME" 2>/dev/null)"
	grep -q '^Managed save: *yes' <<<"$info"
}

# Runs a command in the guest through its agent; exit status is the
# command's own (1 if the agent doesn't answer).
guest_run() {
	local pid out json
	json="$(python3 -c 'import json,sys; print(json.dumps({"execute":"guest-exec","arguments":{"path":"/bin/sh","arg":["-c",sys.argv[1]]}}))' "$1")"
	pid="$(virsh --connect "$CONNECT" qemu-agent-command "$VM_NAME" "$json" 2>/dev/null \
		| sed -n 's/.*"pid":\([0-9]*\).*/\1/p')"
	[ -n "$pid" ] || return 1
	for _ in $(seq 1 20); do
		out="$(virsh --connect "$CONNECT" qemu-agent-command "$VM_NAME" \
			"{\"execute\":\"guest-exec-status\",\"arguments\":{\"pid\":$pid}}" 2>/dev/null)"
		case "$out" in
			*'"exited":true'*) [[ "$out" == *'"exitcode":0'* ]]; return ;;
		esac
		sleep 0.5
	done
	return 1
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

# A VM closed by this launcher is normally saved (hibernated), not shut
# down -- see the end of this script -- so starting it usually means
# restoring that: seconds instead of a full boot, with everything as it
# was left.
restored=false
case "$(domstate)" in
	"shut off"|crashed)
		# No notice for a boot: its window shows up within seconds and shows
		# the boot. A restore shows nothing until it's done (~10 s), so
		# that gets one, up until the window opens.
		restore_note=""
		if has_saved_state; then
			restored=true
			restore_note="$(notify-send -p -t 0 -i computer -a "Cyberbeest" \
				"$(msg vm_start.restoring_title)" "$(msg vm_start.restoring_body)" 2>/dev/null)"
		fi
		virsh --connect "$CONNECT" start "$VM_NAME" || {
			close_note "$restore_note"
			notify "$(msg vm_start.failed_title)" "$(msg vm_start.failed_body)"
			exit 1
		}
		close_note "$restore_note"
		;;
	paused)
		virsh --connect "$CONNECT" resume "$VM_NAME"
		restored=true
		;;
esac

# After a restore the guest's clock is as far behind as the VM was saved,
# and a password change made meanwhile (see cyberbeest-vm-set-password-hash.sh,
# which can't touch a saved VM) is still pending. Both need the guest
# agent, so this waits for it in the background while the window opens.
after_restore() {
	local pending="$HOME/.local/share/cyberbeest-vms/$VM_NAME.pending-password-hash"
	for _ in $(seq 1 60); do
		virsh --connect "$CONNECT" qemu-agent-command "$VM_NAME" '{"execute":"guest-ping"}' >/dev/null 2>&1 && break
		sleep 1
	done
	virsh --connect "$CONNECT" domtime "$VM_NAME" --sync >/dev/null 2>&1 \
		&& echo "$(date '+%F %T') $VM_NAME restored, guest clock synced"
	if [ -s "$pending" ] && "$HOME/.local/bin/cyberbeest-vm-set-password-hash.sh" "$VM_NAME" <"$pending"; then
		rm -f "$pending"
	fi
}
[ "$restored" = true ] && after_restore &

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

# The laptop shutting down with the window still open: libvirt saves the
# VM itself (auto_shutdown_try_save, set up by 53a-), which is also what
# closed the window -- nothing to do here, and a second save would only
# collide with it.
if [ "$(busctl get-property org.freedesktop.login1 /org/freedesktop/login1 \
	org.freedesktop.login1.Manager PreparingForShutdown 2>/dev/null)" = "b true" ]; then
	echo "$(date '+%F %T') host is shutting down, libvirt saves $VM_NAME"
	exit 0
fi

[ "$(domstate)" = "shut off" ] && exit 0

# Save (hibernate) rather than shut down, unless the guest needs a real
# boot: after updates that ask for one (/run/reboot-required, e.g. a new
# kernel), or once it has run for more than REBOOT_AFTER_DAYS since its last
# real boot -- a VM that's only ever restored would otherwise never apply
# kernel updates. Saving mid-update is fine: the update carries on after
# the restore.
REBOOT_AFTER_DAYS=7
if ! guest_run "[ -e /run/reboot-required ] || [ \$(cut -d. -f1 /proc/uptime) -gt $((REBOOT_AFTER_DAYS * 86400)) ]"; then
	echo "$(date '+%F %T') window closed, saving $VM_NAME"
	note_id="$(notify-send -p -t 0 -i computer -a "Cyberbeest" \
		"$(msg vm_start.saving_title)" 2>/dev/null)"
	# The save takes a while (~11 s, lzop -- see 53a-): shutting down or
	# suspending the laptop in the middle of it would lose the VM's state
	# like a power cut, so both are held off until it's done -- where
	# polkit lets us. polkit grants the lock only to local, active sessions:
	# a launcher started from an SSH session (e.g. testing with DISPLAY set)
	# gets "Failed to inhibit: Interactive authentication required" (.76,
	# 2026-09-25). Saving without it is still far better than shutting the
	# VM down, and a host shutdown mid-save is caught by libvirt's own
	# save-on-shutdown anyway (see 53a-).
	save_out="$(systemd-inhibit --what=shutdown:sleep --who=Cyberbeest --mode=block \
		--why="$(msg vm_start.saving_title)" \
		virsh --connect "$CONNECT" managedsave "$VM_NAME" 2>&1)"
	saved=$?
	if [ "$saved" -ne 0 ] && [[ "$save_out" == *"Failed to inhibit"* ]]; then
		echo "$(date '+%F %T') no shutdown lock ($save_out) -- saving without it"
		save_out="$(virsh --connect "$CONNECT" managedsave "$VM_NAME" 2>&1)"
		saved=$?
	fi
	if [ "$saved" -eq 0 ]; then
		[ -n "$note_id" ] && gdbus call --session --dest org.freedesktop.Notifications \
			--object-path /org/freedesktop/Notifications \
			--method org.freedesktop.Notifications.CloseNotification "$note_id" >/dev/null 2>&1
		echo "$(date '+%F %T') $VM_NAME saved"
		exit 0
	fi
	echo "$(date '+%F %T') saving $VM_NAME failed, shutting it down instead: $save_out"
fi

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
note_id="${note_id:-}"
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
