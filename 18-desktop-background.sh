#!/bin/bash
# Installs the Cyberbeest desktop wallpaper images so they're pickable from
# Desktop Settings, but deliberately does NOT try to select one via
# xfconf-query automation: that was tried (setting /backdrop/screen0/...
# properties directly + xfdesktop --reload) and it left the desktop in a
# half-applied state -- Desktop Settings would show the right image already
# selected, but the wallpaper wouldn't actually render correctly until you
# reselected it and toggled the scaling style off and back on. Simpler and
# more reliable to just drop the file where it's one click away and let a
# human pick it once.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/18-desktop-background.log"
# Save the real console on fd 3 before redirecting stdout/stderr to the log,
# so the manual-selection reminder at the end can still reach the person
# running this (whether directly, via menu.sh, or run-gui.py)
# instead of getting silently swallowed into the log file with everything else.
exec 3>&1
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing desktop background ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
. "$DIR/lib/xdg-dirs.sh"

echo "--- Installing wallpaper images ---"
PICTURES_DIR="$(xdg_dir PICTURES)"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$PICTURES_DIR"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/assets/cyberbeest-desktop-bg.png" "$PICTURES_DIR/Cyberbeest.png"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/assets/cyberbeest-desktop-bg-simplified.png" "$PICTURES_DIR/Cyberbeest-simplified.png"

echo "--- Also dropping it into /usr/share/backgrounds/xfce/ ---"
# So it's directly pickable from Desktop Settings' "xfce" folder (the one
# xfdesktop4-data ships) with a single click -- right-click desktop ->
# Desktop Settings -> pick Cyberbeest from the image grid.
install -m 644 "$DIR/lib/assets/cyberbeest-desktop-bg.png" \
	/usr/share/backgrounds/xfce/cyberbeest.png

echo "--- Also dropping it into the desktop-base active theme's wallpaper folder ---"
# Debian's xfdesktop-settings defaults the "Folder" dropdown in Desktop
# Settings to "desktop-base" -- that's the folder the dialog actually opens
# on for a fresh account, so drop a copy there too so it's visible without
# switching folders first.
#
# NB: this is NOT /usr/share/desktop-base/active-theme/wallpaper/contents/images/
# despite that being the obvious guess from the theme's own directory layout.
# Confirmed via ~/.cache/thumbnails/large/*.png Thumb::URI tags after browsing
# the "desktop-base" folder in the picker: the 4 images it actually shows
# (default, desktop-background, desktop-grub.png, login-background.svg) all
# live directly in /usr/share/images/desktop-base/, a flat symlink farm
# maintained by update-alternatives -- the picker doesn't recurse into the
# theme package's own wallpaper/contents/images/ at all. A previous version
# of this script installed into that wrong (but plausible-looking) directory;
# the file was on disk with correct permissions but never appeared in the UI.
DESKTOP_BASE_WALLPAPER_DIR="/usr/share/images/desktop-base"
if [ -d "$DESKTOP_BASE_WALLPAPER_DIR" ]; then
	install -m 644 "$DIR/lib/assets/cyberbeest-desktop-bg.png" \
		"$DESKTOP_BASE_WALLPAPER_DIR/cyberbeest.png"
fi

echo "--- Also dropping the fallback wallpaper into /usr/share/backgrounds/xfce/ ---"
# Same reasoning as the Cyberbeest copy above: makes it directly reselectable
# from Desktop Settings by name, rather than only existing as whatever
# update-alternatives' desktop-background symlink currently happens to
# target below -- if that alternative is ever superseded, the symlink's
# content changes/disappears, but this stable-named copy doesn't.
install -m 644 "$DIR/lib/assets/desktop-base-fallback-wallpaper.png" \
	/usr/share/backgrounds/xfce/cyberbeest-fallback.png

echo "--- Setting the system-wide fallback wallpaper (desktop-base alternative) ---"
# xfdesktop falls back to /usr/share/images/desktop-base/default (-> ...
# /desktop-background -> /etc/alternatives/desktop-background) whenever it
# can't find a matching per-monitor xfconf key for the current display --
# e.g. a live-boot session on unfamiliar hardware/a VM, or (per
# cyberbeest_desktop_background memory) even real hardware if xfdesktop ever
# regenerates generic monitor0/monitor1 keys instead of the connector-named
# one this laptop actually uses. Left alone, that fallback is Debian's own
# "ceratopsian" theme wallpaper. update-alternatives itself doesn't care
# about image format (PNG here, vs. the SVGs every desktop-base theme
# ships) -- xfdesktop loads either via GdkPixbuf regardless. This is
# separate from (and doesn't replace) the manual Cyberbeest-branded pick
# above -- it only ever shows up when nothing else was ever selected.
# Priority 100 comfortably beats every desktop-base theme's own entry
# (highest observed: 70, for whichever theme happens to be "active").
update-alternatives --install /usr/share/images/desktop-base/desktop-background \
	desktop-background "$DIR/lib/assets/desktop-base-fallback-wallpaper.png" 100
update-alternatives --set desktop-background \
	"$DIR/lib/assets/desktop-base-fallback-wallpaper.png"

echo "--- Removing the old xfconf-automation autostart entry/script, if present ---"
rm -f "$TARGET_HOME/.config/autostart/cyberbeest-set-wallpaper.desktop"
rm -f "$TARGET_HOME/.local/bin/set-desktop-background.sh"

echo "=== $(date) : done. Set it via Desktop Settings -> pick Cyberbeest (one-time). ==="

# See run-gui.py's MANUAL_TODO convention: it collects these into a "Things
# to do" pane instead of them getting lost in a scrolling log. Still on fd 3
# too, so a CLI run (menu.sh) shows it directly.
echo "MANUAL_TODO: Pick the desktop background: right-click desktop -> Desktop Settings -> select Cyberbeest, and set Style to 'Scaled'." >&3
