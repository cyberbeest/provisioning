#!/bin/bash
# Installs the Factbook app (factbook/factbook_gui.py): every fact about Cyberbeest in one
# searchable list, by topic. When Butler is installed (69a-butler.sh) the search also ranks
# facts by meaning ("is my disk safe" finds the encryption facts); without it the search
# matches words only. Shows up in the Whisker menu (Cyberbeest) and is what Butler's
# "open the Factbook" and the welcome screen's "Open the full Factbook" button start.
#
# Installs to ~/.local/share/cyberbeest/factbook (the app and facts/) plus the launcher
# entry ~/.local/share/applications/factbook.desktop.
# Depends on: nothing beyond python3-gi (also installed by 72-welcome-screen.sh).
# Idempotent: safe to re-run; it replaces the app and the facts each time.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/72a-factbook.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing Factbook ==="

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="${FACTBOOK_INSTALL_HOME:-$(getent passwd "$TARGET_USER" | cut -d: -f6)}" # the override is for testing only
DEST="$TARGET_HOME/.local/share/cyberbeest/factbook"

[ -f "$DIR/factbook/factbook_gui.py" ] && [ -d "$DIR/factbook/facts" ] || { echo "missing factbook/ next to this script"; exit 1; }

if ! dpkg -s python3-gi gir1.2-gtk-3.0 >/dev/null 2>&1; then
	apt-get -o DPkg::Lock::Timeout=60 install -y python3-gi gir1.2-gtk-3.0
fi

echo "--- App and facts to $DEST ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/cyberbeest" "$DEST"
rm -rf "$DEST/facts"
cp -r "$DIR/factbook/facts" "$DEST/facts"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 "$DIR/factbook/factbook_gui.py" "$DEST/factbook_gui.py"
chown -R "$TARGET_USER:$TARGET_USER" "$DEST/facts"

echo "--- Menu entry ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/applications"
cat > "$TARGET_HOME/.local/share/applications/factbook.desktop" <<EOF2
[Desktop Entry]
Type=Application
Name=Factbook
Name[de]=Faktenbuch
Comment=Every fact about Cyberbeest in one searchable list
Comment[de]=Alle Fakten über Cyberbeest in einer durchsuchbaren Liste
Exec=$DEST/factbook_gui.py
Icon=accessories-dictionary
Terminal=false
Categories=Cyberbeest;
EOF2
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/share/applications/factbook.desktop"

echo "=== $(date) : done ==="
