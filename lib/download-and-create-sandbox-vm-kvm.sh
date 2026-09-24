#!/bin/bash
# Downloads the Cyberbeest sandbox-VM donor disk image and registers it as
# a libvirt/QEMU-KVM domain, so the user can run untrusted apps in a
# same-OS guest for extra isolation. KVM is the only hypervisor
# provisioning ships now -- the VirtualBox equivalent of this script was
# removed 2026-09-19, see memory: cyberbeest_vbox_to_kvm_boxes_migration.
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
# Versioning: the image is pinned by SHA-256 below. Publishing a new image
# means uploading it, then updating the three IMAGE_* values here -- that
# edit is also what makes 56-cyberbeest-sandbox-vm-kvm.sh pending again on
# every machine (run-gui.py tracks lib/ files a script references). A VM
# set up from an older image is detected via the hash stamped next to its
# disk. It is only replaced when the provisioning profile's "Update the VM"
# box was ticked (PROVISIONING_VM_UPDATE=yes, passed in as --update) --
# off by default, since it's a multi-GB download and a VM that suddenly
# looks different can confuse. Updating always keeps the old VM, registered
# as "<name>-backup" and visible in GNOME Boxes: users leave traces in it
# (messenger accounts, bookmarks). One backup only, a previous one is
# deleted. Nothing is touched until the new image is downloaded and
# verified, and ~/VM-Shared is never touched.
#
# Usage: download-and-create-sandbox-vm-kvm.sh [--update] [display-name]
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

IMAGE_URL="https://cyberbeest.com/vm-images/cyberbeest-donor.qcow2.gz"
# Parsed by run-gui.py (vm_update_status) too -- keep the plain KEY="value" form.
IMAGE_SHA256="3413d2ec88c52e2b9944db7ce79d2f65a9422349ff666bc99b32e70bff6270fc"
IMAGE_DOWNLOAD_BYTES="3093302109"
IMAGE_DISK_BYTES="3143303168"

UPDATE=0
if [ "${1:-}" = "--update" ]; then
	UPDATE=1
	shift
fi
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
# Which image a VM was built from, written after a successful setup.
# VMs set up before this existed have none and count as outdated.
STAMP_PATH="$VM_DIR/$VM_NAME.image-sha256"
BACKUP_NAME="$VM_NAME-backup"
BACKUP_DISK="$VM_DIR/$BACKUP_NAME.qcow2"
SHARED_DIR="$HOME/VM-Shared"

vm_exists() {
	virsh --connect "$CONNECT" list --all --name 2>/dev/null | grep -qxF "$1"
}

# Bytes actually allocated on disk (qcow2 files can be sparse), 0 if missing.
allocated() {
	if [ -e "$1" ]; then du -B1 "$1" | cut -f1; else echo 0; fi
}

# A finished download is recorded as verified in $CACHE_PATH.sha256; any
# other cached copy (an older image, or one from before pinning) can never
# be used again, so it goes whether or not anything else happens below.
if [ -f "$CACHE_PATH" ] && [ "$(cat "$CACHE_PATH.sha256" 2>/dev/null)" != "$IMAGE_SHA256" ]; then
	echo "--- Removing a cached download of an older image ---"
	rm -f "$CACHE_PATH" "$CACHE_PATH.sha256" "$CACHE_PATH.version"
fi

UPDATING=0
if vm_exists "$VM_NAME"; then
	if [ "$(cat "$STAMP_PATH" 2>/dev/null)" = "$IMAGE_SHA256" ]; then
		echo "\"$VM_NAME\" is already on the current image -- nothing to do."
		exit 0
	fi
	echo "\"$VM_NAME\" was set up from an older image; a new one is available."
	if [ "$UPDATE" -eq 0 ]; then
		echo "Not updating it (\"Update the VM\" is off in the provisioning profile) -- leaving it alone."
		echo "(To update: tick it in run-gui.py's Profile..., then re-run this script.)"
		exit 0
	fi
	STATE="$(virsh --connect "$CONNECT" domstate "$VM_NAME" 2>/dev/null || echo "shut off")"
	if [ "$STATE" != "shut off" ]; then
		echo "\"$VM_NAME\" is $STATE -- shut it down first, then re-run this script." >&2
		exit 1
	fi
	UPDATING=1
fi

mkdir -p "$VM_DIR" "$SHARED_DIR"

# Same arithmetic as run-gui.py's vm_update_status(), which shows these
# figures in the profile dialog. The margin keeps the laptop from being
# filled to the last byte. The old VM's disk stays (as the backup), so only
# the previous backup counts as reclaimable.
MARGIN_BYTES=$((1024 * 1024 * 1024))
FREE_BYTES="$(df -B1 --output=avail "$VM_DIR" | tail -1 | tr -d ' ')"
RECLAIMABLE=0
if [ "$UPDATING" -eq 1 ]; then
	RECLAIMABLE=$((RECLAIMABLE + $(allocated "$BACKUP_DISK")))
