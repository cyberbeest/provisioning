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
# xfce_panel_kill waits (up to 30s) for the old process to be *confirmed*
# gone -- and now returns 1, not just a warning, if it never is -- and
# xfce_panel_launch waits (up to 5s) for a *new*, different pid to appear
# and then re-checks it after a short settle, also returning 1 on failure.
# Every caller so far calls xfce_panel_kill bare (no `||`) under `set -e`,
# so a real failure there now halts the script instead of silently
# continuing to write/relaunch on top of an unconfirmed kill -- see
# xfce_panel_kill's own comment for why that used to be dangerous. Before
# xfce_panel_launch existed, a write to xfconf could succeed while the
# running panel silently never picked it up (caught 2026-09-14 with the
# i2pd toggle's panel icon) -- callers should check its exit status rather
# than assume success.

xfce_panel_dbus_addr() {
	command -v xfce4-panel >/dev/null 2>&1 || return 1
	XFCE_PANEL_PID="$(pgrep -u "$TARGET_USER" -x xfce4-panel | head -1)" || true
	[ -n "$XFCE_PANEL_PID" ] || return 1

	# cat (not `< file`) so a PID that vanishes between pgrep and here just
	# yields empty output instead of a fatal shell redirection error.
	XFCE_PANEL_DBUS_ADDR="$(cat "/proc/$XFCE_PANEL_PID/environ" 2>/dev/null | tr '\0' '\n' | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')" || true
	XFCE_PANEL_DBUS_ADDR="${XFCE_PANEL_DBUS_ADDR:-unix:path=/run/user/$(id -u "$TARGET_USER")/bus}"

	# xfce4-session is the session leader and always carries the full
	# XDG_*/DESKTOP_SESSION environment LightDM's PAM session set up at
	# login (XDG_CURRENT_DESKTOP, XDG_RUNTIME_DIR, XDG_DATA_DIRS, ...) --
	# xfce4-panel itself may already be missing these if a previous run of
	# this same helper relaunched it without them, so always source from
	# xfce4-session, never from the (possibly already-degraded) panel
	# process. Apps launched from the panel/whisker menu inherit whatever
	# xfce4-panel has, and Chromium's keyring-backend detection (used by
	# Electron's safeStorage in Signal/Element/Telegram) needs
	# XDG_CURRENT_DESKTOP to pick a backend -- without it, those apps fail
	# to start with an "unsupported keyring" dialog. Caught 2026-09-23 on
	# .76 after a provisioning batch that reloaded the panel repeatedly.
	XFCE_SESSION_ENV=()
	local session_pid
	session_pid="$(pgrep -u "$TARGET_USER" -x xfce4-session | head -1)" || true
	if [ -n "$session_pid" ]; then
		while IFS= read -r -d '' line; do
			case "$line" in
				XDG_*=*|DESKTOP_SESSION=*) XFCE_SESSION_ENV+=("$line") ;;
			esac
		done < "/proc/$session_pid/environ"
	fi
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
	#
	# Deliberately does NOT touch xfconfd. xfconfd is already the source of
	# truth for the write a caller just made -- it has no stale client-side
	# cache to drop the way the panel does, so there was never a reason to
	# kill it too. Doing so anyway used to race xfconfd's own async disk
	# flush: SIGKILLing it right after a write could lose that write
	# entirely, and the freshly (auto-)respawned xfconfd would then reload
	# the stale on-disk XML, silently reverting the change. Caught
	# 2026-09-16 on tower: an i2pd panel-icon removal wrote plugin-ids
	# correctly, xfconfd was killed a moment later before it flushed, and
	# the icon came back on every subsequent panel restart because the
	# on-disk xfce4-panel.xml still had the old value.
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
	#
	# 30s, not the original 5s: a loaded/nested-virtualized host can leave
	# a SIGKILLed process in an uninterruptible wait noticeably longer than
	# that, and the old behavior here (warn and return 0 anyway once the
	# timeout hit) is exactly how that became dangerous rather than just
	# slow -- a caller that proceeds to overwrite xfce4-panel.xml and
	# launch a new panel while the old one is *actually* still alive is
	# racing that old process's own eventual, arbitrarily-delayed exit,
	# which can re-persist its stale in-memory plugin config back over the
	# fresh write once it does finally die (same class of clobber as the
	# `-r` flag and the graceful-exit case above, just via a slower fuse).
	# Caught 2026-09-20 on tower's Cyberbeest-VM: both
	# 11a-clipboard-status.sh's and 12-xfce-panel-layout.sh's reloads hit
	# the old 5s ceiling on the same run (visible in their logs), and the
	# panel's on-disk config ended up missing several plugin ids (12, 13,
	# 14, and the new 19) that the freshly-written file and the template
	# both had -- consistent with exactly this delayed stale write-back,
	# not a bug in the write itself. Also re-asserts SIGKILL each loop
	# iteration (cheap, and covers a process that appeared between the
	# initial pkill and this loop, e.g. a respawn racing the kill) rather
	# than trusting the single initial signal was enough.
	#
	# Returns 1 instead of warning-and-returning-0 if still not confirmed
	# gone after the full wait -- every caller runs under `set -e` and
	# calls this bare (no `||`), so that now actually stops the script
	# instead of letting it continue on top of an unconfirmed kill.
	local waited=0 pids
	while true; do
		pids="$(pgrep -u "$TARGET_USER" -x xfce4-panel)" || true
		[ -z "$pids" ] && return 0
		if [ "$waited" -ge 60 ]; then
			echo "--- error: xfce4-panel (pid(s): $pids) still running 30s after SIGKILL -- refusing to proceed, since it could still overwrite fresh config whenever it does eventually die ---" >&2
			return 1
		fi
		# shellcheck disable=SC2086
		kill -9 $pids 2>/dev/null || true
		sleep 0.5
		waited=$((waited + 1))
	done
}

