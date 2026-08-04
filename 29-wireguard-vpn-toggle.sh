#!/bin/bash
# Installs the generic Cyberbeest WireGuard VPN toggle: import any
# provider's WireGuard .conf, connect/disconnect from a panel icon
# (genmon plugin-28), automatic kill-switch injection for configs that
# don't already have one, DNS-leak protection. Also installs the
# "Cyberbeest VPN" landing page (status + known-supported-provider list +
# import), which replaces a bare "Import VPN Profile" launcher.
#
# This only installs the *tool*. Mullvad and Proton VPN's own native apps
# are NOT installed here -- they run a persistent root background daemon
# each, so they're opt-in via Cyberbeest Package Manager instead (see
# 22-i2p-package-manager.sh, APPS list in lib/cyberbeest_package_manager_gui.py).
# This generic toggle has no such footprint (nothing runs until a profile
# is imported and connected), so it's fine as a default install.
#
# See lib/wireguard-vpn-toggle/ for the individual scripts and
# feedback_no_live_network_kill_switch_testing / cyberbeest_vpn_manager_gui
# memory notes for the design history (kill-switch teardown robustness fix,
# why Mullvad/Proton aren't bundled here).
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/29-wireguard-vpn-toggle.log"
exec > >(tee -a "$LOG") 2>&1
LIB="$DIR/lib/wireguard-vpn-toggle"

echo "=== $(date) : installing WireGuard VPN toggle ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- Installing wireguard-tools, iptables, openresolv (DNS-leak protection), python3-gi ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y wireguard-tools iptables openresolv python3-gi gir1.2-gtk-3.0

echo "--- Installing privileged helper scripts ---"
install -d /usr/local/lib/cyberbeest
install -m 755 -o root -g root "$LIB/vpn-import-helper.sh" /usr/local/lib/cyberbeest/vpn-import-helper.sh
install -m 755 -o root -g root "$LIB/vpn-remove-helper.sh" /usr/local/lib/cyberbeest/vpn-remove-helper.sh

echo "--- Installing scoped sudoers rule ---"
if visudo -c -f "$LIB/vpn-toggle-sudoers" >/dev/null 2>&1; then
    install -m 0440 -o root -g root "$LIB/vpn-toggle-sudoers" /etc/sudoers.d/vpn-toggle
else
    echo "visudo syntax check FAILED for vpn-toggle-sudoers, not installing" >&2
    exit 1
fi

echo "--- Locking down /etc/wireguard ---"
install -d -m 700 -o root -g root /etc/wireguard

echo "--- Installing unprivileged scripts to $TARGET_HOME/.local/bin ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
for f in vpn-import.sh vpn-connect.sh vpn-disconnect.sh vpn-remove-profile.sh \
         vpn-panel-icon.sh vpn-genmon.sh vpn-restore-session.sh; do
    install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 "$LIB/$f" "$TARGET_HOME/.local/bin/$f"
done
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 "$LIB/vpn-menu.py" "$TARGET_HOME/.local/bin/vpn-menu.py"

echo "--- Installing Cyberbeest VPN landing page ---"
sed "s|__PACKAGE_MANAGER_SCRIPT__|$TARGET_HOME/.local/bin/cyberbeest-package-manager|g" \
    "$DIR/lib/vpn_manager_gui.py" > "$TARGET_HOME/.local/bin/vpn_manager_gui.py"
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/bin/vpn_manager_gui.py"
chmod 755 "$TARGET_HOME/.local/bin/vpn_manager_gui.py"

echo "--- Installing Whisker menu entry ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/applications"
cat > "$TARGET_HOME/.local/share/applications/vpn.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Cyberbeest VPN
Comment=Connect to a VPN, see known-supported providers, or import a WireGuard config
Exec=$TARGET_HOME/.local/bin/vpn_manager_gui.py
Icon=network-vpn
Categories=Network;
Terminal=false
EOF
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/share/applications/vpn.desktop"

echo "--- Installing login session-restore autostart entry ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/autostart"
cat > "$TARGET_HOME/.config/autostart/vpn-restore-session.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=VPN session restore
Comment=Restores the VPN panel icon and last-connected profile at login, if any profiles are imported.
Exec=$TARGET_HOME/.local/bin/vpn-restore-session.sh
X-GNOME-Autostart-Phase=Application
X-GNOME-Autostart-Delay=5
NoDisplay=true
EOF
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.config/autostart/vpn-restore-session.desktop"

echo "--- Refreshing desktop database ---"
sudo -u "$TARGET_USER" update-desktop-database "$TARGET_HOME/.local/share/applications" >/dev/null 2>&1 || true

echo "=== done ==="