fi
NEEDED=$((IMAGE_DOWNLOAD_BYTES + IMAGE_DISK_BYTES + MARGIN_BYTES))
if [ $((FREE_BYTES + RECLAIMABLE)) -lt "$NEEDED" ]; then
	echo "Not enough disk space: need $((NEEDED / 1000000)) MB, only $(((FREE_BYTES + RECLAIMABLE) / 1000000)) MB available." >&2
	[ "$UPDATING" -eq 1 ] && echo "(The old VM is kept as a backup, so its disk still counts as used.)" >&2
	exit 1
fi

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

if [ -f "$CACHE_PATH" ]; then
	echo "--- Reusing cached download at $CACHE_PATH (already verified) ---"
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

	# The pin comes from the provisioning repo, not from the download
	# host, so a swapped file on the server can't get through. A mismatch
	# also covers a resumed .part that spliced two versions together.
	echo "--- Verifying the download's SHA-256 ---"
	ACTUAL_SHA256="$(sha256sum "$CACHE_PATH.part" | cut -d' ' -f1)"
	if [ "$ACTUAL_SHA256" != "$IMAGE_SHA256" ]; then
		rm -f "$CACHE_PATH.part" "$VERSION_FILE.part"
		echo "Checksum mismatch: expected $IMAGE_SHA256, got $ACTUAL_SHA256 -- discarded the download." >&2
		echo "(If a new image was just uploaded, provisioning's pinned hash may not be updated yet.)" >&2
		exit 1
	fi
	mv "$CACHE_PATH.part" "$CACHE_PATH"
	printf '%s' "$IMAGE_SHA256" > "$CACHE_PATH.sha256"
	rm -f "$VERSION_FILE.part"
fi
echo "--- Download complete ---"

if [ "$UPDATING" -eq 1 ]; then
	if vm_exists "$BACKUP_NAME"; then
		echo "--- Deleting the previous backup VM \"$BACKUP_NAME\" ---"
		virsh --connect "$CONNECT" undefine "$BACKUP_NAME" --nvram
	fi
	rm -f "$BACKUP_DISK"
	echo "--- Keeping the old VM as \"$BACKUP_NAME\" ---"
	mv "$DISK_PATH" "$BACKUP_DISK"
	virsh --connect "$CONNECT" domrename "$VM_NAME" "$BACKUP_NAME"
	virt-xml --connect "$CONNECT" "$BACKUP_NAME" --edit --disk path="$BACKUP_DISK"
	# domrename leaves the UEFI vars file at its old-name path, which the
	# new VM is about to be given too -- sharing it would also make a later
	# `undefine --nvram` of this backup delete the new VM's vars.
	OLD_NVRAM="$(virsh --connect "$CONNECT" dumpxml "$BACKUP_NAME" | sed -n 's|.*<nvram[^>]*>\(.*\)</nvram>.*|\1|p')"
	if [ -n "$OLD_NVRAM" ]; then
		BACKUP_NVRAM="$(dirname "$OLD_NVRAM")/${BACKUP_NAME}_VARS.fd"
		[ -f "$OLD_NVRAM" ] && mv "$OLD_NVRAM" "$BACKUP_NVRAM"
		virt-xml --connect "$CONNECT" "$BACKUP_NAME" --edit --boot nvram="$BACKUP_NVRAM"
	fi
	# GNOME Boxes lists a domain by its title when it has one.
	virsh --connect "$CONNECT" desc "$BACKUP_NAME" --config --title \
		"$DISPLAY_NAME (backup $(date +%Y-%m-%d))"
	rm -f "$STAMP_PATH"
fi

# Only armed now: before this point "$VM_NAME" may still be the user's old
# VM, which a failed download must never undefine.
cleanup_on_failure() {
	echo "--- Failed -- removing the partially-created VM and disk (keeping the cached download at $CACHE_PATH) ---" >&2
	rm -f "$DISK_PATH"
	virsh --connect "$CONNECT" undefine "$VM_NAME" --nvram 2>/dev/null || true
}
trap cleanup_on_failure ERR

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
printf '%s' "$IMAGE_SHA256" > "$STAMP_PATH"
# Several GB that nothing needs once the VM exists -- and would otherwise
# end up inside release images built from a provisioned machine.
rm -f "$CACHE_PATH" "$CACHE_PATH.sha256" "$VERSION_FILE"
echo "--- Done: \"$DISPLAY_NAME\" created at $DISK_PATH ---"
echo "Start it from the Whisker menu, or: $HOME/.local/bin/cyberbeest-vm-start.sh"
