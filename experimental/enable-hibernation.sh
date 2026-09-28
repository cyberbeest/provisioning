#!/bin/bash
# Enables hibernation (suspend-to-disk) on this machine. Experimental --
# not part of the numbered NN-*.sh provisioning sequence, and not run on
# every machine: unlike 31a-sdcard-no-wakeup.sh (harmless everywhere),
# this reserves real permanent disk space (a swapfile sized to this
# machine's RAM), so it's opt-in per machine, run manually.
#
# Consolidates what was worked out interactively on the dev machine
# 2026-09-28:
#  - LVM's volume group was too full to grow the existing small swap LV,
#    so this adds a swapfile on / instead (no unmount/resize needed).
#  - The image is written to swap in-kernel-compressed (LZO) plus
#    zero-page elision, so real usage lands well under raw RAM size --
#    but sizing is still done off total RAM for headroom under worst-case
#    (mostly incompressible, mostly resident) memory content.
#  - filefrag's column spacing shifts when a number is short, so the
#    physical-offset parse below uses a regex on the extent-0 row instead
#    of fixed awk field positions (the first attempt at this broke on
#    exactly that).
#  - Hibernate genuinely wrote the image and entered ACPI S4 but aborted
#    at the last moment ("Wakeup event detected during hibernation,
#    rolling back") -- root cause was the SD card reader's card-detect
#    GPIO firing during hibernate's own brief internal hardware-wake (to
#    write the image), which the kernel misread as an external wake
#    request. Fixed separately by 31a-sdcard-no-wakeup.sh, a prerequisite
#    for this script actually working, not merely a nice-to-have.
#  - /sys/power/disk mode (platform vs shutdown) turned out NOT to be the
#    cause of that abort -- both modes hit it identically before the
#    sdcard fix. Left on "shutdown" below anyway since that's the
#    configuration actually verified working end-to-end; "platform"
#    (ACPI-negotiated S4) was not re-tested after the real fix and adds
#    an extra negotiation step for no proven benefit here.
#
# Only unmasks hibernate.target + sleep.target -- suspend.target,
# hybrid-sleep.target and suspend-then-hibernate.target stay masked, so
# this machine still never offers plain suspend (see
# 31-disable-sleep-states.sh for why masking, not logind.conf's Allow*
# keys, is what actually enforces that).
#
# To undo: re-run 31-disable-sleep-states.sh (re-masks all five targets;
# the swapfile/GRUB/initramfs config left behind is inert with hibernate
# masked, no need to strip it out).
#
# Usage: sudo bash enable-hibernation.sh
# Depends on: 31a-sdcard-no-wakeup.sh should be run first (see above).
# Idempotent: safe to re-run (skips swapfile creation if one already
# exists at $SWAPFILE; re-derives and re-applies the resume config either
# way, which is harmless if unchanged).
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/enable-hibernation.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : enabling hibernation ==="

if [ "$(id -u)" -ne 0 ]; then
	echo "Must run as root (sudo bash $0)." >&2
	exit 1
fi

SWAPFILE=/swapfile
ROOT_DEV="$(findmnt -no SOURCE /)"
RAM_KIB=$(awk '/MemTotal/{print $2}' /proc/meminfo)
# RAM rounded up to the next whole GiB, plus 2G headroom.
SIZE_GIB=$(( (RAM_KIB + 1024*1024 - 1) / (1024*1024) + 2 ))

echo "--- root device: $ROOT_DEV, target swapfile size: ${SIZE_GIB}G ---"

if [[ -e "$SWAPFILE" ]]; then
	echo "$SWAPFILE already exists, skipping creation (re-run assumed)."
else
	avail_kib=$(df --output=avail -k / | tail -1 | tr -d ' ')
	need_kib=$(( (SIZE_GIB + 1) * 1024 * 1024 ))
	if (( avail_kib < need_kib )); then
		echo "ABORT: not enough free space on / ($avail_kib KiB avail, need $need_kib KiB)." >&2
		exit 1
	fi

	echo "--- allocating ${SIZE_GIB}G swapfile ---"
	fallocate --length "${SIZE_GIB}GiB" "$SWAPFILE"
	chmod 600 "$SWAPFILE"
	mkswap "$SWAPFILE"
	swapon "$SWAPFILE"
