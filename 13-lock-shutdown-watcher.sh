#!/bin/bash
# Installs the lock-shutdown-watcher user service: shuts the machine down
# after the screen has stayed continuously locked for SHUTDOWN_MINUTES
# (default 60), reading that from ~/.config/cyberbeest/power-settings.conf --
# the file the shutdown-timer panel icon's menu edits (see
# 12-xfce-panel-layout.sh, lib/shutdown-timer-menu.py). See
# lib/lock-shutdown-watcher.sh.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/13-lock-shutdown-watcher.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing lock-shutdown-watcher ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
TARGET_UID="$(id -u "$TARGET_USER")"

echo "--- Installing dependencies (xprintidle, dbus-send, xset) ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y xprintidle dbus-bin x11-xserver-utils

echo "--- Installing watcher script to $TARGET_HOME/bin/lock-shutdown-watcher.sh ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/lock-shutdown-watcher.sh" "$TARGET_HOME/bin/lock-shutdown-watcher.sh"

echo "--- Installing systemd user unit ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/systemd/user"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/lock-shutdown-watcher.service" \
	"$TARGET_HOME/.config/systemd/user/lock-shutdown-watcher.service"

echo "--- Enabling the unit (WantedBy=default.target) ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/systemd/user/default.target.wants"
ln -sf ../lock-shutdown-watcher.service \
	"$TARGET_HOME/.config/systemd/user/default.target.wants/lock-shutdown-watcher.service"
chown -h "$TARGET_USER:$TARGET_USER" \
	"$TARGET_HOME/.config/systemd/user/default.target.wants/lock-shutdown-watcher.service"

echo "--- Starting it now, if the target user has an active session ---"
if [ -d "/run/user/$TARGET_UID" ]; then
	sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" \
		systemctl --user daemon-reload
	sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" \
		systemctl --user restart lock-shutdown-watcher.service || true
else
	echo "no active session for $TARGET_USER -- it'll start at next login"
fi

echo "=== $(date) : done ==="
