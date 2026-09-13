#!/bin/bash
# Installs the lock-warning-watcher user service: pops a desktop
# notification WARN_SECONDS_BEFORE_LOCK seconds (default 10) before
# xfce4-screensaver's own idle timer locks the screen, so a still-present
# user gets a chance to wiggle the mouse instead of getting locked out --
# reading the setting from ~/.config/cyberbeest/power-settings.conf, the
# file lock-power-saving-dialog.py's "Extended Power Options" window edits.
# See lib/lock-warning-watcher.sh.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/13a-lock-warning-watcher.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing lock-warning-watcher ==="

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
TARGET_UID="$(id -u "$TARGET_USER")"

echo "--- Installing dependencies (xprintidle, dbus-send, libnotify-bin) ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y xprintidle dbus-bin libnotify-bin

echo "--- Installing watcher script to $TARGET_HOME/bin/lock-warning-watcher.sh ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/lock-warning-watcher.sh" "$TARGET_HOME/bin/lock-warning-watcher.sh"

# i18n.sh only resolves lib/i18n/ relative to its own location, so it and its
# catalogs need to live next to the installed script too -- see lib/i18n.sh.
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/i18n.sh" "$TARGET_HOME/bin/i18n.sh"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/bin/i18n"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/i18n/strings.en.sh" "$DIR/lib/i18n/strings.de.sh" \
	"$TARGET_HOME/bin/i18n/"

echo "--- Installing systemd user unit ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/systemd/user"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/lock-warning-watcher.service" \
	"$TARGET_HOME/.config/systemd/user/lock-warning-watcher.service"

echo "--- Enabling the unit (WantedBy=default.target) ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/systemd/user/default.target.wants"
ln -sf ../lock-warning-watcher.service \
	"$TARGET_HOME/.config/systemd/user/default.target.wants/lock-warning-watcher.service"
chown -h "$TARGET_USER:$TARGET_USER" \
	"$TARGET_HOME/.config/systemd/user/default.target.wants/lock-warning-watcher.service"

echo "--- Starting it now, if the target user has an active session ---"
if [ -d "/run/user/$TARGET_UID" ]; then
	sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" \
		systemctl --user daemon-reload
	sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" \
		systemctl --user restart lock-warning-watcher.service || true
else
	echo "no active session for $TARGET_USER -- it'll start at next login"
fi

echo "=== $(date) : done ==="
