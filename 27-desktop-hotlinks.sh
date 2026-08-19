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
. "$DIR/lib/xdg-dirs.sh"
DESKTOP_DIR="$(xdg_dir DESKTOP)"
PICTURES_DIR="$(xdg_dir PICTURES)"
DOWNLOADS_DIR="$(xdg_dir DOWNLOAD)"
HAVE_SESSION=0
if [ -d "/run/user/$TARGET_UID" ]; then
	HAVE_SESSION=1
	DBUS_ADDR="unix:path=/run/user/$TARGET_UID/bus"
fi

echo "--- Adding Pictures and Downloads link launchers to the desktop ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$DESKTOP_DIR"

write_desktop_link() {
	local name="$1" icon="$2" target="$3" legacy_name="$4" dest="$DESKTOP_DIR/$1.desktop" sum
	# Drop a launcher left over from before this folder's real name was
	# resolved via xdg_dir (e.g. Pictures.desktop, orphaned once German
	# renamed the actual folder to Bilder) -- same link, stale name, and
	# otherwise left sitting there pointing at a folder that no longer
	# exists.
	if [ "$legacy_name" != "$name" ]; then
		rm -f "$DESKTOP_DIR/$legacy_name.desktop"
	fi
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

PICTURES_NAME="$(basename "$PICTURES_DIR")"
DOWNLOADS_NAME="$(basename "$DOWNLOADS_DIR")"
write_desktop_link "$PICTURES_NAME" "folder-pictures" "$PICTURES_DIR" "Pictures"
write_desktop_link "$DOWNLOADS_NAME" "folder-download" "$DOWNLOADS_DIR" "Downloads"

echo "--- Adding Pictures and Downloads to the file manager's Places sidebar ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/gtk-3.0"
BOOKMARKS="$TARGET_HOME/.config/gtk-3.0/bookmarks"
sudo -u "$TARGET_USER" touch "$BOOKMARKS"

sync_bookmark() {
	local dir="$1" legacy_name="$2" entry line
	entry="$(basename "$dir")"
	# Same stale-name cleanup as the desktop launchers above, for the
	# Places sidebar's bookmarks file.
	if [ "$legacy_name" != "$entry" ]; then
		sudo -u "$TARGET_USER" sed -i "\#^file://$TARGET_HOME/$legacy_name #d" "$BOOKMARKS"
	fi
	line="file://$dir $entry"
	if ! grep -qxF "$line" "$BOOKMARKS"; then
		sudo -u "$TARGET_USER" bash -c "echo '$line' >> '$BOOKMARKS'"
	fi
}

sync_bookmark "$PICTURES_DIR" "Pictures"
sync_bookmark "$DOWNLOADS_DIR" "Downloads"

echo "--- Hiding the 'File System' special icon (leaves Home/Trash alone) ---"
if [ "$HAVE_SESSION" -eq 1 ]; then
	sudo -u "$TARGET_USER" DBUS_SESSION_BUS_ADDRESS="$DBUS_ADDR" \
		xfconf-query -c xfce4-desktop -p /desktop-icons/file-icons/show-filesystem \
		-n -t bool -s false
else
	echo "no active session for $TARGET_USER -- xfconf needs a running session, skipping;" \
		"re-run this script (or set it by hand) once logged in"
fi

echo "--- Restarting xfdesktop for the logged-in user, if one is running ---"
# --reload only refreshes xfconf-backed settings (backdrop, icon
# positions); it does NOT make a long-running process re-derive
# XDG_DESKTOP_DIR -- glib caches special-dirs like the desktop folder once
# per process at startup. After the folder itself gets renamed (e.g.
# Desktop -> Schreibtisch), a live xfdesktop keeps watching the now-gone
# old path and silently shows no icons at all -- confirmed 2026-08-19:
# --reload left the desktop empty, a full kill+relaunch fixed it
# immediately. Same class of stale-in-memory-state issue
# 12-xfce-panel-layout.sh already works around for xfconfd/the panel.
if [ "$HAVE_SESSION" -eq 1 ] && pgrep -u "$TARGET_USER" -x xfdesktop >/dev/null; then
	pkill -u "$TARGET_USER" -x xfdesktop || true
	sleep 1
	sudo -u "$TARGET_USER" DISPLAY="${DISPLAY:-:0}" DBUS_SESSION_BUS_ADDRESS="$DBUS_ADDR" \
		nohup xfdesktop >/dev/null 2>&1 &
	disown
fi

echo "=== $(date) : done ==="
