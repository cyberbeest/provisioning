#!/bin/bash
# Installs the nature and space wallpaper packs (lib/assets/wallpapers, photos
# from Wikimedia Commons, credits in CREDITS.md) and a small
# helper (lib/cyberbeest-wallpaper-theme.sh, driven by the Wallpaper tab in
# Cyberbeest Settings) that turns on xfdesktop's built-in image cycling for
# one of the packs. Rotation is off by default:
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
for theme in nature space; do
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

echo "=== $(date) : done. ==="
