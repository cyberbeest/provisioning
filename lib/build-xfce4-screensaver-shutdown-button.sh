#!/bin/bash
# Rebuilds xfce4-screensaver from Debian source with a "Shut Down" button
# added to the unlock dialog's button row (Switch User / Log Out / Cancel
# / Unlock), applying shutdown-button.patch. Click once to arm ("Really
# Shut Down?"), click again within 4s to run `systemctl poweroff`
# (auto-disarms otherwise) -- a modal confirmation dialog was tried first
# but conflicts with the lock screen's X11 input grab.
#
# NOTE: the .ui file only gets recompiled into the binary under
# MAINTAINER_MODE, which upstream's build disables by default. This
# script regenerates src/xfce4-screensaver-dialog-ui.h by hand with
# xdt-csource after applying the patch -- skipping that step silently
# ships the unpatched button layout.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_ROOT="/tmp/cyberbeest-xfce4-screensaver-build"
TARGET_USER="${SUDO_USER:-cyberbeest}"

echo "=== $(date) : building xfce4-screensaver with shutdown button ==="

apt-get update
apt-get build-dep -y xfce4-screensaver
apt-get install -y devscripts xfce4-dev-tools

rm -rf "$BUILD_ROOT"
mkdir -p "$BUILD_ROOT"
cd "$BUILD_ROOT"
apt-get source xfce4-screensaver

SRC_DIR="$(find "$BUILD_ROOT" -maxdepth 1 -type d -name 'xfce4-screensaver-*' | head -1)"
cd "$SRC_DIR"

patch -p1 < "$DIR/../shutdown-button.patch"

xdt-csource --static --strip-comments --strip-content \
    --name=xfce4_screensaver_dialog_ui \
    src/xfce4-screensaver-dialog.ui > src/xfce4-screensaver-dialog-ui.h

dpkg-buildpackage -us -uc -b

DEB="$(find "$BUILD_ROOT" -maxdepth 1 -name 'xfce4-screensaver_*.deb' | head -1)"
apt-get install -y --allow-downgrades --reinstall "$DEB"

echo "=== restarting xfce4-screensaver for $TARGET_USER ==="
PID=$(pgrep -u "$TARGET_USER" -f '/xfce4-screensaver$' | head -1 || true)
if [ -n "$PID" ]; then
    ENVFILE="/proc/$PID/environ"
    DISPLAY_VAL=$(tr '\0' '\n' < "$ENVFILE" | sed -n 's/^DISPLAY=//p')
    DBUS_VAL=$(tr '\0' '\n' < "$ENVFILE" | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')
    XAUTH_VAL=$(tr '\0' '\n' < "$ENVFILE" | sed -n 's/^XAUTHORITY=//p')

    kill "$PID"
    sleep 1

    sudo -u "$TARGET_USER" env \
        DISPLAY="$DISPLAY_VAL" \
        DBUS_SESSION_BUS_ADDRESS="$DBUS_VAL" \
        XAUTHORITY="$XAUTH_VAL" \
        nohup /usr/bin/xfce4-screensaver >/dev/null 2>&1 &
    disown
    echo "Restarted xfce4-screensaver (old pid $PID)"
else
    echo "No running xfce4-screensaver process found for $TARGET_USER; it will pick up the new binary next login."
fi

echo "=== fixing gvfs-trash shutdown delay: skip trash-checking on /boot/efi ==="
if grep -qE "boot/efi.*vfat.*umask=0077" /etc/fstab && ! grep -q "x-gvfs-notrash" /etc/fstab; then
    cp /etc/fstab /etc/fstab.pre-cyberbeest-notrash
    sed -i '/boot\/efi/ s/umask=0077/umask=0077,x-gvfs-notrash/' /etc/fstab
    echo "Updated /etc/fstab (backup at /etc/fstab.pre-cyberbeest-notrash)"
else
    echo "fstab already has x-gvfs-notrash or doesn't match the expected line; skipped"
fi

rm -rf "$BUILD_ROOT"
