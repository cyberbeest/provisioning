#!/bin/bash
# Downloads the Cyberbeest sandbox-VM donor disk image and creates a
# VirtualBox VM from it on the host, so the user can run untrusted apps in
# a same-OS guest for extra isolation. Matches the donor image's own
# hardware settings (EFI firmware, VMSVGA graphics, SATA controller --
# see the "Fresh VM"/"Cyberbeest Donor Image" template this was captured
# from) so the shipped install boots correctly, then applies
# set-vm-guest-locale.sh so the guest's language/keyboard match the host's
# before its first boot.
#
# Whether this runs automatically during provisioning or only on-demand
# (e.g. from a Whisker menu item) is not yet decided -- this script is
# just the mechanism, callable either way.
#
# Usage: download-and-create-sandbox-vm.sh [vm-name]
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

IMAGE_URL="https://cyberbeest.com/vm-images/cyberbeest-donor.vdi.gz"
VM_NAME="${1:-Cyberbeest Sandbox}"

if VBoxManage list vms 2>/dev/null | grep -qF "\"$VM_NAME\""; then
	echo "A VM named \"$VM_NAME\" already exists -- pick a different name or remove it first." >&2
	exit 1
fi

echo "--- Registering the VM (so VirtualBox picks its own machine folder) ---"
VBoxManage createvm --name "$VM_NAME" --ostype Debian_64 --register
VM_CFG="$(VBoxManage showvminfo "$VM_NAME" --machinereadable | sed -n 's/^CfgFile=\"\(.*\)\"$/\1/p')"
VM_DIR="$(dirname "$VM_CFG")"
DISK_PATH="$VM_DIR/$VM_NAME.vdi"

cleanup_on_failure() {
	echo "--- Failed -- removing the partially-created VM and disk ---" >&2
	rm -f "$DISK_PATH"
	VBoxManage unregistervm "$VM_NAME" --delete 2>/dev/null || true
}
trap cleanup_on_failure ERR

echo "--- Downloading $IMAGE_URL ---"
curl -fL --progress-bar "$IMAGE_URL" | gunzip > "$DISK_PATH"

echo "--- Matching guest locale/keyboard to the host ---"
bash "$DIR/set-vm-guest-locale.sh" "$DISK_PATH"

echo "--- Configuring hardware ---"
VBoxManage modifyvm "$VM_NAME" --memory 2048 --cpus 2 --firmware efi \
	--graphicscontroller vmsvga --vram 32 --nic1 nat
VBoxManage storagectl "$VM_NAME" --name SATA --add sata --controller IntelAhci
VBoxManage storagectl "$VM_NAME" --name SATA --hostiocache off
VBoxManage storageattach "$VM_NAME" --storagectl SATA --port 0 --device 0 \
	--type hdd --medium "$DISK_PATH"

trap - ERR
echo "--- Done: \"$VM_NAME\" created at $VM_DIR ---"
echo "Start it with: VBoxManage startvm \"$VM_NAME\""
