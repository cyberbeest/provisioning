#!/bin/bash
# Desktop hotlinks: adds Pictures and Downloads folder icons to the desktop
# (as symlinks in ~/Desktop, which xfdesktop renders like any other icon),
# and turns off the "File System" special icon -- opening / is scary
# territory for a normal user and isn't something they need one click away.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/27-desktop-hotlinks.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing desktop hotlinks ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
TARGET_UID="$(id -u "$TARGET_USER")"

echo "--- Symlinking Pictures and Downloads onto the desktop ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/Desktop"
sudo -u "$TARGET_USER" ln -sfn "$TARGET_HOME/Pictures" "$TARGET_HOME/Desktop/Pictures"
sudo -u "$TARGET_USER" ln -sfn "$TARGET_HOME/Downloads" "$TARGET_HOME/Desktop/Downloads"

echo "--- Hiding the 'File System' special icon (leaves Home/Trash alone) ---"
if [ -d "/run/user/$TARGET_UID" ]; then
	sudo -u "$TARGET_USER" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$TARGET_UID/bus" \
		xfconf-query -c xfce4-desktop -p /desktop-icons/file-icons/show-filesystem \
		-n -t bool -s false
else
	echo "no active session for $TARGET_USER -- xfconf needs a running session, skipping;" \
		"re-run this script (or set it by hand) once logged in"
fi

echo "=== $(date) : done ==="
