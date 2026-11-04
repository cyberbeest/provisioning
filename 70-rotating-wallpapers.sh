#!/bin/bash
# Installs the wallpaper photo packs (lib/assets/wallpapers, photos
# from Wikimedia Commons, credits in CREDITS.md) and a small
# helper (lib/cyberbeest-wallpaper-theme.sh, driven by the Wallpaper tab in
# Cyberbeest Settings) that turns on hourly rotation with a short crossfade
# (lib/cyberbeest-wallpaper-fade, autostarted; it exits at once when no pack
# is active) for one of the packs. A small watcher (lib/cyberbeest-wallpaper-corner)
# fades in a settings button when the mouse rests in the bottom-right corner. Rotation is off by default:
# nothing here changes the wallpaper a machine already shows.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/70-rotating-wallpapers.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing rotating wallpapers ==="

SRC="$DIR/lib/assets/wallpapers"
DEST="/usr/share/backgrounds/cyberbeest"

echo "--- Installing wallpaper packs to $DEST ---"
for theme in nature space architecture cars cities coast art; do
	install -d -m 755 "$DEST/$theme"
	# Drop images removed from the pack since an earlier run.
	for f in "$DEST/$theme"/*.jpg; do
		[ -e "$f" ] || continue
		[ -e "$SRC/$theme/$(basename "$f")" ] || rm -f "$f"
	done
	install -m 644 "$SRC/$theme"/*.jpg "$DEST/$theme/"
done
install -m 644 "$SRC/CREDITS.md" "$DEST/CREDITS.md"

echo "--- Installing the wallpaper theme helper ---"
install -m 755 "$DIR/lib/cyberbeest-wallpaper-theme.sh" /usr/local/bin/cyberbeest-wallpaper-theme
rm -f /usr/share/applications/cyberbeest-wallpaper-theme.desktop

echo "--- Installing the crossfade daemon ---"
apt-get install -y python3-gi python3-pil gir1.2-wnck-3.0
install -m 755 "$DIR/lib/cyberbeest-wallpaper-fade" /usr/local/bin/cyberbeest-wallpaper-fade
cat > /etc/xdg/autostart/cyberbeest-wallpaper-fade.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=Cyberbeest wallpaper rotation
Comment=Hourly wallpaper rotation with a crossfade; exits at once when no photo pack is chosen
Exec=/usr/local/bin/cyberbeest-wallpaper-fade
NoDisplay=true
OnlyShowIn=XFCE;
X-XFCE-Autostart-Phase=Application
EOF

echo "--- Installing the corner settings button ---"
install -m 755 "$DIR/lib/cyberbeest-wallpaper-corner" /usr/local/bin/cyberbeest-wallpaper-corner
cat > /etc/xdg/autostart/cyberbeest-wallpaper-corner.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=Cyberbeest wallpaper settings button
Comment=Fades in a settings button when the mouse rests in the bottom-right desktop corner
Exec=/usr/local/bin/cyberbeest-wallpaper-corner
NoDisplay=true
OnlyShowIn=XFCE;
X-XFCE-Autostart-Phase=Application
EOF

# (Re)start the corner button and the fade daemon in the running desktop
# session, so an update takes effect without logging out again. The new
# instances need the session's environment (DISPLAY, XAUTHORITY, DBus), which
# this root shell lacks, so it is read from a running desktop process.
echo "--- Reloading the wallpaper helpers in the running session ---"
TARGET_USER="${SUDO_USER:-}"
SESSION_PID=""
if [ -n "$TARGET_USER" ]; then
	for proc in xfdesktop xfce4-panel xfce4-session; do
		SESSION_PID="$(pgrep -u "$TARGET_USER" -x "$proc" | head -n1 || true)"
		[ -n "$SESSION_PID" ] && break
	done
fi
if [ -n "$SESSION_PID" ] && [ -r "/proc/$SESSION_PID/environ" ]; then
	SESSION_ENV="$(tr '\0' '\n' < "/proc/$SESSION_PID/environ" | grep -E '^(DISPLAY|XAUTHORITY|DBUS_SESSION_BUS_ADDRESS|XDG_RUNTIME_DIR|LANG)=' || true)"
	for helper in cyberbeest-wallpaper-corner cyberbeest-wallpaper-fade; do
		OLD_PID="$(pgrep -u "$TARGET_USER" -f "^python3 /usr/local/bin/$helper\$" | head -n1 || true)"
		# The corner button always runs; the fade daemon only if it already was
		# (it exits by itself when no photo pack is chosen).
		if [ -z "$OLD_PID" ] && [ "$helper" != cyberbeest-wallpaper-corner ]; then
			continue
		fi
		if [ -n "$OLD_PID" ]; then
			kill "$OLD_PID" 2>/dev/null || true
			for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$OLD_PID" 2>/dev/null || break; sleep 0.5; done
		fi
		# shellcheck disable=SC2086
		sudo -u "$TARGET_USER" -H env $(echo $SESSION_ENV) setsid nohup "/usr/local/bin/$helper" >/dev/null 2>&1 </dev/null &
		echo "$helper (re)started"
	done
	sleep 1
else
	echo "No desktop session found -- the helpers start at next login"
fi

echo "=== $(date) : done. ==="
