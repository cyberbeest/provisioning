#!/bin/bash
# Desktop hotlinks: adds Pictures and Downloads folder icons to the desktop
# and to the file manager's Places sidebar, and turns off the "File System"
# special desktop icon -- opening / is scary territory for a normal user and
# isn't something they need one click away.
#
# The desktop icons are .desktop Link launchers (Type=Link, Icon=folder-
# pictures/folder-download) rather than plain symlinks, so they get the
# clean themed folder icon instead of a symlink's shortcut-arrow badge.
# That alone isn't enough though: Thunar/xfdesktop show an "Untrusted link
# launcher" security dialog on open unless the file's trust is established,
# and the generic GIO attribute (metadata::trusted, set via `gio set`) does
# NOT do that for these -- confirmed (2026-08-03) that clicking "Mark As
# Secure And Launch" in that dialog doesn't persist anything (the gvfs
# metadata store on disk was untouched by it, checked via mtime). The
# attribute that actually works is XFCE's own checksum-based trust,
# metadata::xfce-exe-checksum -- a sha256 of the launcher file's own
# content, the same mechanism used by the desktop's stock Terminal Emulator
# launcher (verified by inspecting its metadata). xfdesktop/Thunar recompute
# the checksum on open and compare; matching it means no relaunch/prompt.
# If the launcher's content ever changes, the checksum must be recomputed
# and reset, or the trust breaks again -- this script always does both
# together so they can't drift apart.
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
	local name="$1" icon="$2" target="$3" dest="$TARGET_HOME/Desktop/$1.desktop" sum
	sudo -u "$TARGET_USER" tee "$dest" >/dev/null <<-EOF
	[Desktop Entry]
	Type=Link
	Name=$name
	Icon=$icon
	URL=file://$target
	EOF
	chmod 755 "$dest"
	sum="$(sha256sum "$dest" | cut -d' ' -f1)"
	if [ "$HAVE_SESSION" -eq 1 ]; then
		sudo -u "$TARGET_USER" DBUS_SESSION_BUS_ADDRESS="$DBUS_ADDR" \
			gio set "$dest" metadata::xfce-exe-checksum "$sum"
	else
		echo "no active session for $TARGET_USER -- can't mark $name.desktop trusted yet;" \
			"it'll prompt an 'Untrusted link launcher' dialog on first open until re-run" \
			"(or right-clicked -> Mark As Secure And Launch, once) once logged in"
	fi
}

write_desktop_link "Pictures" "folder-pictures" "$TARGET_HOME/Pictures"
write_desktop_link "Downloads" "folder-download" "$TARGET_HOME/Downloads"

echo "--- Adding Pictures and Downloads to the file manager's Places sidebar ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/gtk-3.0"
BOOKMARKS="$TARGET_HOME/.config/gtk-3.0/bookmarks"
sudo -u "$TARGET_USER" touch "$BOOKMARKS"
for entry in "Pictures" "Downloads"; do
	line="file://$TARGET_HOME/$entry $entry"
	if ! grep -qxF "$line" "$BOOKMARKS"; then
		sudo -u "$TARGET_USER" bash -c "echo '$line' >> '$BOOKMARKS'"
	fi
done

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
