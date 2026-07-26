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
