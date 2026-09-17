#!/bin/bash
# Installs the Cyberbeest Malware Scanner: a manually launched GUI that runs
# debsums (base-system file integrity), ClamAV (known-malware signatures),
# rkhunter and chkrootkit (rootkit signatures/heuristics), then shows a
# rule-based verdict -- no AI reads the results, see lib/interpret_results.py
# for why.
#
# clamd (the ClamAV daemon) is installed but left DISABLED/stopped by
# default -- its resident signature database (order of ~1GB RAM) would
# undercut the notification-mode/34h-battery pitch if it ran all the time
# on every unit. The privileged helper starts it right before a scan and
# stops it right after; see lib/cyberbeest-scanner-helper.sh. This mirrors
# 51-fail2ban.sh's "install but don't run unless actually needed" pattern.
# clamav-freshclam's own background update timer IS left at its default
# enabled state -- it's a brief periodic check, not a resident process, so
# it doesn't carry the same cost and keeps signatures current without
# requiring clamd to be running.
#
# rkhunter's file-property baseline is built here, at provisioning time,
# while the machine is in a known-clean state -- this is the ideal moment
# for that baseline (avoids the "everything looks new" warnings a first
# customer-run scan would otherwise show).
#
# Privileged scan actions happen via lib/cyberbeest-scanner-helper.sh under
# pkexec, so the polkit policy authorizing that (root-owned, not writable
# by the target user) is installed here -- same pattern as
# 22-i2p-package-manager.sh's cyberbeest-pkg-helper.sh.
#
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/59-cyberbeest-scanner.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing Cyberbeest Malware Scanner ==="

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- Installing clamav-daemon, rkhunter, chkrootkit, debsums, python3-gi ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y \
  clamav-daemon rkhunter chkrootkit debsums python3-gi gir1.2-gtk-3.0

echo "--- Configuring clamd (excludes/size caps; matches core count) ---"
CONF=/etc/clamav/clamd.conf
set_directive() {
  local key="$1" value="$2"
  if grep -qE "^${key}\b" "$CONF"; then
    sed -i "s|^${key}\b.*|${key} ${value}|" "$CONF"
  else
    echo "${key} ${value}" >> "$CONF"
  fi
}
set_directive MaxThreads "$(nproc)"
set_directive MaxFileSize 200M
set_directive MaxScanSize 1000M
grep -qxF 'ExcludePath ^/proc/' "$CONF" || cat >> "$CONF" <<'EOF'
ExcludePath ^/proc/
ExcludePath ^/sys/
ExcludePath ^/dev/
ExcludePath ^/run/
ExcludePath \.cache/
ExcludePath ^/var/cache/
ExcludePath \.(qcow2|vdi|vmdk|iso|img)$
EOF

echo "--- Priming the virus database (one-off, so the first scan doesn't stall on it) ---"
systemctl stop clamav-freshclam.service 2>/dev/null || true
freshclam || true
systemctl start clamav-freshclam.service 2>/dev/null || true

echo "--- Leaving clamd disabled/stopped by default (started on demand per scan) ---"
systemctl stop clamav-daemon 2>/dev/null || true
systemctl disable clamav-daemon 2>/dev/null || true

echo "--- Building rkhunter's file-property baseline now, while the machine is clean ---"
rkhunter --propupd || true

echo "--- Installing privileged helper + polkit policy ---"
install -d /usr/local/lib/cyberbeest
sed "s|__TARGET_USER__|$TARGET_USER|g; s|__TARGET_HOME__|$TARGET_HOME|g" \
  "$DIR/lib/cyberbeest-scanner-helper.sh" \
  > /usr/local/lib/cyberbeest/cyberbeest-scanner-helper.sh
chmod 755 /usr/local/lib/cyberbeest/cyberbeest-scanner-helper.sh
install -m 644 "$DIR/lib/com.cyberbeest.scanner.policy" /usr/share/polkit-1/actions/com.cyberbeest.scanner.policy

echo "--- Installing GUI + support modules to $TARGET_HOME/.local/... ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
  "$DIR/lib/cyberbeest_scanner_gui.py" \
  "$TARGET_HOME/.local/bin/cyberbeest_scanner_gui.py"

install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/lib/cyberbeest-scanner"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
  "$DIR/lib/interpret_results.py" "$DIR/lib/manifest_diff.py" \
  "$TARGET_HOME/.local/lib/cyberbeest-scanner/"

install -d -o "$TARGET_USER" -g "$TARGET_USER" \
  "$TARGET_HOME/.local/share/cyberbeest/scanner/reports"

echo "--- Installing Whisker menu entry ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/applications"
cat > "$TARGET_HOME/.local/share/applications/cyberbeest-malware-scanner.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Cyberbeest Malware Scanner
Comment=Check for malware, rootkits, and tampered system files
Exec=$TARGET_HOME/.local/bin/cyberbeest_scanner_gui.py
Icon=security-high
Categories=Cyberbeest;Settings;
Terminal=false
StartupNotify=true
EOF
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/share/applications/cyberbeest-malware-scanner.desktop"

echo "--- Refreshing desktop database ---"
sudo -u "$TARGET_USER" update-desktop-database "$TARGET_HOME/.local/share/applications" >/dev/null 2>&1 || true

echo "=== $(date) : done ==="
