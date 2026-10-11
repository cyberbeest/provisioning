#!/bin/bash
# EXPERIMENTAL: Cyberbeest Fast Track -- for machines that follow the beta
# track (~/provisioning-bleeding, branch main) and should offer new commits
# within minutes instead of waiting for someone to open Cyberbeest Update.
#
# A small watcher (lib/cyberbeest-fasttrack.sh) starts at login, checks the
# v-server's doorbell file once a minute and, when main has a commit this
# checkout lacks, shows the Cyberbeest Update confirm dialog. After "Yes" the
# changed scripts run automatically (run-gui.py --run-changed); the sudo
# password prompt still appears as usual. The doorbell is described in
# cyberbeest-vserver/README.md ("fasttrack/").
#
# Needs the normal Cyberbeest Update (52-cyberbeest-update.sh) installed.
# Also adds a Whisker menu entry ("Cyberbeest Fast Track") and a panel icon
# (genmon plugin-230: up to date / update available / paused; click menu with
# check now, open Cyberbeest Update, pause/resume).
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
for f in fasttrack-genmon.sh fasttrack-menu.py fasttrack-panel-icon.sh; do
	install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 "$DIR/lib/$f" "$BIN/$f"
done
install -d -m 755 /etc/cyberbeest

echo "--- Whisker menu entry ---"
APPS="$TARGET_HOME/.local/share/applications"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$APPS"
cat > "$APPS/cyberbeest-fast-track.desktop" <<EOT
[Desktop Entry]
Type=Application
Name=Cyberbeest Fast Track
Name[de]=Cyberbeest Fast Track
Comment=Check for new Cyberbeest updates now and apply them after confirmation
Comment[de]=Jetzt nach neuen Cyberbeest-Updates suchen und sie nach Bestätigung anwenden
Icon=software-update-available
Exec=$BIN/cyberbeest-update.sh --fast-track
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
Exec=$BIN/cyberbeest-fasttrack.sh
Terminal=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
EOT
chown "$TARGET_USER:$TARGET_USER" "$AUTOSTART/cyberbeest-fasttrack.desktop"

echo "--- (Re)starting the watcher now ---"
pkill -u "$TARGET_USER" -f '[c]yberbeest-fasttrack\.sh' || true
sleep 1
sudo -u "$TARGET_USER" env DISPLAY="${DISPLAY:-:0}" XAUTHORITY="$TARGET_HOME/.Xauthority" \
	setsid -f "$BIN/cyberbeest-fasttrack.sh" >/dev/null 2>&1 || true

echo "--- Panel icon (plugin-230) ---"
sudo -u "$TARGET_USER" env DISPLAY="${DISPLAY:-:0}" XAUTHORITY="$TARGET_HOME/.Xauthority" \
	DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u "$TARGET_USER")/bus" \
	"$BIN/fasttrack-panel-icon.sh" add || echo "panel icon not added (no graphical session?)"

echo "=== $(date) : done ==="
