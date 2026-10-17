#!/bin/bash
# Installs the wallpaper photo packs (lib/assets/wallpapers, photos
# from Wikimedia Commons, credits in CREDITS.md) and a small
# helper (lib/cyberbeest-wallpaper-theme.sh, driven by the Wallpaper tab in
# Cyberbeest Settings) that turns on hourly rotation with a short crossfade
# (lib/cyberbeest-wallpaper-fade, autostarted; it exits at once when no pack
# is active) for one of the packs. Rotation is off by default:
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

echo "=== $(date) : done. ==="
