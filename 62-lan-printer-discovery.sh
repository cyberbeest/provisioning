#!/bin/bash
# Turns off avahi-daemon (mDNS/DNS-SD, aka Bonjour/Zeroconf) by default and
# installs an opt-in toggle to turn it back on temporarily.
#
# avahi ships enabled on basically every desktop Linux distro for LAN
# printer/scanner auto-discovery and Thunar's "Network" browsing, but it
# also broadcasts this machine's hostname and sits on 3 UDP ports (5353
# plus two per-IP-family "legacy unicast" ports it self-assigns) reachable
# by anyone on the LAN -- and, as of this writing, nothing else in
# provisioning firewalls those off. Most people set up a network printer
# once in a while, not continuously, so this makes discovery opt-in
# instead: off by default, one Whisker click to turn it on for the current
# boot only (see lib/setup_avahi_toggle.py for the toggle itself).
#
# Masking (not just disabling) both units matters: avahi-daemon.socket
# alone can respawn avahi-daemon.service via D-Bus activation (see
# /usr/share/dbus-1/system-services/org.freedesktop.Avahi.service) the
# moment anything -- cups-browsed, a GLib zeroconf lookup -- asks for the
# org.freedesktop.Avahi bus name. `disable` alone removes the enablement
# symlinks (including that D-Bus alias), which should already be enough,
# but masking is the belt-and-suspenders way 37-encrypted-dns.sh also uses
# for the packaged dnscrypt-proxy units, so the off state can't be
# accidentally reawakened by something else asking for the service.
#
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/62-lan-printer-discovery.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) starting 62-lan-printer-discovery.sh ==="

echo "--- ensuring avahi-daemon is installed (idempotent) ---"
apt-get -o DPkg::Lock::Timeout=60 install -y avahi-daemon

echo "--- stopping and masking avahi-daemon.service/.socket (off by default) ---"
systemctl stop avahi-daemon.service avahi-daemon.socket 2>&1 || true
systemctl mask avahi-daemon.service avahi-daemon.socket

echo "--- installing scoped sudoers rule for the enable/disable toggle ---"
SUDOERS_FILE=/etc/sudoers.d/avahi-toggle
TMP_FILE="$(mktemp)"
cat > "$TMP_FILE" <<'EOF'
cyberbeest ALL=(root) NOPASSWD: /usr/bin/systemctl unmask avahi-daemon.service avahi-daemon.socket
cyberbeest ALL=(root) NOPASSWD: /usr/bin/systemctl start avahi-daemon.service avahi-daemon.socket
cyberbeest ALL=(root) NOPASSWD: /usr/bin/systemctl stop avahi-daemon.service avahi-daemon.socket
cyberbeest ALL=(root) NOPASSWD: /usr/bin/systemctl mask avahi-daemon.service avahi-daemon.socket
EOF
if visudo -c -f "$TMP_FILE"; then
    install -m 0440 -o root -g root "$TMP_FILE" "$SUDOERS_FILE"
else
    echo "FAIL: visudo syntax check failed for avahi-toggle sudoers rule" >&2
    rm -f "$TMP_FILE"
    exit 1
fi
rm -f "$TMP_FILE"

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- installing LAN-discovery toggle scripts for $TARGET_USER ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
    "$DIR/lib/setup_avahi_toggle.py" "$TARGET_HOME/.local/bin/setup_avahi_toggle.py"
runuser -u "$TARGET_USER" -- python3 "$TARGET_HOME/.local/bin/setup_avahi_toggle.py"

echo "=== $(date) SUCCESS: avahi-daemon is off by default, toggle installed ==="
