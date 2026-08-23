#!/bin/bash
# Installs Cyberbeest Wipe App Data: a manually launched GUI that erases a
# selected app's local data (see lib/cyberbeest_wipe_app_data_gui.py and
# lib/app-data-paths.conf for the path table and reasoning -- plain delete
# is enough given full-disk LUKS encryption, no shred-style overwrite).
#
# i2pd's data lives under /var/lib/i2pd (a system service account, not a
# per-user path) -- the GUI escalates for that one entry via pkexec, which
# needs no install step here (part of policykit-1, already present on a
# standard Xfce desktop).
#
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/44-wipe-app-data.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing Cyberbeest Wipe App Data ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- Installing python3-gi (GTK bindings the GUI needs) and polkitd/pkexec ---"
# polkitd + pkexec + the auth-prompt agent (mate-polkit) all already come in
# via xfce4's own dependencies on a Cyberbeest machine -- installed
# explicitly here too, so this step is self-contained and doesn't silently
# depend on that.
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y python3-gi gir1.2-gtk-3.0 polkitd pkexec

echo "--- Installing script + path table to $TARGET_HOME/.local/bin ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
    "$DIR/lib/cyberbeest_wipe_app_data_gui.py" \
    "$TARGET_HOME/.local/bin/cyberbeest_wipe_app_data_gui.py"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
    "$DIR/lib/app-data-paths.conf" \
    "$TARGET_HOME/.local/bin/app-data-paths.conf"

echo "--- Installing Whisker menu entry ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/applications"
cat > "$TARGET_HOME/.local/share/applications/cyberbeest-wipe-app-data.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Cyberbeest Wipe App Data
Comment=Erase a selected app's local data (chat history, wallet files, browsing data)
Icon=edit-clear-all
Exec=$TARGET_HOME/.local/bin/cyberbeest_wipe_app_data_gui.py
Categories=Cyberbeest;Settings;
Terminal=false
StartupNotify=true
EOF
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/share/applications/cyberbeest-wipe-app-data.desktop"

echo "--- Refreshing desktop database ---"
sudo -u "$TARGET_USER" update-desktop-database "$TARGET_HOME/.local/share/applications" >/dev/null 2>&1 || true

echo "=== $(date) : done ==="
