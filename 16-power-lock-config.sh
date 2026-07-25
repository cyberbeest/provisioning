#!/bin/bash
# Installs this machine's power-manager and screen-lock settings: display
# sleeps after 6 minutes idle and turns off after 7 (DPMS), the screen
# locks after 5 minutes idle, and there's no separate system auto-suspend
# (that's handled by lock-shutdown-watcher.sh instead) -- see
# lib/xfce-perchannel-xml/xfce4-power-manager.xml and xfce4-screensaver.xml.
# Idempotent: safe to re-run (backs up any pre-existing config the first
# time, as *.pre-cyberbeest). A live session needs to log out/in (or
# reboot) to pick this up -- unlike the panel, these aren't reloaded live.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/16-power-lock-config.log"
exec > "$LOG" 2>&1

echo "=== $(date) : installing power/screen-lock config ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
XML_DIR="$TARGET_HOME/.config/xfce4/xfconf/xfce-perchannel-xml"

echo "--- Installing xfce4-power-manager and xfce4-screensaver ---"
apt-get update -qq
apt-get install -y xfce4-power-manager xfce4-screensaver

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

echo "=== $(date) : done ==="
