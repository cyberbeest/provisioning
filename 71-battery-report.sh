#!/bin/bash
# Installs "Battery Report" (lib/cyberbeest_battery_report.py): a graphical report on how long the
# battery lasts per charge when locked and when working, plus a multi-day timeline of power state,
# charge and draw. It reads the history the panel's wattage widget already logs every 5 minutes
# (~/.local/state/wattage-panel/history.csv), so there is nothing to collect and nothing to run in
# the background.
#
# The report is a self-contained HTML page, shown in the sandboxed Firefox through a dedicated
# profile whose userChrome.css hides tabs and address bar (the script creates that profile on first
# use). It is written to ~/Downloads/.battery-report.html because that is a folder the browser jail
# can read. Dependencies: python3 and firefox, both already part of the base install.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/71-battery-report.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing Battery Report ==="

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- Installing script to $TARGET_HOME/.local/bin ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
    "$DIR/lib/cyberbeest_battery_report.py" "$TARGET_HOME/.local/bin/cyberbeest_battery_report.py"

echo "--- Installing icon ---"
ICONS_DIR="$TARGET_HOME/.local/share/cyberbeest/icons"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$ICONS_DIR"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
    "$DIR/lib/assets/Cyberbeest-black.png" "$ICONS_DIR/Cyberbeest-black.png"

echo "--- Installing Whisker menu entry ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/applications"
cat > "$TARGET_HOME/.local/share/applications/cyberbeest-battery-report.desktop" <<INNER
[Desktop Entry]
Type=Application
Name=Battery Report
Name[de]=Akkubericht
Comment=See how long your battery lasts, locked and at work
Comment[de]=Zeigen, wie lange der Akku hält, gesperrt und bei der Arbeit
Icon=$ICONS_DIR/Cyberbeest-black.png
Exec=$TARGET_HOME/.local/bin/cyberbeest_battery_report.py
Categories=Cyberbeest;Settings;
Terminal=false
StartupNotify=false
INNER
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/share/applications/cyberbeest-battery-report.desktop"

echo "--- Refreshing desktop database ---"
sudo -u "$TARGET_USER" update-desktop-database "$TARGET_HOME/.local/share/applications" >/dev/null 2>&1 || true

echo "=== $(date) : done ==="
