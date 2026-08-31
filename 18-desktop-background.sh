#!/bin/bash
# Installs the Cyberbeest desktop wallpaper images so they're pickable from
# Desktop Settings, and installs an autostart entry (lib/set-fallback-wallpaper.sh)
# that fills in a fallback image via xfconf for any monitor/workspace slot
# nobody has explicitly set yet -- so a fresh/live/VM session shows our
# branding instead of XFCE's own default (a teal swirl with the XFCE mouse
# logo), without ever overriding a human's manual "pick Cyberbeest in
# Desktop Settings" choice. See that script's header for why an earlier,
# similar attempt (removed in b321043) looked half-applied instead of just
# working.
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
# This part is NOT what actually makes xfdesktop render our fallback --
# verified empirically (2026-08-31, screenshot of a live VM session) that
# xfdesktop does NOT consult /usr/share/images/desktop-base/default when it
# can't find a matching per-monitor xfconf key; it renders its own
# hardcoded default (a teal swirl with the XFCE mouse logo) instead. This
# update-alternatives dance is kept anyway because it's what some other
# consumers of the desktop-base alternative (e.g. lightdm-gtk-greeter's
# `user-background` fallback, some login/lock screens) DO honor, and
# because it's what a human sees if they browse the "desktop-base" folder
# in Desktop Settings. Priority 100 comfortably beats every desktop-base
# theme's own entry (highest observed: 70).
update-alternatives --install /usr/share/images/desktop-base/desktop-background \
	desktop-background "$DIR/lib/assets/desktop-base-fallback-wallpaper.png" 100
update-alternatives --set desktop-background \
	"$DIR/lib/assets/desktop-base-fallback-wallpaper.png"

echo "--- Removing the old xfconf-automation autostart entry/script, if present ---"
rm -f "$TARGET_HOME/.config/autostart/cyberbeest-set-wallpaper.desktop"
rm -f "$TARGET_HOME/.local/bin/set-desktop-background.sh"

echo "--- Installing set-fallback-wallpaper.sh + autostart entry ---"
# This is what actually makes xfdesktop render our fallback instead of its
# own default: it fills in the real, connector-named xfconf key (via
# xrandr, at login time, since the connector name isn't known any earlier)
# for every workspace, but only where nothing is set yet -- so it never
# overrides a human's manual "pick Cyberbeest in Desktop Settings" choice.
# See lib/set-fallback-wallpaper.sh for why the earlier attempt at this
# (removed in b321043) looked "half-applied": it only updated
# already-existing workspace<N> xfconf keys, so newly-created ones (the
# common case on a fresh session) stayed unset and xfdesktop fell through
# to its own default anyway.
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/set-fallback-wallpaper.sh" "$TARGET_HOME/.local/bin/set-fallback-wallpaper.sh"

install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/autostart"
sed "s|/home/cyberbeest/|$TARGET_HOME/|g" "$DIR/lib/cyberbeest-set-fallback-wallpaper.desktop" \
	> "$TARGET_HOME/.config/autostart/cyberbeest-set-fallback-wallpaper.desktop"
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.config/autostart/cyberbeest-set-fallback-wallpaper.desktop"

echo "--- Running it now, if the target user has an active session ---"
TARGET_UID="$(id -u "$TARGET_USER")"
if [ -d "/run/user/$TARGET_UID" ]; then
	SESSION_PID="$(pgrep -u "$TARGET_USER" -x xfce4-session | head -1)"
	DBUS_ADDR=""
	if [ -n "$SESSION_PID" ]; then
		DBUS_ADDR="$(cat "/proc/$SESSION_PID/environ" 2>/dev/null | tr '\0' '\n' | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')" || true
	fi
	DBUS_ADDR="${DBUS_ADDR:-unix:path=/run/user/$TARGET_UID/bus}"
	su - "$TARGET_USER" -c "DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$DBUS_ADDR' $TARGET_HOME/.local/bin/set-fallback-wallpaper.sh" || true
else
	echo "no active session for $TARGET_USER -- it'll run at next login"
fi

echo "=== $(date) : done. Set it via Desktop Settings -> pick Cyberbeest (one-time). ==="

# See run-gui.py's MANUAL_TODO convention: it collects these into a "Things
# to do" pane instead of them getting lost in a scrolling log. Still on fd 3
# too, so a CLI run (menu.sh) shows it directly.
echo "MANUAL_TODO: Pick the desktop background: right-click desktop -> Desktop Settings -> select Cyberbeest, and set Style to 'Scaled'." >&3
