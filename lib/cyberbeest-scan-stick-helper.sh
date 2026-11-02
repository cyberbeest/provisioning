#!/bin/bash
# Root half of the "scan from boot stick" offer (see
# cyberbeest-scan-stick-watch.sh). Run via pkexec with the stick's block
# device. Verifies it really is a Cyberbeest stick, then reboots. The computer
# starts the stick by itself because its firmware tries USB first; the stick's
# first (default, no-timeout) menu entry is the scan:
#
#   1. label is "Cyberbeest Combined", filesystem iso9660;
#   2. the signed manifest on the stick verifies against
#      /etc/cyberbeest/scan-allowed-signers (ssh-keygen -Y verify) -- if that
#      file is not installed yet, this is skipped with a warning;
#   3. the files the manifest names (scan.cfg, grub.cfg, kernel, initrd)
#      match their hashes;
#   4. reboot (nothing is written to NVRAM).
#
# CB_DRY_RUN=1 does everything except the reboot.
# Failures print "ERROR: <message>" (the watcher shows the last such line).
set -uo pipefail
DEV="${1:-}"
LABEL="Cyberbeest Combined"
ALLOWED=/etc/cyberbeest/scan-allowed-signers
# Test hook: dry runs may point at a throwaway key; real runs never do.
[ "${CB_DRY_RUN:-0}" = 1 ] && ALLOWED="${CB_ALLOWED_SIGNERS:-$ALLOWED}"

err() { echo "ERROR: $1"; exit 1; }

[ "$(id -u)" -eq 0 ] || err "must run as root"
[ -b "$DEV" ] || err "not a block device: $DEV"
[ "$(blkid -s LABEL -o value "$DEV" 2>/dev/null)" = "$LABEL" ] || err "this is not a Cyberbeest stick"
[ "$(blkid -s TYPE -o value "$DEV" 2>/dev/null)" = iso9660 ] || err "unexpected stick layout"
TMP="$(mktemp -d)"
cleanup() { umount "$TMP" 2>/dev/null; rmdir "$TMP" 2>/dev/null; }
trap cleanup EXIT
mount -t iso9660 -o ro,nodev,nosuid,noexec "$DEV" "$TMP" || err "could not read the stick"

[ -f "$TMP/cyberbeest-scan.manifest" ] && [ -f "$TMP/boot/grub/scan.cfg" ] || err "this stick has no scan mode (too old?)"

if [ -s "$ALLOWED" ]; then
	[ -f "$TMP/cyberbeest-scan.manifest.sig" ] || err "the stick's scan files are not signed"
	ssh-keygen -Y verify -f "$ALLOWED" -I cyberbeest-scan -n cyberbeest-scan \
		-s "$TMP/cyberbeest-scan.manifest.sig" < "$TMP/cyberbeest-scan.manifest" >/dev/null 2>&1 \
		|| err "the stick's signature is not valid -- do not use this stick"
else
	echo "WARN: no trusted signing key installed on this computer; stick not authenticated"
fi

(cd "$TMP" && sed 's|  /|  |' cyberbeest-scan.manifest | sha256sum -c --quiet - >/dev/null 2>&1) \
	|| err "the stick's files do not match its manifest -- do not use this stick"

if [ "${CB_DRY_RUN:-0}" = 1 ]; then
	echo "DRY RUN: stick verified, would run: systemctl reboot"
	exit 0
fi

cleanup
trap - EXIT
systemctl reboot
