#!/bin/bash
# Boot-stick malware scan: runs as root from the Cyberbeest live image
# (booted with "cyberbeest-scan" on the kernel command line), unlocks the
# machine's internal encrypted disk, mounts it READ-ONLY and scans it from
# outside, so nothing on the target executes and a rootkit can't lie to the
# scanner. Never writes to the target.
#
# Called by cyberbeest_scanner_gui.py --stick (via sudo). Modes:
#   cyberbeest-stick-scan.sh --list
#       Prints one "<device>\t<size>\t<model>" line per internal LUKS
#       partition (the disk the stick booted from is excluded).
#   cyberbeest-stick-scan.sh --scan <device>
#       The passphrase is read from stdin (first line, as typed), so it never
#       appears in a process list. Same stdout protocol as
#       cyberbeest-scanner-helper.sh (@@STAGE@@, @@CLAMTOTAL@@,
#       @@CLAMPROGRESS@@, @@ALERT@@, @@DONE@@, @@INTERRUPTED@@), plus
#       @@ERROR@@ <message> for failures the GUI should show verbatim
#       (wrong password, no usable filesystem, ...).
#
# Not covered here, on purpose: rkhunter/chkrootkit inspect a RUNNING system
# (hidden processes, loaded modules, sockets); a disk that is not booted has
# none of that. Package checksums come from the target's own dpkg database,
# so a rootkit that also rewrote those md5sums files could hide a change from
# debsums -- ClamAV and the tiering still apply.
set -uo pipefail

LIBDIR="${CB_LIBDIR:-/usr/local/lib/cyberbeest}"
PRIORITY_PY="$LIBDIR/scan_priority.py"
REPORT_DIR="/run/cyberbeest-scan/reports"
CANCEL_FILE="/run/cyberbeest-scan/cancel"
MAPPER_NAME="cbscan_crypt"
# Not under /run: clamd's ExcludePath (and the stock config) skips ^/run/.
MNT="/mnt/cyberbeest-scan"
EXCLUDE_RE='(/\.cache/)|(^/var/cache/)|(\.(qcow2|vdi|vmdk|iso|img)$)|(^/(proc|sys|dev|run)/)'

# The disk the live medium sits on: never offer it as a target. /run/live/medium
# is where live-boot mounts the boot stick.
boot_disk() {
	local src
	src="$(findmnt -n -o SOURCE /run/live/medium 2>/dev/null || true)"
	[ -n "$src" ] || return 0
	lsblk -no PKNAME "$src" 2>/dev/null | head -n1
}

list_targets() {
	local skip
	skip="$(boot_disk)"
	lsblk -rpno PATH,FSTYPE,SIZE,MODEL,PKNAME | while read -r path fstype size model pk; do
		[ "$fstype" = crypto_LUKS ] || continue
		[ -n "$skip" ] && [ "$(basename "$pk")" = "$skip" ] && continue
		printf '%s\t%s\t%s\n' "$path" "$size" "${model:-disk}"
	done
}

if [ "${1:-}" = "--list" ]; then
	list_targets
	exit 0
fi
if [ "${1:-}" != "--scan" ] || [ -z "${2:-}" ]; then
	echo "usage: $0 --list | --scan <luks-device>" >&2
	exit 2
fi
DEVICE="$2"
[ "$(id -u)" -eq 0 ] || { echo "@@ERROR@@ must run as root"; exit 1; }

IFS= read -r TYPED_PASSPHRASE || TYPED_PASSPHRASE=""

mkdir -p "$REPORT_DIR" "$MNT"
rm -f "$CANCEL_FILE"
STAMP="$(date +%Y%m%d-%H%M%S)"
REPORT="$REPORT_DIR/scan-$STAMP.log"
FINISHED=0
CLAMD_STARTED=0

section() {
	echo "===$1===" >> "$REPORT"
	echo "=== $2 ===" | tee -a "$REPORT"
}

