#!/bin/bash
# Installs Cyberbeest Security Watch: a manually launched, tabbed Whisker
# menu app showing recent Debian Security Advisories, high/critical CVEs
# (NVD), recent Exploit-DB entries, and this machine's own permanent record
# of every package it has installed/upgraded (see lib/cyberbeest_security_watch_gui.py).
#
# The 4th tab reads from a permanent log that /var/log/apt/history.log and
# /var/log/dpkg.log can't provide on their own -- those get logrotated away
# after ~12 months. lib/log-security-updates.py parses history.log plus
# each package's own local Debian changelog to record not just old->new
# version numbers but the actual changelog/CVE text for the update, flags
# it security-relevant if a CVE or urgency=high/critical is mentioned, and
# appends to ~/.config/cyberbeest/security-update-history.jsonl, which is
# never rotated or truncated. Runs entirely as the normal user (reads only
# world-readable logs) -- no apt hook, no root needed for the logging
# itself, kept current by a systemd --user timer (daily + up to 1h jitter).
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/42-security-watch.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing Cyberbeest Security Watch ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
TARGET_UID="$(id -u "$TARGET_USER")"

echo "--- Installing python3-gi (GTK bindings the GUI needs) ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y python3-gi gir1.2-gtk-3.0

echo "--- Installing scripts to $TARGET_HOME/.local/bin ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
    "$DIR/lib/cyberbeest_security_watch_gui.py" \
    "$TARGET_HOME/.local/bin/cyberbeest_security_watch_gui.py"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
    "$DIR/lib/log-security-updates.py" \
    "$TARGET_HOME/.local/bin/log-security-updates.py"

echo "--- Installing Whisker menu entry ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/applications"
cat > "$TARGET_HOME/.local/share/applications/cyberbeest-security-watch.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Cyberbeest Security Watch
Comment=Latest Debian security advisories, CVEs, exploits, and this machine's update history
Exec=$TARGET_HOME/.local/bin/cyberbeest_security_watch_gui.py
Icon=security-high
Categories=Cyberbeest;Settings;
Terminal=false
StartupNotify=true
EOF
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/share/applications/cyberbeest-security-watch.desktop"

echo "--- Installing systemd user service + daily timer ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/systemd/user"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
    "$DIR/lib/cyberbeest-security-update-log.service" \
    "$TARGET_HOME/.config/systemd/user/cyberbeest-security-update-log.service"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
    "$DIR/lib/cyberbeest-security-update-log.timer" \
    "$TARGET_HOME/.config/systemd/user/cyberbeest-security-update-log.timer"

echo "--- Enabling the timer (WantedBy=timers.target) ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/systemd/user/timers.target.wants"
ln -sf ../cyberbeest-security-update-log.timer \
    "$TARGET_HOME/.config/systemd/user/timers.target.wants/cyberbeest-security-update-log.timer"
chown -h "$TARGET_USER:$TARGET_USER" \
    "$TARGET_HOME/.config/systemd/user/timers.target.wants/cyberbeest-security-update-log.timer"

echo "--- Starting the timer now and backfilling the log, if the target user has an active session ---"
if [ -d "/run/user/$TARGET_UID" ]; then
    sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" \
        systemctl --user daemon-reload
    sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" \
        systemctl --user enable --now cyberbeest-security-update-log.timer
    sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" \
        systemctl --user start cyberbeest-security-update-log.service || true
else
    echo "no active session for $TARGET_USER -- timer will enable and the log will backfill at next login"
fi

echo "--- Refreshing desktop database ---"
sudo -u "$TARGET_USER" update-desktop-database "$TARGET_HOME/.local/share/applications" >/dev/null 2>&1 || true

echo "=== $(date) : done ==="
