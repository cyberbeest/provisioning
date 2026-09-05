#!/bin/bash
# Installs "Cyberbeest Update": a Whisker menu entry that hard-resets
# ~/provisioning (or ~/provisioning-bleeding) to the latest commit on
# whichever branch it tracks and applies anything new via run-gui.py's
# "Run changed only", auto-clicked so the user just confirms once (behind
# a brief progress dialog for the git step) and watches it run -- see
# lib/cyberbeest-update.sh for the actual logic and run-gui.py's
# --run-changed flag for the auto-click.
#
# Assumes beestify.sh or beestify-bleeding.sh already ran (so a git
# checkout exists to pull into) -- lib/cyberbeest-update.sh itself checks
# for that at click-time and shows a zenity error if not, rather than this
# install step failing on a machine mid-provisioning.
#
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/52-cyberbeest-update.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing Cyberbeest Update ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- Installing script to $TARGET_HOME/.local/bin ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/cyberbeest-update.sh" \
	"$TARGET_HOME/.local/bin/cyberbeest-update.sh"

# i18n.sh does `. "$DIR/i18n.sh"` relative to its own location, so this
# script's i18n.sh (and its i18n/ catalogs) have to sit next to the
# installed script -- see lib/i18n.sh.
echo "--- Installing shared i18n runtime ---"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR/lib/i18n.sh" "$TARGET_HOME/.local/bin/i18n.sh"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin/i18n"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR"/lib/i18n/strings.*.sh "$TARGET_HOME/.local/bin/i18n/"

echo "--- Installing Whisker menu entry ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/applications"
cat > "$TARGET_HOME/.local/share/applications/cyberbeest-update.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Cyberbeest Update
Name[de]=Cyberbeest-Update
Comment=Check for and apply the latest Cyberbeest provisioning updates
Comment[de]=Nach den neuesten Cyberbeest-Updates suchen und sie anwenden
Icon=system-software-update
Exec=$TARGET_HOME/.local/bin/cyberbeest-update.sh
Categories=Cyberbeest;Settings;
Terminal=false
StartupNotify=true
EOF
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/share/applications/cyberbeest-update.desktop"

echo "--- Refreshing desktop database ---"
sudo -u "$TARGET_USER" update-desktop-database "$TARGET_HOME/.local/share/applications" >/dev/null 2>&1 || true

echo "=== $(date) : done ==="
