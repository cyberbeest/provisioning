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

CONF="$HOME/.config/cyberbeest/panel.conf"
MARKER="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/cyberbeest-xfce-panel-stopped"
LOG="${XDG_RUNTIME_DIR:-/tmp}/cyberbeest-panel-choice.log"
[ "$1" = status ] || exec >>"$LOG" 2>&1
export DISPLAY="${DISPLAY:-:0}" XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"

gopanel_bin() {
	for p in "$GOPANEL_BIN" "$(command -v gopanel)" "$HOME/claude/gopanel/gopanel"; do
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
	sleep 1.5 # let it map its window before the other panel goes away
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

saved() { grep -qx 'PANEL=gopanel' "$CONF" 2>/dev/null && echo gopanel || echo xfce; }

save() {
	mkdir -p "$(dirname "$CONF")"
	echo "PANEL=$1" >"$CONF"
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
		wait_for 40 xfce4-panel # the session starts it; stopping it before it exists would not stick
		use_gopanel || rm -f "$MARKER"
	fi ;;
status) saved ;;
*) echo "usage: $0 set xfce|gopanel | login | status" >&2; exit 2 ;;
esac