cleanup() {
	pkill -TERM -P $$ 2>/dev/null || true
	sleep 1
	pkill -KILL -P $$ 2>/dev/null || true
	[ "$CLAMD_STARTED" = 1 ] && systemctl stop clamav-daemon 2>/dev/null
	CLAMD_STARTED=0
	umount -R "$MNT/root" 2>/dev/null || umount -R -l "$MNT/root" 2>/dev/null || true
	for vg in $(pvs --noheadings -o vg_name "/dev/mapper/$MAPPER_NAME" 2>/dev/null); do
		vgchange -an "$vg" >/dev/null 2>&1 || true
	done
	cryptsetup close "$MAPPER_NAME" 2>/dev/null || true
	if [ "$FINISHED" != 1 ]; then
		echo "@@INTERRUPTED@@"
	fi
}
trap cleanup EXIT
trap 'cleanup; exit 143' INT TERM

# Cancel button: the GUI drops a file, we stop (same path as a signal).
(
	while [ ! -e "$CANCEL_FILE" ]; do sleep 1; done
	kill -TERM $$ 2>/dev/null
) &

fail() {
	echo "@@ERROR@@ $1"
	FINISHED=1   # a handled failure, not an interruption
	exit 1
}

# ---- 1. Unlock ------------------------------------------------------------
echo "@@STAGE@@ 1 4 unlock"
section unlock "Unlocking the internal disk (read-only)"

# The machine's own boot prompt runs the typed text through this filter
# before cryptsetup sees it (words, case, separators, umlauts), so the keyslot
# holds the normalized form. Same function, same result; the raw text is the
# fallback for disks that never used the filter.
FILTER=/lib/cryptsetup/cyberbeest-passphrase-filter
NORMALIZED=""
if [ -r "$FILTER" ]; then
	# shellcheck disable=SC1090
	. "$FILTER"
	NORMALIZED="$(printf '%s' "$TYPED_PASSPHRASE" | cyberbeest_normalize_passphrase)"
fi

opened=0
for candidate in "$NORMALIZED" "$TYPED_PASSPHRASE"; do
	[ -n "$candidate" ] || continue
	if printf '%s' "$candidate" | cryptsetup open --readonly --type luks \
		--key-file=- "$DEVICE" "$MAPPER_NAME" >/dev/null 2>&1; then
		opened=1
		break
	fi
done
unset TYPED_PASSPHRASE NORMALIZED candidate
[ "$opened" = 1 ] || fail "That password did not unlock the disk."

vgscan --mknodes >/dev/null 2>&1
vgchange -ay >/dev/null 2>&1 || true
udevadm settle 2>/dev/null || true

# ---- 2. Find and mount the root filesystem (and /boot, ESP) ---------------
echo "@@STAGE@@ 2 4 mount"
section mount "Mounting the disk read-only"

ROOT_MNT="$MNT/root"
mkdir -p "$ROOT_MNT"
mounted_root=0
while read -r dev fstype; do
	case "$fstype" in ext2|ext3|ext4|btrfs|xfs) ;; *) continue ;; esac
	case "$fstype" in
		ext*) opts="ro,noload,nodev,nosuid,noexec" ;;
		xfs) opts="ro,norecovery,nodev,nosuid,noexec" ;;
		*) opts="ro,nodev,nosuid,noexec" ;;
	esac
	if mount -o "$opts" "$dev" "$ROOT_MNT" 2>/dev/null; then
		if [ -e "$ROOT_MNT/etc/os-release" ] && [ -d "$ROOT_MNT/usr" ]; then
			mounted_root=1
			echo "root filesystem: $dev ($fstype)" | tee -a "$REPORT"
			break
		fi
		umount "$ROOT_MNT"
	fi
done < <(lsblk -rpno PATH,FSTYPE "/dev/mapper/$MAPPER_NAME" 2>/dev/null)
[ "$mounted_root" = 1 ] || fail "Unlocked the disk but found no Linux system on it."

