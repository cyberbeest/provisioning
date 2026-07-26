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
exec > "$LOG" 2>&1

echo "=== $(date) : installing desktop background ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- Installing wallpaper images ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/Pictures"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/assets/cyberbeest-desktop-bg.png" "$TARGET_HOME/Pictures/Cyberbeest.png"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/assets/cyberbeest-desktop-bg-simplified.png" "$TARGET_HOME/Pictures/Cyberbeest-simplified.png"

echo "--- Also dropping it into /usr/share/backgrounds/xfce/ ---"
# So it's directly pickable from Desktop Settings' "xfce" folder (the one
# xfdesktop4-data ships) with a single click -- right-click desktop ->
# Desktop Settings -> pick Cyberbeest from the image grid.
install -m 644 "$DIR/lib/assets/cyberbeest-desktop-bg.png" \
	/usr/share/backgrounds/xfce/cyberbeest.png

echo "--- Removing the old xfconf-automation autostart entry/script, if present ---"
rm -f "$TARGET_HOME/.config/autostart/cyberbeest-set-wallpaper.desktop"
rm -f "$TARGET_HOME/.local/bin/set-desktop-background.sh"

echo "=== $(date) : done. Set it via Desktop Settings -> pick Cyberbeest (one-time, per monitor). ==="
