#!/bin/bash
# Installs the Cyberbeest desktop wallpaper + the autostart entry that sets
# it reliably regardless of what XRandR calls the actual monitor -- see
# lib/set-desktop-background.sh for why a static xfce4-desktop.xml copy
# doesn't work across different hardware.
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

echo "--- Installing set-desktop-background.sh ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/set-desktop-background.sh" "$TARGET_HOME/.local/bin/set-desktop-background.sh"

echo "--- Installing autostart entry ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/autostart"
sed "s|/home/cyberbeest/|$TARGET_HOME/|g" "$DIR/lib/cyberbeest-set-wallpaper.desktop" \
	> "$TARGET_HOME/.config/autostart/cyberbeest-set-wallpaper.desktop"
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.config/autostart/cyberbeest-set-wallpaper.desktop"

echo "--- Running it now, if the target user has an active session ---"
TARGET_UID="$(id -u "$TARGET_USER")"
if [ -d "/run/user/$TARGET_UID" ]; then
	su - "$TARGET_USER" -c "DISPLAY='${DISPLAY:-:0}' $TARGET_HOME/.local/bin/set-desktop-background.sh" || true
else
	echo "no active session for $TARGET_USER -- it'll run at next login"
fi

echo "=== $(date) : done ==="
