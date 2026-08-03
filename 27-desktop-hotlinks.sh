#!/bin/bash
# Desktop hotlinks: adds Pictures and Downloads folder icons to the desktop,
# and turns off the "File System" special icon -- opening / is scary
# territory for a normal user and isn't something they need one click away.
#
# These are .desktop Link launchers (Type=Link, Icon=folder-pictures/
# folder-download), not plain symlinks -- a plain symlink renders with a
# distracting "shortcut arrow" emblem, whereas a Link launcher shows the
# clean themed folder icon instead (same look as the built-in Home icon).
# GIO only trusts a .desktop file's declared Icon/Name once it's marked
# metadata::trusted (an anti-icon-spoofing check); without it, both Thunar
# and xfdesktop fall back to a generic document icon, so this sets that
# xattr via `gio set` after writing each file.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/27-desktop-hotlinks.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing desktop hotlinks ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
TARGET_UID="$(id -u "$TARGET_USER")"
HAVE_SESSION=0
if [ -d "/run/user/$TARGET_UID" ]; then
	HAVE_SESSION=1
	DBUS_ADDR="unix:path=/run/user/$TARGET_UID/bus"
fi

echo "--- Adding Pictures and Downloads link launchers to the desktop ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/Desktop"

write_desktop_link() {
	local name="$1" icon="$2" target="$3" dest="$TARGET_HOME/Desktop/$1.desktop"
	sudo -u "$TARGET_USER" tee "$dest" >/dev/null <<-EOF
	[Desktop Entry]
	Type=Link
	Name=$name
	Icon=$icon
	URL=file://$target
	EOF
	chmod 755 "$dest"
	if [ "$HAVE_SESSION" -eq 1 ]; then
		sudo -u "$TARGET_USER" DBUS_SESSION_BUS_ADDRESS="$DBUS_ADDR" gio set "$dest" "metadata::trusted" yes
	else
		echo "no active session for $TARGET_USER -- can't mark $name.desktop trusted yet;" \
			"it'll show a generic icon until re-run (or right-clicked -> Allow Launching) once logged in"
	fi
}

write_desktop_link "Pictures" "folder-pictures" "$TARGET_HOME/Pictures"
write_desktop_link "Downloads" "folder-download" "$TARGET_HOME/Downloads"

echo "--- Hiding the 'File System' special icon (leaves Home/Trash alone) ---"
if [ "$HAVE_SESSION" -eq 1 ]; then
	sudo -u "$TARGET_USER" DBUS_SESSION_BUS_ADDRESS="$DBUS_ADDR" \
		xfconf-query -c xfce4-desktop -p /desktop-icons/file-icons/show-filesystem \
		-n -t bool -s false
else
	echo "no active session for $TARGET_USER -- xfconf needs a running session, skipping;" \
		"re-run this script (or set it by hand) once logged in"
fi

echo "=== $(date) : done ==="
