#!/bin/bash
# Shared helper for reloading xfce4-panel, for a script that's running as
# root (via sudo) and needs the logged-in TARGET_USER's panel to pick up
# freshly-written xfconf data or newly-built plugins.
#
# Never use `xfce4-panel -r`: it asks the still-running process to restart
# itself from whatever config it already has cached client-side (e.g. the
# stock defaults from the very first, pre-provisioning login), then persists
# that stale state back to xfconfd -- silently clobbering xfconf data another
# script just wrote, sometimes a few seconds later. This bit
# 11-xfce-panel-plugins.sh's `-r` call landing (asynchronously) in the middle
# of 12-xfce-panel-layout.sh's own write+reload, undoing it. Always kill the
# process outright and launch a fresh one instead, so it has no cached state
# to fall back on and is forced to actually read xfconfd from scratch.
#
# Must run as root with TARGET_USER already set (same convention as
# lib/xdg-dirs.sh). Usage:
#
#   if xfce_panel_dbus_addr; then
#       xfce_panel_kill
#       ...anything that needs xfconfd freshly restarted first...
#       xfce_panel_launch
#   fi
#
# xfce_panel_dbus_addr must be called first (while the old panel process is
# still alive, to read its environ) and is also the "is a panel even running
# for this user" guard -- it returns 1 and does nothing else if not, so
# callers can skip the whole reload on a machine with no graphical session.

xfce_panel_dbus_addr() {
	command -v xfce4-panel >/dev/null 2>&1 || return 1
	XFCE_PANEL_PID="$(pgrep -u "$TARGET_USER" -x xfce4-panel | head -1)" || true
	[ -n "$XFCE_PANEL_PID" ] || return 1

	# cat (not `< file`) so a PID that vanishes between pgrep and here just
	# yields empty output instead of a fatal shell redirection error.
	XFCE_PANEL_DBUS_ADDR="$(cat "/proc/$XFCE_PANEL_PID/environ" 2>/dev/null | tr '\0' '\n' | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')" || true
	XFCE_PANEL_DBUS_ADDR="${XFCE_PANEL_DBUS_ADDR:-unix:path=/run/user/$(id -u "$TARGET_USER")/bus}"
}

xfce_panel_kill() {
	# -9/SIGKILL, not a plain (SIGTERM) pkill: a graceful xfce4-panel exit
	# re-persists its currently-loaded plugin config (rc files, xfconf
	# plugin-ids) from its own in-memory state as part of shutting down --
	# clobbering config a script just wrote to disk moments earlier, the
	# same failure mode as the `-r` case above, just via a different path.
	# Caught 2026-09-05 merging the genmon-11/genmon-16 widgets: the write
	# step ran cleanly, but the plugin-11 rc and the plugin-ids array both
	# reverted to their pre-merge contents once the killed panel finished
	# exiting.
	pkill -9 -u "$TARGET_USER" -x xfconfd || true
	pkill -9 -u "$TARGET_USER" -x xfce4-panel || true
	sleep 1
}

xfce_panel_launch() {
	su - "$TARGET_USER" -c "DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$XFCE_PANEL_DBUS_ADDR' setsid xfce4-panel >/dev/null 2>&1 < /dev/null &"
	sleep 1
	if ! pgrep -u "$TARGET_USER" -x xfce4-panel >/dev/null; then
		echo "--- Panel process didn't come up after launch ---"
	fi
}
