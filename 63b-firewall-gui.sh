#!/bin/bash
# Installs the Firewall tool: a GUI (Whisker menu entry "Firewall") to open and
# close ports on top of 63-firewall.sh's default-deny-inbound ruleset. The
# privileged part is lib/cyberbeest-firewall-helper.sh, run through pkexec; the
# polkit policy authorising it is installed here (same pattern as
# 73-cyberbeest-backup.sh). See lib/cyberbeest_firewall_gui.py for how the
# list is stored and shown.
#
# Needs 63-firewall.sh to have run first (the helper refuses to do anything
# without /etc/nftables.conf).
#
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/63b-firewall-gui.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing the Firewall tool ==="

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- Installing python3-gi (GTK bindings the GUI needs) ---"
apt-get -o DPkg::Lock::Timeout=60 install -y python3-gi gir1.2-gtk-3.0

echo "--- Installing privileged helper + polkit policy ---"
install -d /usr/local/lib/cyberbeest
install -m 755 "$DIR/lib/cyberbeest-firewall-helper.sh" /usr/local/lib/cyberbeest/cyberbeest-firewall-helper.sh
install -m 644 "$DIR/lib/com.cyberbeest.firewall.policy" /usr/share/polkit-1/actions/com.cyberbeest.firewall.policy

echo "--- Installing script + i18n catalogs to $TARGET_HOME/.local/bin ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin" "$TARGET_HOME/.local/bin/i18n"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/cyberbeest_firewall_gui.py" "$TARGET_HOME/.local/bin/cyberbeest_firewall_gui.py"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR/lib/i18n.py" "$TARGET_HOME/.local/bin/i18n.py"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR"/lib/i18n/strings_*.py "$TARGET_HOME/.local/bin/i18n/"

echo "--- Installing icon ---"
ICONS_DIR="$TARGET_HOME/.local/share/cyberbeest/icons"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$ICONS_DIR"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/assets/Cyberbeest-black.png" "$ICONS_DIR/Cyberbeest-black.png"

echo "--- Installing Whisker menu entry ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/applications"
cat > "$TARGET_HOME/.local/share/applications/cyberbeest-firewall.desktop" <<INNER
[Desktop Entry]
Type=Application
Name=Firewall
Name[de]=Firewall
Comment=See which ports are open and open or close more
Comment[de]=Offene Ports ansehen und weitere öffnen oder schließen
Icon=$ICONS_DIR/Cyberbeest-black.png
StartupWMClass=cyberbeest-firewall
Exec=$TARGET_HOME/.local/bin/cyberbeest_firewall_gui.py
Categories=Cyberbeest;Settings;
Terminal=false
StartupNotify=true
INNER
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/share/applications/cyberbeest-firewall.desktop"

echo "--- Refreshing desktop database ---"
sudo -u "$TARGET_USER" update-desktop-database "$TARGET_HOME/.local/share/applications" >/dev/null 2>&1 || true

echo "=== $(date) : done ==="
