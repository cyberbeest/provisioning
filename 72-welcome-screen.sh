#!/bin/bash
# Installs the login welcome window (lib/cyberbeest-welcome.py): a dark tour with voice
# control, emergency security and an interactive panel guide (asks gopanel `items` and
# highlights icons on hover), plus five random "Did you know?" tips from the Factbook (the
# facts marked "tip": true, built into hints.json
# here), shown a few seconds after every login until the user clicks "Don't show
# again" (marker ~/.config/cyberbeest/welcome-dismissed). Test: cyberbeest-welcome --force
# Depends on: 21-default-password-nag.sh (icon, i18n helper in ~/.local/bin).
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/72-welcome-screen.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing welcome window ==="

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

apt-get -o DPkg::Lock::Timeout=60 install -y python3-gi python3-gi-cairo gir1.2-gtk-3.0

echo "--- Building the hints from the Factbook ---"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
python3 "$DIR/factbook/factbook.py" build "$TMP"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/cyberbeest"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$TMP/hints.json" "$TARGET_HOME/.local/share/cyberbeest/hints.json"

echo "--- Installing the window and its i18n helper ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin" "$TARGET_HOME/.local/bin/i18n"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR/lib/i18n.py" "$TARGET_HOME/.local/bin/i18n.py"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR"/lib/i18n/strings_*.py "$TARGET_HOME/.local/bin/i18n/"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 "$DIR/lib/cyberbeest-welcome.py" "$TARGET_HOME/.local/bin/cyberbeest-welcome"

echo "--- Installing autostart entry ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/autostart"
sed "s|/home/cyberbeest/|$TARGET_HOME/|g" "$DIR/lib/cyberbeest-welcome.desktop" \
	> "$TARGET_HOME/.config/autostart/cyberbeest-welcome.desktop"
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.config/autostart/cyberbeest-welcome.desktop"

echo "--- Installing app menu entry (Whisker menu, Cyberbeest category) ---"
# --force: opened on purpose, so it shows even after "Don't show again".
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/applications"
cat > "$TARGET_HOME/.local/share/applications/cyberbeest-welcome.desktop" <<EOF2
[Desktop Entry]
Type=Application
Name=Welcome Screen
Name[de]=Willkommensbildschirm
Comment=A few tips about your Cyberbeest
Comment[de]=Ein paar Tipps zu Ihrem Cyberbeest
Exec=$TARGET_HOME/.local/bin/cyberbeest-welcome --force
Icon=$TARGET_HOME/.local/share/cyberbeest/icons/Cyberbeest-black.png
Terminal=false
Categories=Cyberbeest;
EOF2
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/share/applications/cyberbeest-welcome.desktop"

echo "=== $(date) : done. Shows at next login; run cyberbeest-welcome --force to test. ==="
