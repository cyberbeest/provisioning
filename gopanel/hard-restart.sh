#!/bin/bash
# Cold-start test for gopanel: quit it (helpers and tray icons go with it), wait, start it
# again in its own unit (like autostart does). Unlike `gopanel restart` (exec, same pid, helpers survive)
# this shows the real startup: helper spawn delay, tray docking, recorded widths.
#   hard-restart.sh [delay-seconds]     default 3; keep it under ~10 (watchdog brings XFCE back at 15)
DELAY="${1:-3}"
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
GOPANEL="$DIR/gopanel"
[ -x "$GOPANEL" ] || GOPANEL="$(command -v gopanel)"
export DISPLAY="${DISPLAY:-:0}"

"$GOPANEL" quit
for _ in $(seq 20); do pgrep -x gopanel >/dev/null || break; sleep 0.25; done
pkill -x kitt; pkill -x io-scanner; pkill -x network-scanner; pkill -x mem-liquid; pkill -x wattage-panel
echo "panel stopped, starting again in ${DELAY}s..."
sleep "$DELAY"
# Straight into its own transient unit, as panel-choice's launch() does. Not via
# `panel-choice login`: that waits for xfce4-panel to exist first (it is stopped on purpose),
# and the watchdog brings the XFCE panel back if gopanel is gone for ~15 s, which flashed
# the old panel at the top of the screen.
exec systemd-run --user --collect --quiet --unit="panel-choice-$(date +%s%N)" -p KillMode=process \
	--setenv=DISPLAY --setenv=XAUTHORITY --setenv=XDG_CURRENT_DESKTOP --setenv=XDG_SESSION_TYPE \
	-- "$GOPANEL"
