#!/bin/bash
# Installs the Cyberbeest Power Settings GUI (lock/shutdown timing config)
# as a regular app under Whisker's Settings category (not pinned to the
# panel -- the panel's own "Power" launcher is the logout dialog, see
# 12-xfce-panel-layout.sh) -- see lib/cyberbeest-power-settings.py.
# This GUI only edits ~/.config/cyberbeest/power-settings.conf; the
# lock-shutdown-watcher user service that actually reads that file and
# enforces the lock/shutdown/suspend-cycle behavior is installed separately
# by 13-lock-shutdown-watcher.sh.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/08-cyberbeest-power-settings.log"
exec > "$LOG" 2>&1

echo "=== $(date) : installing cyberbeest-power-settings ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- Installing python3-gi (GTK bindings the GUI needs) ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y python3-gi gir1.2-gtk-3.0

echo "--- Installing GUI script to $TARGET_HOME/.local/bin/cyberbeest-power-settings ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
# GENMON_WIDGET_NAME must match the shutdown-timer genmon plugin id that
# 12-xfce-panel-layout.sh's panel template assigns (genmon-16), so the
# "refresh the panel icon now" call in the GUI targets the right widget.
sed "s|__GENMON_WIDGET__|genmon-16|g" "$DIR/lib/cyberbeest-power-settings.py" \
	> "$TARGET_HOME/.local/bin/cyberbeest-power-settings"
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/bin/cyberbeest-power-settings"
chmod 755 "$TARGET_HOME/.local/bin/cyberbeest-power-settings"

# i18n.py does `from i18n import t`, which only resolves if i18n.py (and its
# strings_*.py catalogs) sit next to the installed script -- see lib/i18n.py.
echo "--- Installing shared i18n runtime ---"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR/lib/i18n.py" "$TARGET_HOME/.local/bin/i18n.py"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin/i18n"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR"/lib/i18n/strings_*.py "$TARGET_HOME/.local/bin/i18n/"

echo "--- Installing icon ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/Pictures"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/assets/Cyberbeest-black.png" \
	"$TARGET_HOME/Pictures/Cyberbeest-black.png"

echo "--- Installing app menu entry (Whisker menu, Settings category) ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/applications"
cat > "$TARGET_HOME/.local/share/applications/cyberbeest-power-settings.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Cyberbeest Power Settings
Name[de]=Cyberbeest-Energieeinstellungen
Comment=Configure Cyberbeest lock/suspend/notification behavior
Comment[de]=Sperr-/Ruhezustands-/Benachrichtigungsverhalten von Cyberbeest konfigurieren
Exec=$TARGET_HOME/.local/bin/cyberbeest-power-settings
Icon=$TARGET_HOME/Pictures/Cyberbeest-black.png
Terminal=false
Categories=Cyberbeest;Settings;
StartupNotify=true
EOF
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/share/applications/cyberbeest-power-settings.desktop"

echo "=== $(date) : done ==="
