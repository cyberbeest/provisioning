#!/bin/bash
# NOTE: if xfce-panel-watchdog.service is already installed and running
# from an earlier version of this script, re-running it will pick up a
# fixed lib/xfce-panel-watchdog.sh -- the very first version launched the
# relaunched xfce4-panel in a way that nested it (and every plugin) inside
# this service's own cgroup, so a later `systemctl --user restart
# xfce-panel-watchdog.service` would have killed the live panel right
# along with it. Confirmed live 2026-09-25 and fixed the same day (dropped
# a stray `setsid` in the systemd-run relaunch command -- see that file's
# own comment). Any machine that got the first version needs this
# re-installed once to pick up the fix.
#
# Installs the xfce-panel-watchdog user service: polls for xfce4-panel and
# relaunches it if it ever crashes on its own (the known liblauncher.so
# segfault -- see lib/xfce-panel-reload.sh's xfce_panel_launch -- or any
# other cause). No new packages needed (bash/pgrep/flock/systemd are all
# already present). See lib/xfce-panel-watchdog.sh for the coordination
# with 11-/12-'s own reloads and the i2pd/vpn/dot panel-icon toggles, all
# of which now flock the same lock file this watchdog does.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/60-xfce-panel-watchdog.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing xfce-panel-watchdog ==="

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
TARGET_UID="$(id -u "$TARGET_USER")"

echo "--- Installing watchdog script to $TARGET_HOME/bin/xfce-panel-watchdog.sh ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/xfce-panel-watchdog.sh" "$TARGET_HOME/bin/xfce-panel-watchdog.sh"

echo "--- Installing systemd user unit ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/systemd/user"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/xfce-panel-watchdog.service" \
	"$TARGET_HOME/.config/systemd/user/xfce-panel-watchdog.service"

echo "--- Enabling the unit (WantedBy=default.target) ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/systemd/user/default.target.wants"
ln -sf ../xfce-panel-watchdog.service \
	"$TARGET_HOME/.config/systemd/user/default.target.wants/xfce-panel-watchdog.service"
chown -h "$TARGET_USER:$TARGET_USER" \
	"$TARGET_HOME/.config/systemd/user/default.target.wants/xfce-panel-watchdog.service"

echo "--- Starting it now, if the target user has an active session ---"
if [ -d "/run/user/$TARGET_UID" ]; then
	sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" \
		systemctl --user daemon-reload
	sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" \
		systemctl --user restart xfce-panel-watchdog.service || true
else
	echo "no active session for $TARGET_USER -- it'll start at next login"
fi

echo "=== $(date) : done ==="
