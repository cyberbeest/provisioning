#!/bin/bash
# Desktop hotlinks: adds Pictures and Downloads folder icons to the desktop
# and to the file manager's Places sidebar, and turns off the "File System"
# special desktop icon -- opening / is scary territory for a normal user and
# isn't something they need one click away. Also nudges the Trash icon down
# to the bottom of the stack, once, after everything else is in place --
# xfdesktop's default arrangement puts it second (right after Home, ahead of
# every real folder/launcher), which reads oddly to a non-technical user.
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

# --reload only refreshes xfconf-backed settings (backdrop, icon
# positions); it does NOT make a long-running process re-derive
# XDG_DESKTOP_DIR -- glib caches special-dirs like the desktop folder once
# per process at startup. After the folder itself gets renamed (e.g.
# Desktop -> Schreibtisch), a live xfdesktop keeps watching the now-gone
# old path and silently shows no icons at all -- confirmed 2026-08-19:
# --reload left the desktop empty, a full kill+relaunch fixed it
# immediately. Same class of stale-in-memory-state issue
# 12-xfce-panel-layout.sh already works around for xfconfd/the panel.
restart_xfdesktop() {
	# Always relaunch when there's a session to relaunch it into -- NOT
	# gated on xfdesktop currently being alive. It's called a second time
	# below right after the trash-fix step has already killed xfdesktop
	# itself (to edit the icon file safely); gating on "is it running"
	# here would see nothing (we just killed it) and silently skip the
	# relaunch, leaving the desktop with no icons at all -- exactly what
	# happened the first time this was written.
	if [ "$HAVE_SESSION" -eq 1 ]; then
		pkill -u "$TARGET_USER" -x xfdesktop || true
		sleep 1
		sudo -u "$TARGET_USER" DISPLAY="${DISPLAY:-:0}" DBUS_SESSION_BUS_ADDRESS="$DBUS_ADDR" \
			nohup xfdesktop >/dev/null 2>&1 &
		disown
		sleep 2
	fi
}

echo "--- Restarting xfdesktop for the logged-in user, if one is running ---"
restart_xfdesktop

echo "--- Moving the Trash icon to the bottom of the desktop icon stack ---"
# xfdesktop's own default arrangement (confirmed empirically by clearing
# icons.screen0.yaml and letting it rebuild from scratch) is: Home first,
# then Trash, then every real folder/launcher sorted alphabetically -- so
# Trash lands second, ahead of Pictures/Downloads/Terminal etc. Fix that up
# once by editing the icon-position file directly: it must not be touched
# while xfdesktop is running (the file's own header says so, and it gets
# overwritten on exit anyway), so kill it, edit, then relaunch via the same
# restart_xfdesktop helper used above. Only handles the single built-in
# display column (col 0) this laptop actually has -- if the icon count ever
# grows enough to overflow into a second column, this needs revisiting.
ICONS_YAML="$TARGET_HOME/.config/xfce4/desktop/icons.screen0.yaml"
if [ "$HAVE_SESSION" -eq 1 ] && [ -f "$ICONS_YAML" ]; then
	pkill -u "$TARGET_USER" -x xfdesktop || true
	sleep 1
	# NB: plain <<'PYEOF' (no dash), body flush against the left margin --
	# <<- only strips LEADING TABS, not "one level of indentation", so a
	# tab-indented body here would have every line's tabs stripped down to
	# column 0 regardless of nesting depth, destroying Python's own
	# indentation-based scoping (confirmed: that's exactly what happened
	# on the first version of this block). Spaces below are real Python
	# indentation, not shell heredoc styling.
	sudo -u "$TARGET_USER" python3 - "$ICONS_YAML" <<'PYEOF'
import re, sys

path = sys.argv[1]
with open(path) as f:
    lines = f.readlines()

# Each icon is a "    \"key\":" line followed by indented "row:"/"col:"/
# "last_seen:" property lines. Find every icon's row line and the
# max row seen outside of Trash, then bump Trash's row past it.
icon_re = re.compile(r'^    "(.*)":\s*$')
row_re = re.compile(r'^(      row: )(\d+)\s*$')

current_key = None
max_row = -1
trash_row_line = None
for i, line in enumerate(lines):
    m = icon_re.match(line)
    if m:
        current_key = m.group(1)
        continue
    m = row_re.match(line)
    if m and current_key is not None:
        row = int(m.group(2))
        if current_key == "trash:///":
            trash_row_line = i
        else:
            max_row = max(max_row, row)

if trash_row_line is not None and max_row >= 0:
    lines[trash_row_line] = f"      row: {max_row + 1}\n"
    with open(path, "w") as f:
        f.writelines(lines)
PYEOF
	restart_xfdesktop
else
	echo "no active session for $TARGET_USER, or no icon layout saved yet -- skipping;" \
		"re-run this script once logged in to move Trash to the bottom"
fi

echo "=== $(date) : done ==="
