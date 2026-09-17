#!/bin/bash
# Builds and installs the custom xfce4-panel plugins (cpuload-color,
# kitt-scanner, wattage-panel, mem-liquid, io-scanner) from source -- see
# lib/xfce-panel-plugins/. Built on the target rather than shipped as
# prebuilt .so files, since the panel plugin ABI is tied to the exact
# xfce4-panel/gtk3 versions installed, which a binary can't guarantee.
# Idempotent: safe to re-run (make install just overwrites).
# 2026-09-17: adds io-scanner, a green vertical KITT-style sweep whose
# speed tracks disk I/O (MB/s summed across all physical disks, immune to
# multi-disk/dm-crypt double-counting -- see the file's header comment).
# Installed like the others but deliberately NOT added to 12-xfce-panel-
# layout.sh's default layout -- available for a user to add by hand via
# the panel's own "add new item" dialog, not shown out of the box.
# 2026-08-28: kitt-scanner/mem-liquid top-3 dedup fix (coalesce on the
# aliased name, not the raw comm) -- bumps this script so run-gui's
# change-detection re-runs it after a lib/ dep-only edit.
# 2026-08-28: mem-liquid contention warning fix -- exclude Shmem from the
# CountMapped "passive cache" credit (tmpfs/shared-memory pages aren't
# reclaimable page cache), so the displayed % and the warning threshold
# stop diverging when Shmem usage is large.
# 2026-09-11: wattage-panel shows an empty label instead of the "no
# battery" text on machines without a battery.
# 2026-09-16: lib/xfce-panel-reload.sh no longer SIGKILLs xfconfd during
# reload -- that raced xfconfd's async disk flush and could revert a
# just-written xfconf change (zombie panel icon seen on tower). Bumped
# so run-gui re-applies this lib-only fix.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/11-xfce-panel-plugins.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : building custom xfce4-panel plugins ==="

echo "--- Installing build dependencies ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y build-essential pkg-config gettext \
	libxfce4panel-2.0-dev libxfce4util-dev libxfce4ui-2-dev \
	libgtk-3-dev libx11-dev libxext-dev

echo "--- Building and installing plugins ---"
make -C "$DIR/lib/xfce-panel-plugins" clean install

echo "--- Reloading xfce4-panel for the logged-in user, if one is running ---"
TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
. "$DIR/lib/xfce-panel-reload.sh"
if xfce_panel_dbus_addr; then
	xfce_panel_kill
	xfce_panel_launch || echo "--- warning: panel reload didn't take live effect ---" >&2
fi

echo "=== $(date) : done ==="