# /boot and the EFI partition live outside the encrypted volume, on the same
# physical disk. Tampered kernels/initrds are a classic persistence spot, so
# they are part of the scan.
PARENT="$(lsblk -no PKNAME "$DEVICE" | head -n1)"
if [ -n "$PARENT" ]; then
	while read -r part fstype ptype; do
		[ "$ptype" = part ] || continue
		[ "$part" = "$DEVICE" ] && continue
		case "$fstype" in
			ext2|ext3|ext4)
				mkdir -p "$ROOT_MNT/boot"
				mountpoint -q "$ROOT_MNT/boot" || mount -o ro,noload,nodev,nosuid,noexec "$part" "$ROOT_MNT/boot" 2>/dev/null \
					&& echo "boot partition: $part" | tee -a "$REPORT"
				;;
		esac
	done < <(lsblk -rpno PATH,FSTYPE,TYPE "/dev/$PARENT")
	while read -r part fstype ptype; do
		if [ "$ptype" = part ] && [ "$fstype" = vfat ]; then
			mkdir -p "$ROOT_MNT/boot/efi"
			mountpoint -q "$ROOT_MNT/boot/efi" || mount -o ro,nodev,nosuid,noexec "$part" "$ROOT_MNT/boot/efi" 2>/dev/null \
				&& echo "EFI partition: $part" | tee -a "$REPORT"
		fi
	done < <(lsblk -rpno PATH,FSTYPE,TYPE "/dev/$PARENT")
fi

# ---- 3. debsums ------------------------------------------------------------
echo "@@STAGE@@ 3 4 debsums"
section debsums "Checking base-system files (debsums)"
debsums --root="$ROOT_MNT" -c 2>&1 | tee -a "$REPORT"

# ---- 4. ClamAV, sensitive places first ------------------------------------
echo "@@STAGE@@ 4 4 clamscan"
section clamscan "Scanning for known malware (ClamAV)"

# Signatures baked into the image can be old by the time the stick is used;
# refresh if the network happens to be up. Failing is fine.
timeout 60 freshclam --quiet 2>&1 | tail -n 2 | tee -a "$REPORT" || true

systemctl start clamav-daemon
CLAMD_STARTED=1
for _ in $(seq 1 60); do
	[ -S /var/run/clamav/clamd.ctl ] && break
	sleep 1
done

FILE_LIST="$(mktemp)"
echo "building the file list (sensitive locations first)..." | tee -a "$REPORT"
python3 "$PRIORITY_PY" walk "$ROOT_MNT" "$EXCLUDE_RE" > "$FILE_LIST"
TOTAL="$(wc -l < "$FILE_LIST")"
echo "@@CLAMTOTAL@@ $TOTAL"

{
nworkers="$(nproc)"
chunkdir="$(mktemp -d)"
# Round-robin, not contiguous: every worker walks the tiers in order.
split -n "r/$nworkers" -d -a3 "$FILE_LIST" "$chunkdir/chunk_"
counter_file="$(mktemp)"; echo 0 > "$counter_file"
counter_lock="$(mktemp)"
pids=()
for chunk in "$chunkdir"/chunk_*; do
	[ -s "$chunk" ] || continue
	(
		stdbuf -oL clamdscan -v --fdpass --file-list="$chunk" 2>&1 | while IFS= read -r line; do
			case "$line" in
				*": OK"|*FOUND)
					n="$(flock "$counter_lock" bash -c '
						read -r c < "'"$counter_file"'"; c=$((c+1))
						echo "$c" > "'"$counter_file"'"; echo "$c"')"
					case "$line" in
						*FOUND)
							echo "$line"
							echo "@@ALERT@@ $line"
							echo "@@CLAMPROGRESS@@ $n" ;;
						*)
							[ $((n % 25)) -eq 0 ] || [ "$n" -eq "$TOTAL" ] && echo "@@CLAMPROGRESS@@ $n" ;;
					esac ;;
				*) echo "$line" ;;
			esac
		done
	) &
	pids+=("$!")
done
wait "${pids[@]}" 2>/dev/null
rm -rf "$chunkdir" "$counter_file" "$counter_lock"
} | tee -a "$REPORT"
rm -f "$FILE_LIST"

FINISHED=1
echo "@@DONE@@ $REPORT"
