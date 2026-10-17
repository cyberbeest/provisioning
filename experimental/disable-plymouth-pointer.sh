#!/bin/bash
# Undoes enable-plymouth-pointer.sh: puts the stock Plymouth files back, removes
# the "evdev" line from /etc/initramfs-tools/modules if the enable script added
# it, and regenerates the initramfs of every installed kernel.
#
# Needs the stock backup the enable script made in
# /var/backups/cyberbeest/plymouth-pointer/stock. If Plymouth was upgraded since
# (so the backup no longer matches the installed package), the files are
# reinstalled from the package instead, which needs the package cache or network.
#
# Usage: sudo bash disable-plymouth-pointer.sh
# Idempotent: safe to re-run.
set -uo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/disable-plymouth-pointer.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : removing the Plymouth mouse pointer ==="

[ "$(id -u)" -eq 0 ] || {
	echo "Must run as root (sudo bash $0)." >&2
	exit 1
}

LIB=/usr/lib/x86_64-linux-gnu
BACKUP_DIR=/var/backups/cyberbeest/plymouth-pointer
STOCK="$BACKUP_DIR/stock"
EVDEV_MARK="$BACKUP_DIR/added-evdev"
MODFILE=/etc/initramfs-tools/modules

is_fork() { grep -aq ply_pointer_new "$1" 2>/dev/null; }

installed_ver="$(dpkg-query -W -f='${Version}' plymouth 2>/dev/null)"

if is_fork "$LIB/libply-splash-core.so.5.0.0"; then
	stock_ver="$(cat "$STOCK/version" 2>/dev/null || true)"
	if [ -d "$STOCK/files" ] && [ "$stock_ver" = "$installed_ver" ]; then
		(cd "$STOCK/files" && find . -type f) | while read -r f; do
			f="${f#./}"
			cp -a "$STOCK/files/$f" "$LIB/$f.new" && mv -f "$LIB/$f.new" "$LIB/$f" && echo "restored $f"
		done
		ldconfig
	else
		echo "No matching stock backup (backup is for '${stock_ver:-none}', installed is '$installed_ver'); reinstalling from the package."
		apt-get install --reinstall -y plymouth libplymouth5 || {
			echo "Reinstalling failed. The pointer build is still installed." >&2
			exit 1
		}
	fi
else
	echo "The stock Plymouth files are already in place."
fi

# Remove the two lines the enable script added, but only if it added them
if [ -f "$EVDEV_MARK" ]; then
	sed -i '/^# added by the Cyberbeest Plymouth pointer install/,+1d' "$MODFILE"
	rm -f "$EVDEV_MARK"
	echo "removed the evdev entry from $MODFILE"
fi

echo "Regenerating the initramfs of every kernel ..."
update-initramfs -u -k all || {
	echo "update-initramfs failed; the saved initrd for the running kernel is in $STOCK" >&2
	exit 1
}

echo "Done. Stock Plymouth is installed again; reboot to use it."
