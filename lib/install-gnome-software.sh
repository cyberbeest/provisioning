#!/bin/bash
# Install GNOME Software as a Synaptic replacement: uses AppStream metadata
# for a curated app-store view (unlike gnome-packagekit's raw apt-section
# listing). flatpak/snap plugins are only Debian "Suggests" here, not
# "Recommends", so they are not pulled in.
#
# Run with sudo:
#   sudo bash ~/provisioning/lib/install-gnome-software.sh (normally invoked via ../02-gnome-software-store.sh)

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/install-gnome-software.log"
exec > >(tee -a "$LOG") 2>&1
echo "=== $(date '+%Y-%m-%d %H:%M:%S') install-gnome-software.sh ==="

apt-get -o DPkg::Lock::Timeout=60 update
apt-get -o DPkg::Lock::Timeout=60 install -y gnome-software gnome-software-plugin-deb

echo "Confirming no flatpak/snap plugins were pulled in:"
dpkg -l | grep -i 'gnome-software-plugin' || true

echo "gnome-software installed."

# GNOME Software's background updater applies updates via PackageKit's
# "offline update" flow, which always forces a reboot to apply -- even for a
# trivial package -- independent of and bypassing the deliberate
# Unattended-Upgrade::Automatic-Reboot "false" setting. Disable it outright
# rather than relying on every user's dconf state.
cat >/usr/share/glib-2.0/schemas/95-cyberbeest-gnome-software.gschema.override <<'EOF'
[org.gnome.software]
allow-updates=false
download-updates=false
EOF
glib-compile-schemas /usr/share/glib-2.0/schemas/
echo "Disabled gnome-software's background auto-updater (allow-updates/download-updates)."

# Debian's stock org.gnome.Software.Featured.xml references ~59 GNOME Circle
# apps by ID. Most never resolve on a plain Debian install, but once real
# archive-wide AppStream data (dep11) gets fetched, some of them do, and
# flood the Explore page's Featured carousel with unrelated apps. Disable it.
STOCK_FEATURED=/usr/share/swcatalog/xml/org.gnome.Software.Featured.xml
if [ -f "$STOCK_FEATURED" ]; then
    mv "$STOCK_FEATURED" "$STOCK_FEATURED.disabled"
    echo "Disabled stock GNOME Circle featured list ($STOCK_FEATURED.disabled)"
fi
