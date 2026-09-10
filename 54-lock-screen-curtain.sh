#!/bin/bash
# Installs the lock-screen-curtain user service: covers the screen with an
# opaque window the instant the screen locks, closing the brief window
# where the desktop can still be visible before xfce4-screensaver's own
# password dialog has painted over it. Toggle is CURTAIN_ENABLED in
# ~/.config/cyberbeest/power-settings.conf (default true), surfaced as a
# checkbox in the Extended Power Options dialog (see
# lib/lock-power-saving-dialog.py). See lib/lock-screen-curtain.sh.
# Idempotent: safe to re-run.
#
# Bumped 2026-09-10: lib/lock-screen-curtain.sh's watchdog fail-safe used a
# plain shell variable (curtain_state) shared between two subshells (the
# backgrounded watchdog function and the dbus-monitor pipeline's `while
# read` loop) that don't actually share variables -- each got its own
# copy, so the watchdog's belief of the state could get stuck and never
# fire. Switched to a state file so both see the same value.
#
# Also bumped same day: the curtain was sized via `xdotool
# getdisplaygeometry`, which reports the primary monitor's resolution, not
# the full virtual desktop -- on a dual-monitor setup this left the
# secondary monitor mostly uncovered. Switched to `xwininfo -root`, which
# reports the real root window size spanning every output.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/54-lock-screen-curtain.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing lock-screen-curtain ==="

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
TARGET_UID="$(id -u "$TARGET_USER")"

echo "--- Installing dependencies (xterm, xdotool, dbus-send/dbus-monitor, wmctrl, xprop) ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y xterm xdotool dbus-bin wmctrl x11-utils

echo "--- Installing curtain script to $TARGET_HOME/bin/lock-screen-curtain.sh ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/lock-screen-curtain.sh" "$TARGET_HOME/bin/lock-screen-curtain.sh"

echo "--- Installing systemd user unit ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/systemd/user"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/lock-screen-curtain.service" \
	"$TARGET_HOME/.config/systemd/user/lock-screen-curtain.service"

echo "--- Enabling the unit (WantedBy=default.target) ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/systemd/user/default.target.wants"
ln -sf ../lock-screen-curtain.service \
	"$TARGET_HOME/.config/systemd/user/default.target.wants/lock-screen-curtain.service"
chown -h "$TARGET_USER:$TARGET_USER" \
	"$TARGET_HOME/.config/systemd/user/default.target.wants/lock-screen-curtain.service"

echo "--- Starting it now, if the target user has an active session ---"
if [ -d "/run/user/$TARGET_UID" ]; then
	sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" \
		systemctl --user daemon-reload
	sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" \
		systemctl --user restart lock-screen-curtain.service || true
else
	echo "no active session for $TARGET_USER -- it'll start at next login"
fi

echo "=== $(date) : done ==="
