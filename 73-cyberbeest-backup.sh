#!/bin/bash
# Installs Cyberbeest Backup: a graphical full-disk backup and restore.
# Backup copies EFI, /boot, the LUKS header, the LVM layout and a compressed
# partclone image of the root volume (read from an LVM snapshot, so the system
# keeps running) into one LUKS2 container file on an external drive, locked
# with the computer's master password. The Find-files tab unpacks it into a
# scratch file and mounts that read-only to copy single files out. Restore, normally run from the live
# stick, rebuilds the disk from such a folder. The privileged work happens in
# lib/cyberbeest-{backup,restore}-helper.sh under pkexec; the polkit policy
# authorising them is installed here (same pattern as 59-cyberbeest-scanner.sh).
#
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/73-cyberbeest-backup.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing Cyberbeest Backup ==="

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- Installing partclone, zstd, cryptsetup, lvm2, efibootmgr, python3-gi ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y partclone zstd cryptsetup lvm2 efibootmgr util-linux e2fsprogs python3-gi gir1.2-gtk-3.0

echo "--- Installing privileged helpers + polkit policy ---"
install -d /usr/local/lib/cyberbeest
install -m 755 "$DIR/lib/cyberbeest-backup-common.sh" "$DIR/lib/cyberbeest-backup-helper.sh" \
  "$DIR/lib/cyberbeest-restore-helper.sh" "$DIR/lib/cyberbeest-extract-helper.sh" /usr/local/lib/cyberbeest/
install -m 644 "$DIR/lib/com.cyberbeest.backup.policy" /usr/share/polkit-1/actions/com.cyberbeest.backup.policy

echo "--- Installing GUI and its i18n helper ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin" "$TARGET_HOME/.local/bin/i18n"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR/lib/i18n.py" "$TARGET_HOME/.local/bin/i18n.py"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR"/lib/i18n/strings_*.py "$TARGET_HOME/.local/bin/i18n/"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 "$DIR/lib/cyberbeest_backup_gui.py" "$TARGET_HOME/.local/bin/cyberbeest_backup_gui.py"

echo "--- Installing Whisker menu entry ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/applications"
cat > "$TARGET_HOME/.local/share/applications/cyberbeest-backup.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Cyberbeest Backup
Name[de]=Cyberbeest Sicherung
Comment=Back up or restore the whole computer
Comment[de]=Den ganzen Computer sichern oder wiederherstellen
Exec=$TARGET_HOME/.local/bin/cyberbeest_backup_gui.py
Icon=drive-harddisk
Categories=Cyberbeest;Settings;
Terminal=false
StartupNotify=true
DESKTOP
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/share/applications/cyberbeest-backup.desktop"
sudo -u "$TARGET_USER" update-desktop-database "$TARGET_HOME/.local/share/applications" >/dev/null 2>&1 || true

echo "=== $(date) : done ==="
