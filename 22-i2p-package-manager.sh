#!/bin/bash
# Installs the Cyberbeest Package Manager GUI (Whisker app; currently a
# single opt-in entry: I2P (i2pd) + qBittorrent, with a dedicated
# Alpenglow-themed Firefox profile for eepsites, and an on-demand
# start/stop toggle -- Whisker entry starts i2pd + adds a panel icon,
# clicking the icon opens a menu to stop i2pd / open the I2P Firefox
# profile / start qBittorrent -- all set up automatically once installed)
# -- see lib/cyberbeest_package_manager_gui.py and lib/setup_i2p_extras.py.
#
# This only deploys the *tool*; it does not install i2pd/qbittorrent
# itself -- that stays opt-in, checked by hand in the GUI, same as every
# other row it might grow later.
#
# Privileged installs happen via lib/cyberbeest-pkg-helper.sh under pkexec,
# so the polkit policy authorizing that (root-owned, not writable by the
# cyberbeest user -- see the comment in the GUI script) is installed here.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/22-i2p-package-manager.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing cyberbeest-package-manager ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- Installing python3-gi (GTK bindings the GUI needs) ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y python3-gi gir1.2-gtk-3.0

echo "--- Installing privileged helper + polkit policy ---"
install -d /usr/local/lib/cyberbeest
install -m 755 "$DIR/lib/cyberbeest-pkg-helper.sh" /usr/local/lib/cyberbeest/cyberbeest-pkg-helper.sh
install -m 644 "$DIR/lib/com.cyberbeest.package-manager.policy" /usr/share/polkit-1/actions/com.cyberbeest.package-manager.policy

echo "--- Installing GUI + post-install helper to $TARGET_HOME/.local/bin ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
sed "s|__LOG_PATH__|$TARGET_HOME/.local/share/cyberbeest/cyberbeest_package_manager.log|g; \
     s|__POST_INSTALL_SCRIPT__|$TARGET_HOME/.local/bin/setup_i2p_extras.py|g" \
	"$DIR/lib/cyberbeest_package_manager_gui.py" \
	> "$TARGET_HOME/.local/bin/cyberbeest-package-manager"
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/bin/cyberbeest-package-manager"
chmod 755 "$TARGET_HOME/.local/bin/cyberbeest-package-manager"

install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/setup_i2p_extras.py" "$TARGET_HOME/.local/bin/setup_i2p_extras.py"

install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/cyberbeest"

echo "--- Installing icon ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/Pictures"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/assets/Cyberbeest-black.png" \
	"$TARGET_HOME/Pictures/Cyberbeest-black.png"

echo "--- Installing app menu entry (Whisker menu, Settings category) ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/applications"
cat > "$TARGET_HOME/.local/share/applications/cyberbeest-package-manager.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Cyberbeest Package Manager
Name[de]=Cyberbeest-Paketverwaltung
Comment=Install or remove optional Cyberbeest applications
Comment[de]=Optionale Cyberbeest-Anwendungen installieren oder entfernen
Exec=$TARGET_HOME/.local/bin/cyberbeest-package-manager
Icon=$TARGET_HOME/Pictures/Cyberbeest-black.png
Terminal=false
Categories=Cyberbeest;Settings;
StartupNotify=true
EOF
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/share/applications/cyberbeest-package-manager.desktop"

echo "=== $(date) : done ==="