fi
swapon --show

if ! grep -q "^$SWAPFILE " /etc/fstab; then
	echo "$SWAPFILE none swap sw 0 0" >> /etc/fstab
fi

echo "--- deriving physical offset ---"
row=$(filefrag -v "$SWAPFILE" | awk '$1=="0:"')
echo "row: $row"
offset=$(echo "$row" | grep -oP '\d+(?=\.\.)' | sed -n '2p')

if ! [[ "$offset" =~ ^[0-9]+$ ]]; then
	echo "ABORT: could not determine a numeric physical offset (got '$offset')." >&2
	exit 1
fi
echo "physical offset (pages): $offset"

echo "--- updating /etc/initramfs-tools/conf.d/resume ---"
# RESUME=none, not our root device: initramfs-tools' hooks/resume script
# only uses this (uppercase) conf.d value for its own legacy auto-detect
# path, which requires RESUME to itself be blkid TYPE=swap -- our root LV
# never is, so pointing it there just produces a spurious "no matching
# swap device" warning and an unused zz-resume-auto override. The resume
# that actually happens is scripts/local-premount/resume, which uses the
# lowercase resume=/resume_offset= kernel cmdline params set below --
# confirmed working end to end on 2026-09-28.
# Backup goes in $DIR, not conf.d itself: mkinitramfs globs and sources
# *every* file under conf.d (confirmed in /usr/sbin/mkinitramfs), so a
# stray resume.bak-* left in there gets sourced too -- alphabetically
# after "resume", silently overwriting RESUME=none back to a stale value.
# Cost a real debugging round-trip on 2026-09-28.
[[ -f /etc/initramfs-tools/conf.d/resume ]] && cp /etc/initramfs-tools/conf.d/resume "$DIR/resume.conf.bak-$(date +%s)"
echo "RESUME=none" > /etc/initramfs-tools/conf.d/resume

echo "--- updating /etc/default/grub ---"
cp /etc/default/grub "/etc/default/grub.bak-$(date +%s)"
# Strip any previous resume=/resume_offset= from an earlier run first, so
# re-running doesn't accumulate duplicates if the swapfile was recreated.
# [^" ]+, not \S+: resume_offset= is often the last token before the
# closing quote, and \S+ greedily eats the quote too since it's not
# whitespace -- corrupted GRUB_CMDLINE_LINUX_DEFAULT into an unterminated
# string this way on 2026-09-28 (update-grub then fails outright).
sed -i -E 's/ ?resume=[^" ]+//; s/ ?resume_offset=[^" ]+//' /etc/default/grub
sed -i -E "s#^GRUB_CMDLINE_LINUX_DEFAULT=\"(.*)\"#GRUB_CMDLINE_LINUX_DEFAULT=\"\1 resume=$ROOT_DEV resume_offset=$offset\"#" /etc/default/grub
grep GRUB_CMDLINE_LINUX_DEFAULT /etc/default/grub

echo "--- persisting hibernate mode (shutdown, not platform -- see header) ---"
install -d /etc/tmpfiles.d
cat > /etc/tmpfiles.d/cyberbeest-hibernate-mode.conf <<'EOF'
# Written by experimental/enable-hibernation.sh. /sys/power/disk resets to
# the firmware-preferred mode ("platform") on every boot; force "shutdown"
# instead -- see enable-hibernation.sh header for why.
w /sys/power/disk - - - - shutdown
EOF

echo "--- unmasking hibernate.target + sleep.target only ---"
systemctl unmask hibernate.target sleep.target
systemctl list-unit-files --state=masked | grep -iE "sleep|suspend|hibernate" || true

echo "--- update-initramfs ---"
update-initramfs -u -k all

echo "--- update-grub ---"
update-grub

echo "=== $(date) : done. Reboot required before hibernate will actually work. ==="
