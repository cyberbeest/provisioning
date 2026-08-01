#!/bin/bash
# Installs the Cyberbeest Panel Color GUI as a regular app under Whisker's
# Settings category (not pinned to the panel) -- see
# lib/cyberbeest-panel-color.py. Lets the user set the xfce4-panel
# background color, and keeps it in sync with the kitt-scanner LED plugin's
# margin color, since kitt-scanner.c hardcodes that margin to match the
# *default* theme background rather than reading the panel's live color.
# Depends on: 11-xfce-panel-plugins.sh (builds kitt-scanner),
# 12-xfce-panel-layout.sh (installs kitt-scanner as plugin id 14, i.e.
# kitt-scanner-14.rc -- this script's KITT_RC_PATH substitution must match
# that). Degrades gracefully if kitt-scanner isn't installed (the panel
# color still applies; the margin-color file write is just skipped).
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/25-cyberbeest-panel-color.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing cyberbeest-panel-color ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- Installing python3-gi (GTK bindings the GUI needs) ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y python3-gi gir1.2-gtk-3.0

echo "--- Installing GUI script to $TARGET_HOME/.local/bin/cyberbeest-panel-color ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
# Must match the kitt-scanner plugin instance 12-xfce-panel-layout.sh's
# panel template assigns (kitt-scanner-14.rc).
sed "s|__KITT_RC_PATH__|$TARGET_HOME/.config/xfce4/panel/kitt-scanner-14.rc|g" \
	"$DIR/lib/cyberbeest-panel-color.py" > "$TARGET_HOME/.local/bin/cyberbeest-panel-color"
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/bin/cyberbeest-panel-color"
chmod 755 "$TARGET_HOME/.local/bin/cyberbeest-panel-color"

# i18n.py does `from i18n import t`, which only resolves if i18n.py (and its
# strings_*.py catalogs) sit next to the installed script -- see lib/i18n.py.
echo "--- Installing shared i18n runtime ---"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR/lib/i18n.py" "$TARGET_HOME/.local/bin/i18n.py"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin/i18n"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR"/lib/i18n/strings_*.py "$TARGET_HOME/.local/bin/i18n/"

echo "--- Installing icon ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/Pictures"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/assets/Cyberbeest-black.png" \
	"$TARGET_HOME/Pictures/Cyberbeest-black.png"

echo "--- Installing app menu entry (Whisker menu, Settings category) ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/applications"
cat > "$TARGET_HOME/.local/share/applications/cyberbeest-panel-color.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Cyberbeest Panel Color
Name[de]=Cyberbeest-Panelfarbe
Comment=Set the panel background color
Comment[de]=Hintergrundfarbe des Panels festlegen
Exec=$TARGET_HOME/.local/bin/cyberbeest-panel-color
Icon=$TARGET_HOME/Pictures/Cyberbeest-black.png
Terminal=false
Categories=Cyberbeest;Settings;
StartupNotify=true
EOF
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/share/applications/cyberbeest-panel-color.desktop"

echo "=== $(date) : done ==="
