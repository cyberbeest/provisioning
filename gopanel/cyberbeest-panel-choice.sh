#!/bin/bash
# Which panel runs: the stock XFCE panel or gopanel.
#   cyberbeest-panel-choice.sh set xfce|gopanel   remember the choice and switch now
#   cyberbeest-panel-choice.sh login              apply the remembered choice (autostart)
#   cyberbeest-panel-choice.sh status             print the remembered choice
#
# xfce-panel-watchdog relaunches a dead xfce4-panel, unless the stop marker below
# exists (see lib/xfce-panel-watchdog.sh). So: gopanel = marker + xfce4-panel
# stopped; xfce = marker removed (the watchdog brings the panel back) + gopanel quit.
# The panel that takes over is always up before the other one is stopped.
# With no saved choice gopanel runs; if it is missing or fails to start, the XFCE panel stays.

CONF="$HOME/.config/cyberbeest/panel.conf"
MARKER="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/cyberbeest-xfce-panel-stopped"
LOG="${XDG_RUNTIME_DIR:-/tmp}/cyberbeest-panel-choice.log"
[ "$1" = status ] || exec >>"$LOG" 2>&1
export DISPLAY="${DISPLAY:-:0}" XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"

gopanel_bin() {
	for p in "$GOPANEL_BIN" "$(command -v gopanel)" "$HOME/.local/bin/gopanel" "$HOME/claude/gopanel/gopanel"; do
		[ -n "$p" ] && [ -x "$p" ] && { echo "$p"; return 0; }
	done
	return 1
}

# Own transient unit, so the panel outlives whoever launched us (settings window,
# autostart) -- same reason xfce-panel-watchdog uses systemd-run.
# KillMode=process is essential: every app started from the panel (Firefox, ...) lives in
# this unit's cgroup, and the default (control-group) SIGKILLs all of them the moment the
# panel exits -- on a panel switch, a crash, or a restart.
launch() {
	systemd-run --user --collect --quiet --unit="panel-choice-$(date +%s%N)" -p KillMode=process \
		--setenv=DISPLAY --setenv=XAUTHORITY --setenv=XDG_CURRENT_DESKTOP --setenv=XDG_SESSION_TYPE \
		-- "$@"
}

wait_for() { # wait_for <seconds> <process name>
	for _ in $(seq $(($1 * 2))); do
		pgrep -x "$2" >/dev/null && return 0
		sleep 0.5
	done
	return 1
}

use_gopanel() {
	local bin
	bin="$(gopanel_bin)" || { echo "gopanel binary not found"; return 1; }
	pgrep -x gopanel >/dev/null || launch "$bin"
	wait_for 10 gopanel || { echo "gopanel did not start, keeping the XFCE panel"; return 1; }
	# Keep the XFCE panel until gopanel's window is really on screen, then only a short grace, so the
	# stock panel is never visible alone and never lingers beside gopanel.
	for _ in $(seq 20); do
		xwininfo -root -tree 2>/dev/null | grep -q '"gopanel"' && break
		sleep 0.25
	done
	sleep 0.3
	touch "$MARKER"
	pgrep -x xfce4-panel >/dev/null && xfce4-panel --quit
	return 0
}

use_xfce() {
	# gopanel owns the XEmbed tray selection; xfce4-panel's systray does not retry, so
	# release it before the panel starts.
	pgrep -x gopanel >/dev/null && "$(gopanel_bin)" yield
	sleep 0.5
	rm -f "$MARKER"
	wait_for 8 xfce4-panel || launch xfce4-panel # the watchdog normally does this within 5 s
	wait_for 10 xfce4-panel
	sleep 2
	pgrep -x gopanel >/dev/null && "$(gopanel_bin)" quit
}

# gopanel is the default; only an explicit PANEL=xfce (picked in Settings > Panel) keeps the XFCE panel.
saved() { [ "$(sed -n 's/^PANEL=//p' "$CONF" 2>/dev/null | tail -1)" = xfce ] && echo xfce || echo gopanel; }

save() { # keeps the other settings in the file (MONITOR=...)
	mkdir -p "$(dirname "$CONF")"
	{ echo "PANEL=$1"; grep -v '^PANEL=' "$CONF" 2>/dev/null || true; } >"$CONF.new" && mv "$CONF.new" "$CONF"
}

echo "== $(date) $*"
case "$1" in
set)
	case "$2" in
	gopanel) use_gopanel && save gopanel ;;
	xfce) save xfce; use_xfce ;;
	*) echo "usage: $0 set xfce|gopanel" >&2; exit 2 ;;
	esac ;;
login)
	if [ "$(saved)" = gopanel ]; then
		# The session starts xfce4-panel before this autostart entry runs, so it shows briefly. Start
		# gopanel at once, in parallel with the wait below, to keep that overlap as short as possible.
		bin="$(gopanel_bin)" && { pgrep -x gopanel >/dev/null || launch "$bin"; }
		# systemd-run returns before the process exists, so without this wait use_gopanel's own
		# `pgrep -x gopanel || launch` can fire a second instance (seen: two panel-choice-*.service
		# units 70 ms apart, which split the SNI watcher / XEmbed tray roles and left Telegram without
		# a tray icon).
		wait_for 10 gopanel
		wait_for 40 xfce4-panel # the session starts it; stopping it before it exists would not stick
		use_gopanel || rm -f "$MARKER"
	fi ;;
status) saved ;;
*) echo "usage: $0 set xfce|gopanel | login | status" >&2; exit 2 ;;
esac
