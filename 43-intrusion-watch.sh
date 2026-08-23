#!/bin/bash
# Installs Cyberbeest Intrusion Watch: a manually launched, poll-mode
# intrusion-detection scanner (see lib/cyberbeest_intrusion_watch_gui.py).
# "Scan Now" or an optional auto-scan timer runs a handful of cheap, local
# checks -- SSH/sudo/LightDM failed-auth attempts, USB device insertions,
# a DNS NXDOMAIN spike check against dnscrypt-proxy's logs, and baseline-
# diff checks for unexpected listening ports and unexpected autostart/
# cron/systemd-enabled entries. Each check shows OK/WARN/ALERT/N-A rather
# than a silent false "OK" when it can't actually see anything (e.g. no
# sshd installed, or no journal read access).
#
# The journalctl-based checks need the 'adm' group for journal read
# access -- granted below directly (this script already runs as root),
# unlike the dev machine's manual RUNME dance for the same grant. Group
# membership only takes effect on next login; harmless to grant early
# during provisioning since the user hasn't logged in interactively yet
# in most install flows, and is a no-op if already granted.
#
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/43-intrusion-watch.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing Cyberbeest Intrusion Watch ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- Installing python3-gi (GTK bindings the GUI needs) ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y python3-gi gir1.2-gtk-3.0

echo "--- Granting the 'adm' group (system journal read access) ---"
usermod -aG adm "$TARGET_USER"

echo "--- Installing script to $TARGET_HOME/.local/bin ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
    "$DIR/lib/cyberbeest_intrusion_watch_gui.py" \
    "$TARGET_HOME/.local/bin/cyberbeest_intrusion_watch_gui.py"

echo "--- Installing Whisker menu entry ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/applications"
cat > "$TARGET_HOME/.local/share/applications/cyberbeest-intrusion-watch.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Cyberbeest Intrusion Watch
Comment=Poll-mode scan for SSH/sudo/login failures, USB insertions, DNS anomalies, and unexpected ports or autostart entries
Exec=$TARGET_HOME/.local/bin/cyberbeest_intrusion_watch_gui.py
Icon=security-high
Categories=Cyberbeest;Settings;
Terminal=false
StartupNotify=true
EOF
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/share/applications/cyberbeest-intrusion-watch.desktop"

echo "--- Refreshing desktop database ---"
sudo -u "$TARGET_USER" update-desktop-database "$TARGET_HOME/.local/share/applications" >/dev/null 2>&1 || true

echo "=== $(date) : done ==="
