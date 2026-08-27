#!/bin/bash
# Installs the Cyberbeest Package Manager GUI (Whisker app; opt-in rows
# for qBittorrent, Mullvad VPN, and Proton VPN) -- see
# lib/cyberbeest_package_manager_gui.py.
#
# i2pd itself is NOT one of these rows anymore -- it's installed by
# default now (see 50-i2pd-default.sh), same tier as Signal/Firefox/etc.
# qBittorrent stays opt-in here since it's an unrelated torrenting client;
# its post-install step (lib/enable_qbittorrent_i2p.py) just flips on I2P
# support in its own config, assuming i2pd is already present.
#
# This only deploys the *tool*; it does not install qbittorrent/mullvad-vpn/
# proton-vpn-gnome-desktop themselves -- those stay opt-in, checked by hand
# in the GUI.
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
     s|__QBT_POST_INSTALL_SCRIPT__|$TARGET_HOME/.local/bin/enable_qbittorrent_i2p.py|g" \
	"$DIR/lib/cyberbeest_package_manager_gui.py" \
	> "$TARGET_HOME/.local/bin/cyberbeest-package-manager"
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/bin/cyberbeest-package-manager"
chmod 755 "$TARGET_HOME/.local/bin/cyberbeest-package-manager"

install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/enable_qbittorrent_i2p.py" "$TARGET_HOME/.local/bin/enable_qbittorrent_i2p.py"

install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/cyberbeest"

echo "--- Installing icon ---"
# Not Pictures/Bilder: that's user-visible and locale-renamed (English
# "Pictures" vs. German "Bilder"), so a hardcoded/stale reference to it can
# silently break this app-UI icon. .local/share/cyberbeest/icons is a fixed,
# non-user-facing location no XDG-dirs translation or user reorganization
# touches.
ICONS_DIR="$TARGET_HOME/.local/share/cyberbeest/icons"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$ICONS_DIR"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/assets/Cyberbeest-black.png" \
	"$ICONS_DIR/Cyberbeest-black.png"

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
Icon=$ICONS_DIR/Cyberbeest-black.png
Terminal=false
Categories=Cyberbeest;Settings;
StartupNotify=true
EOF
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/share/applications/cyberbeest-package-manager.desktop"

echo "=== $(date) : done ==="
