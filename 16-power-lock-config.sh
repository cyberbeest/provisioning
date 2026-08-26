#!/bin/bash
# Installs this machine's power-manager and screen-lock settings: display
# sleeps after 5 minutes idle and turns off after 6 (DPMS), the screen
# locks after 5 minutes idle, brightness reduction on inactivity is
# disabled outright (found enabled by default on a fresh install,
# dimming the screen ahead of the actual lock), and there's no separate
# system auto-suspend (that's handled by lock-shutdown-watcher.sh instead)
# -- see lib/xfce-perchannel-xml/xfce4-power-manager.xml and
# xfce4-screensaver.xml.
# Also disables light-locker's autostart: it's pulled in as an xfce4-session
# recommend, and having it running alongside xfce4-screensaver makes both
# fight over the lock/unlock X grab -- intermittently leaving the unlock
# dialog's password field unable to take keyboard focus.
# Idempotent: safe to re-run (backs up any pre-existing config the first
# time, as *.pre-cyberbeest). A live session needs to log out/in (or
# reboot) to pick this up -- unlike the panel, these aren't reloaded live.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/16-power-lock-config.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing power/screen-lock config ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
XML_DIR="$TARGET_HOME/.config/xfce4/xfconf/xfce-perchannel-xml"

echo "--- Installing xfce4-power-manager and xfce4-screensaver ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y xfce4-power-manager xfce4-screensaver

echo "--- Installing xfconf channel files ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$XML_DIR"
for channel in xfce4-power-manager xfce4-screensaver; do
	dest="$XML_DIR/$channel.xml"
	if [ -e "$dest" ] && [ ! -e "$dest.pre-cyberbeest" ]; then
		cp "$dest" "$dest.pre-cyberbeest"
	fi
	install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
		"$DIR/lib/xfce-perchannel-xml/$channel.xml" "$dest"
done

echo "--- Disabling light-locker autostart (xfce4-screensaver is the locker) ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/autostart"
cat > "$TARGET_HOME/.config/autostart/light-locker.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Screen Locker
Exec=light-locker
NoDisplay=true
Hidden=true
EOF
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.config/autostart/light-locker.desktop"
pkill -u "$TARGET_USER" -x light-locker || true

echo "=== $(date) : done ==="
