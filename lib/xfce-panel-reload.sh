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
#       xfce_panel_launch || echo "panel reload didn't stick" >&2
#   fi
#
# xfce_panel_dbus_addr must be called first (while the old panel process is
# still alive, to read its environ) and is also the "is a panel even running
# for this user" guard -- it returns 1 and does nothing else if not, so
# callers can skip the whole reload on a machine with no graphical session.
#
# xfce_panel_kill waits (up to 5s) for the old process to actually be gone,
# and xfce_panel_launch waits (up to 5s) for a *new*, different pid to
# appear and then re-checks it after a short settle -- both print a
# "warning:" line on stderr and xfce_panel_launch returns 1 if the reload
# didn't genuinely take live effect. Before this, a write to xfconf could
# succeed while the running panel silently never picked it up (caught
# 2026-09-14 with the i2pd toggle's panel icon) -- callers should check
# xfce_panel_launch's exit status rather than assume success.

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

	# Wait for the old process to actually be gone rather than trusting a
	# flat `sleep 1` -- a lingering old process (SIGKILL raced with the
	# process being in an uninterruptible state, or a supervisor instantly
	# respawning it) would otherwise go unnoticed, and xfce_panel_launch's
	# own "a process exists" check can't tell that lingering old process
	# apart from a genuinely fresh one. Caught 2026-09-14: an i2pd panel
	# icon add wrote xfconf correctly but the live panel never picked it
	# up, with nothing in any log -- the reload silently never happened
	# and nothing along the way was in a position to say so.
	local waited=0
	while pgrep -u "$TARGET_USER" -x xfce4-panel >/dev/null 2>&1; do
		sleep 0.5
		waited=$((waited + 1))
		if [ "$waited" -ge 10 ]; then
			echo "--- warning: xfce4-panel still running 5s after SIGKILL ---" >&2
			break
		fi
	done
}

xfce_panel_launch() {
	local old_pid="${XFCE_PANEL_PID:-}"
	su - "$TARGET_USER" -c "DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$XFCE_PANEL_DBUS_ADDR' setsid xfce4-panel >/dev/null 2>&1 < /dev/null &"

	# Poll for a new pid rather than a flat sleep -- and require it to
	# differ from the pid we killed, since "a process exists" alone can't
	# distinguish a genuinely fresh launch from the old one never having
	# died (see xfce_panel_kill).
	local new_pid=""
	local waited=0
	while [ "$waited" -lt 10 ]; do
		new_pid="$(pgrep -u "$TARGET_USER" -x xfce4-panel | head -1)"
		if [ -n "$new_pid" ] && [ "$new_pid" != "$old_pid" ]; then
			break
		fi
		sleep 0.5
		waited=$((waited + 1))
	done
	if [ -z "$new_pid" ]; then
		echo "--- warning: xfce4-panel did not come up after launch ---" >&2
		return 1
	fi
	if [ "$new_pid" = "$old_pid" ]; then
		echo "--- warning: xfce4-panel pid unchanged after launch (old process never died?) ---" >&2
		return 1
	fi

	# Something else (xfce4-session's own respawn-on-crash logic, most
	# likely) can replace our freshly launched panel with another one a
	# moment later, e.g. restored from its own cached session state --
	# re-check after a short settle so that gets caught too instead of
	# reporting success on a pid that's about to be replaced.
	sleep 1.5
	local settled_pid
	settled_pid="$(pgrep -u "$TARGET_USER" -x xfce4-panel | head -1)"
	if [ "$settled_pid" != "$new_pid" ]; then
		echo "--- warning: xfce4-panel pid changed again during settle (pid $new_pid -> ${settled_pid:-gone}) -- something else respawned it ---" >&2
		return 1
	fi
}
