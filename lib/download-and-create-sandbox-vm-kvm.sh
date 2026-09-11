#!/bin/bash
# Downloads the Cyberbeest sandbox-VM donor disk image and registers it as
# a libvirt/QEMU-KVM domain, so the user can run untrusted apps in a
# same-OS guest for extra isolation -- the QEMU/KVM + GNOME Boxes
# equivalent of lib/download-and-create-sandbox-vm.sh (VirtualBox).
#
# Runs under the unprivileged qemu:///session connection (no root daemon
# per VM -- see memory: cyberbeest_vbox_to_kvm_boxes_migration for why).
# Firmware/video match what the donor image actually needs: OVMF/UEFI (the
# donor was captured from an EFI-firmware VM -- importing under legacy
# BIOS hangs forever at "Booting from Hard Disk..." with no error) and
# QXL (GNOME Boxes' resize protocol only works with QXL, not virtio-vga).
#
# Also installs the host-side helper scripts (start/watcher/title-fix --
# see their own headers for what each does) and a Whisker menu launcher,
# so starting the VM and closing its window both behave like a normal app.
#
# Usage: download-and-create-sandbox-vm-kvm.sh [display-name]
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

IMAGE_URL="https://cyberbeest.com/vm-images/cyberbeest-donor.qcow2.gz"
DISPLAY_NAME="${1:-Cyberbeest VM}"
# libvirt domain names can't contain spaces (virt-install rejects them
# outright: "Guest name '...' can not contain ' ' character") -- sanitize
# separately from the human-readable name used in notifications/the menu
# entry, rather than making the friendly name itself space-free.
VM_NAME="${DISPLAY_NAME// /-}"
CONNECT="qemu:///session"
VM_DIR="$HOME/.local/share/cyberbeest-vms"
# Cached separately from the per-VM disk so a later failure (e.g.
# virt-install rejecting the name, as happened once already) doesn't cost
# a re-download of several GB just to retry that step -- only the
# extracted, VM-specific disk is cleaned up on failure, never this cache.
CACHE_PATH="$VM_DIR/cyberbeest-donor.qcow2.gz"
DISK_PATH="$VM_DIR/$VM_NAME.qcow2"
SHARED_DIR="$HOME/VM-Shared"

if virsh --connect "$CONNECT" list --all --name 2>/dev/null | grep -qxF "$VM_NAME"; then
	echo "A VM named \"$VM_NAME\" already exists -- assuming a prior run already set it up, skipping."
	echo "(To rebuild it from scratch: remove it in GNOME Boxes first, then re-run this.)"
	exit 0
fi

mkdir -p "$VM_DIR" "$SHARED_DIR"

cleanup_on_failure() {
	echo "--- Failed -- removing the partially-created VM and disk (keeping the cached download at $CACHE_PATH) ---" >&2
	rm -f "$DISK_PATH"
	virsh --connect "$CONNECT" undefine "$VM_NAME" --nvram 2>/dev/null || true
}
trap cleanup_on_failure ERR

REMOTE_HEADERS="$(curl -fsSI "$IMAGE_URL" | tr -d '\r')"
IMAGE_SIZE="$(printf '%s\n' "$REMOTE_HEADERS" | sed -n 's/^[Cc]ontent-[Ll]ength: *//Ip' | tail -1)"
# Identifies which server-side version of the image a cached/partial
# download actually is, so a resume can't silently splice bytes from two
# different versions together if the donor image gets updated between
# runs. ETag is the normal way to do this; Last-Modified is a fallback for
# a server that doesn't send one. If neither is present, IMAGE_VERSION is
# empty and every run just re-downloads from scratch (see below).
IMAGE_VERSION="$(printf '%s\n' "$REMOTE_HEADERS" | sed -n 's/^[Ee][Tt]ag: *//p' | tail -1)"
[ -n "$IMAGE_VERSION" ] || IMAGE_VERSION="$(printf '%s\n' "$REMOTE_HEADERS" | sed -n 's/^[Ll]ast-[Mm]odified: *//Ip' | tail -1)"
VERSION_FILE="$CACHE_PATH.version"

if [ -n "$IMAGE_SIZE" ] && [ "$(stat -c%s "$CACHE_PATH" 2>/dev/null)" = "$IMAGE_SIZE" ] \
	&& [ -n "$IMAGE_VERSION" ] && [ "$(cat "$VERSION_FILE" 2>/dev/null)" = "$IMAGE_VERSION" ]; then
	echo "--- Reusing cached download at $CACHE_PATH (already complete, same version) ---"
