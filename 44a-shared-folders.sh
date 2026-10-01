#!/bin/bash
# Installs Whitelisted Folders: a GUI to add extra folders that every
# firejail-sandboxed app (browser, messengers, wallets) may see. One global
# list, not per app -- see lib/cyberbeest_shared_folders_gui.py for how it
# works (user-level ~/.config/firejail/globals.local, no root needed) and
# for the guardrails.
#
# Sparrow and Feather's hand-built profiles include globals.local too (see
# lib/sparrow.profile, lib/feather.profile, deployed by 40-jail-wallets-viber.sh).
#
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/44a-shared-folders.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing Whitelisted Folders ==="

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- Installing firejail and python3-gi (GTK bindings the GUI needs) ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y firejail python3-gi gir1.2-gtk-3.0

echo "--- Installing script + i18n catalogs to $TARGET_HOME/.local/bin ---"
# i18n.py does `from i18n import t`, which only resolves if i18n.py (and its
# strings_*.py catalogs) sit next to the installed script -- see lib/i18n.py.
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin" "$TARGET_HOME/.local/bin/i18n"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
    "$DIR/lib/cyberbeest_shared_folders_gui.py" "$TARGET_HOME/.local/bin/cyberbeest_shared_folders_gui.py"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR/lib/i18n.py" "$TARGET_HOME/.local/bin/i18n.py"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR"/lib/i18n/strings_*.py "$TARGET_HOME/.local/bin/i18n/"

echo "--- Re-deploying the wallet profiles (they include globals.local now) ---"
install -m 644 "$DIR/lib/sparrow.profile" /etc/firejail/sparrow.profile
install -m 644 "$DIR/lib/feather.profile" /etc/firejail/feather.profile

echo "--- Installing icon ---"
# Same fixed, non-user-facing icons location as 21-default-password-nag.sh.
ICONS_DIR="$TARGET_HOME/.local/share/cyberbeest/icons"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$ICONS_DIR"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/assets/Cyberbeest-black.png" "$ICONS_DIR/Cyberbeest-black.png"

echo "--- Seeding the default shares (Downloads, Pictures) on first install ---"
# The per-app profiles no longer hard-code these two folders, so the list has
# to start out containing them. Only ever written when no list exists yet --
# a user who removed them keeps it that way.
sudo -u "$TARGET_USER" -H python3 "$TARGET_HOME/.local/bin/cyberbeest_shared_folders_gui.py" --seed

echo "--- Installing Whisker menu entry ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/applications"
cat > "$TARGET_HOME/.local/share/applications/cyberbeest-shared-folders.desktop" <<INNER
[Desktop Entry]
Type=Application
Name=Whitelisted Folders
Name[de]=Zugelassene Ordner
Comment=Choose extra folders your protected apps may see
Comment[de]=Zusätzliche Ordner für deine geschützten Apps zulassen
Icon=$ICONS_DIR/Cyberbeest-black.png
StartupWMClass=whitelisted-folders
Exec=$TARGET_HOME/.local/bin/cyberbeest_shared_folders_gui.py
Categories=Cyberbeest;Settings;
Terminal=false
StartupNotify=true
INNER
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/share/applications/cyberbeest-shared-folders.desktop"

echo "--- Refreshing desktop database ---"
sudo -u "$TARGET_USER" update-desktop-database "$TARGET_HOME/.local/share/applications" >/dev/null 2>&1 || true

echo "=== $(date) : done ==="
