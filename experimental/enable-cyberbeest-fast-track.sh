#!/bin/bash
# EXPERIMENTAL: Cyberbeest Fast Track -- for machines that follow the beta
# track (~/provisioning-bleeding, branch main) and should offer new commits
# within minutes instead of waiting for someone to open Cyberbeest Update.
#
# This script only installs. The Whisker entry "Cyberbeest Fast Track" turns it
# on (starts the watcher, adds the panel icon, remembers "on" for next login);
# the icon's menu has "Stop Fast Track". The watcher (lib/cyberbeest-fasttrack.sh) checks the
# v-server's doorbell file once a minute and, when main has a commit this
# checkout lacks, shows the Cyberbeest Update confirm dialog. After "Yes" the
# changed scripts run automatically (run-gui.py --run-changed); the sudo
# password prompt still appears as usual. The doorbell is described in
# cyberbeest-vserver/README.md ("fasttrack/").
#
# Needs the normal Cyberbeest Update (52-cyberbeest-update.sh) installed.
# Also adds a Whisker menu entry ("Cyberbeest Fast Track") and a panel icon
# (genmon plugin-230: up to date / update available; click menu with check now,
# open Cyberbeest Update, stop).
#
# Opt-out without uninstalling: sudo touch /etc/cyberbeest/fasttrack-disabled
# Usage: sudo bash enable-cyberbeest-fast-track.sh
# Undo:  sudo bash disable-cyberbeest-fast-track.sh
# Idempotent: safe to re-run.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/enable-cyberbeest-fast-track.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing Cyberbeest Fast Track ==="

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
BIN="$TARGET_HOME/.local/bin"

if [ ! -x "$BIN/cyberbeest-update.sh" ]; then
	echo "cyberbeest-update.sh not installed -- run 52-cyberbeest-update.sh first." >&2
	exit 1
fi

install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 "$DIR/lib/cyberbeest-fasttrack.sh" "$BIN/cyberbeest-fasttrack.sh"
# The update script and run-gui.py must carry the --fast-track/--run-changed
# support, so refresh the installed copy too.
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 "$DIR/../lib/cyberbeest-update.sh" "$BIN/cyberbeest-update.sh"
for f in fasttrack-genmon.sh fasttrack-menu.py fasttrack-panel-icon.sh fasttrack-start.sh fasttrack-stop.sh; do
	install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 "$DIR/lib/$f" "$BIN/$f"
done
install -d -m 755 /etc/cyberbeest
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/cyberbeest-fasttrack"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR"/lib/fasttrack-icons/*.png "$TARGET_HOME/.local/share/cyberbeest-fasttrack/"

echo "--- Whisker menu entry ---"
APPS="$TARGET_HOME/.local/share/applications"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$APPS"
cat > "$APPS/cyberbeest-fast-track.desktop" <<EOT
[Desktop Entry]
Type=Application
Name=Cyberbeest Fast Track
Name[de]=Cyberbeest Fast Track
Comment=Turn on Fast Track: confirmation box whenever there is new code
Comment[de]=Fast Track einschalten: Bestätigungsfenster bei jedem neuen Code
Icon=$TARGET_HOME/.local/share/cyberbeest-fasttrack/fasttrack-ok.png
Exec=$BIN/fasttrack-start.sh
Categories=Cyberbeest;Settings;
Terminal=false
StartupNotify=true
EOT
chown "$TARGET_USER:$TARGET_USER" "$APPS/cyberbeest-fast-track.desktop"
sudo -u "$TARGET_USER" update-desktop-database "$APPS" >/dev/null 2>&1 || true

AUTOSTART="$TARGET_HOME/.config/autostart"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$AUTOSTART"
cat > "$AUTOSTART/cyberbeest-fasttrack.desktop" <<EOT
[Desktop Entry]
Type=Application
Name=Cyberbeest Fast Track
Exec=sh -c '[ -e "\$HOME/.local/state/cyberbeest-fasttrack/enabled" ] && exec "\$HOME/.local/bin/cyberbeest-fasttrack.sh"'
Terminal=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
EOT
chown "$TARGET_USER:$TARGET_USER" "$AUTOSTART/cyberbeest-fasttrack.desktop"

echo "=== $(date) : done ==="