else
	# A .part left over from an interrupted download (e.g. a crash/reboot
	# mid-transfer) can only be resumed if it's bytes of the SAME
	# server-side version -- otherwise `curl -C -` would happily append
	# new-version bytes onto the tail of an old-version prefix, producing
	# a corrupt file that just happens to be the right size. Compare
	# against the version recorded next to the .part when IT was started;
	# discard and restart from scratch on any mismatch (including the
	# "no version info available" case, to be safe).
	if [ -f "$CACHE_PATH.part" ]; then
		if [ -z "$IMAGE_VERSION" ] || [ "$(cat "$VERSION_FILE.part" 2>/dev/null)" != "$IMAGE_VERSION" ]; then
			echo "--- Remote image version changed (or unknown) since the last partial download -- discarding it and starting over ---"
			rm -f "$CACHE_PATH.part"
		fi
	fi
	[ -n "$IMAGE_VERSION" ] && printf '%s' "$IMAGE_VERSION" > "$VERSION_FILE.part"

	echo "--- Downloading $IMAGE_URL to $CACHE_PATH (several GB, this takes a while) ---"
	# curl -C - resumes from $CACHE_PATH.part's current size via an HTTP
	# Range request (a no-op, starting from byte 0, the first time). Can't
	# pipe through pv here the way experimental/download-and-create-sandbox-vm.sh
	# does (comment there explains why not curl's own \r-based bar) since
	# -C - needs to write directly to a seekable file, not a pipe -- so
	# progress is a periodic size poll instead, printed every 10s to match
	# pv's non-spammy cadence in run-gui.py's log widget.
	curl -fsSL -C - "$IMAGE_URL" -o "$CACHE_PATH.part" &
	CURL_PID=$!
	while kill -0 "$CURL_PID" 2>/dev/null; do
		sleep 10
		CUR_SIZE="$(stat -c%s "$CACHE_PATH.part" 2>/dev/null || echo 0)"
		if [ -n "$IMAGE_SIZE" ] && [ "$IMAGE_SIZE" -gt 0 ]; then
			echo "--- Downloaded $CUR_SIZE / $IMAGE_SIZE bytes ($(( CUR_SIZE * 100 / IMAGE_SIZE ))%) ---"
		else
			echo "--- Downloaded $CUR_SIZE bytes ---"
		fi
	done
	wait "$CURL_PID"

	mv "$CACHE_PATH.part" "$CACHE_PATH"
	[ -n "$IMAGE_VERSION" ] && printf '%s' "$IMAGE_VERSION" > "$VERSION_FILE"
	rm -f "$VERSION_FILE.part"
fi
echo "--- Download complete ---"

echo "--- Extracting to $DISK_PATH ---"
gunzip -c "$CACHE_PATH" > "$DISK_PATH"

echo "--- Matching guest locale/keyboard to the host ---"
bash "$DIR/set-vm-guest-locale.sh" "$DISK_PATH"

echo "--- Registering the VM ---"
virt-install \
	--connect "$CONNECT" \
	--name "$VM_NAME" \
	--memory 2048 \
	--vcpus 2 \
	--disk path="$DISK_PATH",format=qcow2,bus=virtio \
	--import \
	--os-variant debian13 \
	--boot uefi \
	--graphics spice \
	--video model=qxl,vram=65536 \
	--channel spicevmc \
	--channel unix,target.type=virtio,target.name=org.qemu.guest_agent.0 \
	--filesystem driver.type=virtiofs,source.dir="$SHARED_DIR",target.dir=shared \
	--memorybacking access.mode=shared \
	--noautoconsole

echo "--- Installing the start/watcher/title-fix helper scripts ---"
mkdir -p "$HOME/.local/bin"
install -m 755 "$DIR/cyberbeest-vm-start.sh" "$HOME/.local/bin/cyberbeest-vm-start.sh"
install -m 755 "$DIR/cyberbeest-vm-watcher.sh" "$HOME/.local/bin/cyberbeest-vm-watcher.sh"
install -m 755 "$DIR/cyberbeest-vm-title-fix.sh" "$HOME/.local/bin/cyberbeest-vm-title-fix.sh"

echo "--- Adding the Whisker menu launcher ---"
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/cyberbeest-sandbox-vm.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$DISPLAY_NAME
Comment=Run untrusted apps in an isolated same-OS virtual machine
Exec=$HOME/.local/bin/cyberbeest-vm-start.sh "$VM_NAME" "$DISPLAY_NAME"
Icon=computer
Categories=System;
Terminal=false
EOF

trap - ERR
echo "--- Done: \"$DISPLAY_NAME\" created at $DISK_PATH ---"
echo "Start it from the Whisker menu, or: $HOME/.local/bin/cyberbeest-vm-start.sh"