xfce_panel_kill_xfconfd() {
	# For a caller that overwrites a channel's xfce-perchannel-xml file
	# directly on disk (xfce4-panel.xml via `install`/`sed -i`, bypassing
	# xfconf-query entirely) rather than going through xfconfd. xfconfd
	# loads a channel into memory once (at its own startup, or the first
	# time something asks for that channel) and has no file-watch on
	# external edits to the XML -- it's the normal sole writer, so nothing
	# tells it to notice a change made behind its back. A periodic flush of
	# its own still-stale in-memory state back to disk can then silently
	# clobber the fresh write moments later, even though a subsequent panel
	# reload looks completely clean (xfce_panel_launch's checks are
	# liveness-only: they confirm a new xfce4-panel process came up and
	# stayed up, not that xfconfd actually served it the values from the
	# file just written rather than its stale cache).
	#
	# This is the opposite caution from xfce_panel_kill's own "deliberately
	# does NOT touch xfconfd" -- that one is about not racing an in-flight
	# WRITE going *through* the daemon (xfconf-query), which could be lost
	# if xfconfd dies before its async disk flush. This is about a write
	# that goes *around* the daemon, where xfconfd has to be forced to
	# re-read the file instead of serving whatever it already has cached.
	# Confirmed 2026-09-20: reproduced the exact missing-plugin-ids symptom
	# already on file in xfce_panel_kill's own history (12/13/14/19 -- see
	# its comment), traced it to this, and confirmed the fix: kill xfconfd
	# too, right alongside the panel, whenever the caller wrote the XML
	# file directly. D-Bus activation respawns xfconfd automatically the
	# next time something asks for a channel, reading the current file at
	# that fresh startup -- callers should do this before the "remove stray
	# panels" xfconf-query calls and the final xfce_panel_launch, so both
	# see the freshly-written file, not a stale cache.
	pkill -9 -u "$TARGET_USER" -x xfconfd || true

	local waited=0
	while pgrep -u "$TARGET_USER" -x xfconfd >/dev/null 2>&1; do
		if [ "$waited" -ge 20 ]; then
			echo "--- error: xfconfd still running 10s after SIGKILL -- refusing to proceed, since it could still serve stale cached values to whatever asks next ---" >&2
			return 1
		fi
		sleep 0.5
		waited=$((waited + 1))
	done
}

xfce_panel_launch() {
	local old_pid="${XFCE_PANEL_PID:-}"

	# Re-export the full XDG_*/DESKTOP_SESSION set captured in
	# xfce_panel_dbus_addr (from xfce4-session, not just DISPLAY and the
	# D-Bus address) so apps launched from the relaunched panel see the
	# same environment LightDM set up at login -- see that function's
	# comment for why this matters (Electron's keyring-backend detection
	# in particular).
	local env_assignments="" kv
	for kv in "${XFCE_SESSION_ENV[@]:-}"; do
		[ -n "$kv" ] || continue
		env_assignments+="$(printf '%q ' "$kv")"
	done

	su - "$TARGET_USER" -c "DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$XFCE_PANEL_DBUS_ADDR' ${env_assignments}setsid xfce4-panel >/dev/null 2>&1 < /dev/null &"

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

	# Keep watching a while longer: xfce4-panel's stock launcher plugin
	# (liblauncher.so) sporadically segfaults a few seconds into a panel
	# start -- a null-pointer read at the same offset every time, seen on
	# tower since 2026-09-11 and on .76 on 2026-09-25 right after this
	# reload -- and nothing respawns the panel after that. A fresh start
	# has worked every time, so one retry; not more, so a panel that
	# crashes for some other reason can't loop.
	local watched=0
	while [ "$watched" -lt 20 ]; do
		sleep 0.5
		watched=$((watched + 1))
		pgrep -u "$TARGET_USER" -x xfce4-panel >/dev/null && continue
		if [ "${_XFCE_PANEL_RETRYING:-}" = 1 ]; then
			echo "--- warning: xfce4-panel crashed again right after the retry ---" >&2
			return 1
		fi
		echo "--- xfce4-panel crashed during startup (the known liblauncher.so segfault?) -- starting it once more ---" >&2
		_XFCE_PANEL_RETRYING=1 XFCE_PANEL_PID="" xfce_panel_launch
		return
	done
}
