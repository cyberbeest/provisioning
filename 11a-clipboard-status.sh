#!/bin/bash
# Installs the clipboard-status panel icon: a genmon widget (plugin-19,
# which 12-xfce-panel-layout.sh's template wires into the panel right
# before the clock) that shows what type of content currently sits in the
# X11 clipboard (text/image/files/empty), with a click-menu to view/edit/
# clear it and an auto-clear timer that wipes the clipboard after a
# configurable delay (default 15 minutes). Security rationale: any app can
# read the clipboard, so a breached app is an instant leak of whatever's
# sitting there -- this makes that exposure visible instead of invisible,
# and bounds how long it lasts. See lib/clipboard-watcher.sh,
# lib/clipboard-status-genmon.sh, lib/clipboard-status-menu.py,
# lib/clipboard-status-viewer.py, lib/clipboard-show-image.py,
# lib/clipboard-auto-clear-settings.py.
#
# Runs as 11a (right after 11-xfce-panel-plugins.sh, before 12-xfce-panel-
# layout.sh) rather than after 12, on the same principle 11 itself follows:
# a plugin's script/binary needs to already exist on disk before the
# layout script wires it into the panel's xfconf and reloads, or the first
# reload shows an empty placeholder "(genmon)" icon until something reloads
# the panel again later. 12-xfce-panel-layout.sh depends on this script
# having already run, not the other way around.
#
# Event-driven, not polled: lib/clipnotify.c is a small XFixes-based
# selection-change listener (the real `clipnotify` tool isn't packaged for
# Debian, but only needs libx11-dev/libxfixes-dev), compiled here since the
# X11/xfce4-panel plugin ABI it links against is tied to what's installed
# on the target. clipboard-watcher.sh loops it with a 60s timeout as a slow
# poll fallback in case an event is ever missed.
#
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/11a-clipboard-status.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing clipboard-status panel icon ==="

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
TARGET_UID="$(id -u "$TARGET_USER")"

# Must match the plugin-ids/xfce4-panel.xml.template slot 12-xfce-panel-
# layout.sh reserves for this widget.
GENMON_WIDGET="genmon-19"

echo "--- Installing build dependencies (clipnotify needs libx11/libxfixes headers) ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y build-essential libx11-dev libxfixes-dev xclip

echo "--- Building clipnotify ---"
BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "$BUILD_DIR"' EXIT
gcc -O2 -o "$BUILD_DIR/clipnotify" "$DIR/lib/clipnotify.c" -lX11 -lXfixes

echo "--- Installing scripts to $TARGET_HOME/.local/bin ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$BUILD_DIR/clipnotify" "$TARGET_HOME/.local/bin/clipnotify"
sed "s|__GENMON_WIDGET__|$GENMON_WIDGET|g" "$DIR/lib/clipboard-watcher.sh" \
	> "$TARGET_HOME/.local/bin/clipboard-watcher.sh"
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/bin/clipboard-watcher.sh"
chmod 755 "$TARGET_HOME/.local/bin/clipboard-watcher.sh"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/clipboard-status-genmon.sh" "$TARGET_HOME/.local/bin/clipboard-status-genmon.sh"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/clipboard-status-menu.py" "$TARGET_HOME/.local/bin/clipboard-status-menu.py"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/clipboard-status-viewer.py" "$TARGET_HOME/.local/bin/clipboard-status-viewer.py"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/clipboard-show-image.py" "$TARGET_HOME/.local/bin/clipboard-show-image.py"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/clipboard-auto-clear-settings.py" "$TARGET_HOME/.local/bin/clipboard-auto-clear-settings.py"

# i18n.sh/i18n.py only resolve their catalogs relative to their own
# location, so both need a copy next to the scripts installed here too --
# same per-installed-directory duplication convention as
# 12-xfce-panel-layout.sh and 13a-lock-warning-watcher.sh.
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR/lib/i18n.sh" "$TARGET_HOME/.local/bin/i18n.sh"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR/lib/i18n.py" "$TARGET_HOME/.local/bin/i18n.py"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin/i18n"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/i18n/strings.en.sh" "$DIR/lib/i18n/strings.de.sh" \
	"$DIR/lib/i18n/strings_en.py" "$DIR/lib/i18n/strings_de.py" \
	"$TARGET_HOME/.local/bin/i18n/"

echo "--- Installing systemd user unit ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/systemd/user"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/clipboard-watcher.service" \
	"$TARGET_HOME/.config/systemd/user/clipboard-watcher.service"

echo "--- Enabling the unit (WantedBy=default.target) ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/systemd/user/default.target.wants"
ln -sf ../clipboard-watcher.service \
	"$TARGET_HOME/.config/systemd/user/default.target.wants/clipboard-watcher.service"
chown -h "$TARGET_USER:$TARGET_USER" \
	"$TARGET_HOME/.config/systemd/user/default.target.wants/clipboard-watcher.service"

echo "--- Writing $GENMON_WIDGET.rc ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/xfce4/panel"
sed "s|__HOME__|$TARGET_HOME|g" "$DIR/lib/xfce-panel-layout/clipboard-status-genmon.rc.template" \
	> "$TARGET_HOME/.config/xfce4/panel/$GENMON_WIDGET.rc"
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.config/xfce4/panel/$GENMON_WIDGET.rc"

echo "--- Starting the watcher now, if the target user has an active session ---"
if [ -d "/run/user/$TARGET_UID" ]; then
	sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" \
		systemctl --user daemon-reload
	sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" \
		systemctl --user restart clipboard-watcher.service || true
else
	echo "no active session for $TARGET_USER -- it'll start at next login"
fi

# plugin-19 isn't in the panel's plugin-ids yet at this point (12-xfce-
# panel-layout.sh hasn't run), so this reload won't show the icon -- kept
# anyway for the same reason 11-xfce-panel-plugins.sh's own end-of-script
# reload is harmless-but-early for its plugins too: consistent habit,
# and it means a fresh xfce4-panel process has nothing stale cached from
# before rc/systemd-unit files existed once 12 does its own reload.
echo "--- Reloading xfce4-panel for the logged-in user, if one is running ---"
. "$DIR/lib/xfce-panel-reload.sh"
if xfce_panel_dbus_addr; then
	xfce_panel_kill
	xfce_panel_launch || echo "--- warning: panel reload didn't take live effect ---" >&2
fi

echo "=== $(date) : done ==="
