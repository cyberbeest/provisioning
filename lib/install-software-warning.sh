#!/bin/bash
# Installs a risk-acceptance warning that shows every time GNOME Software is
# launched (via app grid, menu, or D-Bus activation), before the real app
# starts. See cyberbeest-launch-software.sh for the dialog itself.
#
# Mechanism: org.gnome.Software.desktop declares DBusActivatable=true, so
# GLib launches it via D-Bus activation rather than forking its Exec= line
# directly. To gate that reliably we override both:
#   - the .desktop entry, in /usr/local/share/applications (takes priority
#     over /usr/share/applications in XDG_DATA_DIRS search order), with
#     DBusActivatable dropped and Exec= pointed at our wrapper
#   - the D-Bus service file, in /usr/local/share/dbus-1/services (same
#     priority reasoning), for any launch path that still activates it via
#     D-Bus directly (e.g. `gapplication launch`, xdg-open on an appstream:
#     link)
#
# Run with sudo:
#   sudo bash ~/provisioning/lib/install-software-warning.sh (normally invoked via ../04-software-launch-warning.sh)

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/install-software-warning.log"
exec > >(tee -a "$LOG") 2>&1
echo "=== $(date '+%Y-%m-%d %H:%M:%S') install-software-warning.sh ==="

if dpkg -s zenity >/dev/null 2>&1; then
    echo "zenity already installed, skipping apt install"
else
    apt-get update
    apt-get install -y zenity
fi

install -m 755 "$DIR/cyberbeest-launch-software.sh" /usr/local/bin/cyberbeest-launch-software

mkdir -p /usr/local/share/applications
sed \
    -e 's|^Exec=gnome-software %U|Exec=/usr/local/bin/cyberbeest-launch-software %U|' \
    -e '/^DBusActivatable=true$/d' \
    /usr/share/applications/org.gnome.Software.desktop \
    >/usr/local/share/applications/org.gnome.Software.desktop

mkdir -p /usr/local/share/dbus-1/services
cat >/usr/local/share/dbus-1/services/org.gnome.Software.service <<'EOF'
[D-BUS Service]
Name=org.gnome.Software
Exec=/usr/local/bin/cyberbeest-launch-software --gapplication-service
EOF

update-desktop-database /usr/local/share/applications 2>&1 || true

echo "Warning dialog installed. GNOME Software launches now go through cyberbeest-launch-software."

# Kill any running instance so the override actually applies next launch
# (GNOME Software runs as a background GApplication service and otherwise
# keeps running under the old desktop-file/D-Bus-service registration).
pkill -x gnome-software && echo "Killed running gnome-software so the override takes effect on next launch." || true
