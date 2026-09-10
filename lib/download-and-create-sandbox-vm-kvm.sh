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
DISPLAY_NAME="${1:-Cyberbeest Sandbox}"
# libvirt domain names can't contain spaces (virt-install rejects them
# outright: "Guest name '...' can not contain ' ' character") -- sanitize
# separately from the human-readable name used in notifications/the menu
# entry, rather than making the friendly name itself space-free.
VM_NAME="${DISPLAY_NAME// /-}"
CONNECT="qemu:///session"
VM_DIR="$HOME/.local/share/cyberbeest-vms"
DISK_PATH="$VM_DIR/$VM_NAME.qcow2"
SHARED_DIR="$HOME/Cyberbeest-Sandbox-Shared"

if virsh --connect "$CONNECT" list --all --name 2>/dev/null | grep -qxF "$VM_NAME"; then
	echo "A VM named \"$VM_NAME\" already exists -- assuming a prior run already set it up, skipping."
	echo "(To rebuild it from scratch: remove it in GNOME Boxes first, then re-run this.)"
	exit 0
fi

mkdir -p "$VM_DIR" "$SHARED_DIR"

cleanup_on_failure() {
	echo "--- Failed -- removing the partially-created VM and disk ---" >&2
	rm -f "$DISK_PATH"
	virsh --connect "$CONNECT" undefine "$VM_NAME" --nvram 2>/dev/null || true
}
trap cleanup_on_failure ERR

echo "--- Downloading $IMAGE_URL (several GB, this takes a while) ---"
# See lib/download-and-create-sandbox-vm.sh's own comment for why pv (-i 10,
# -f) rather than curl's own \r-based progress bar: piped into run-gui.py's
# log widget, \r becomes spammy separate lines; pv's periodic real newlines
# don't.
IMAGE_SIZE="$(curl -fsSI "$IMAGE_URL" | tr -d '\r' | sed -n 's/^[Cc]ontent-[Ll]ength: *//Ip' | tail -1)"
curl -fsSL "$IMAGE_URL" | pv -f -i 10 ${IMAGE_SIZE:+-s "$IMAGE_SIZE"} | gunzip > "$DISK_PATH"
echo "--- Download complete ---"

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
