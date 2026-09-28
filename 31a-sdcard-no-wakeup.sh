#!/bin/bash
# Disables system wakeup from the SD/MMC card reader's card-detect GPIO.
# Discovered while prototyping hibernation (see experimental/): an empty
# or floating card slot fires the card-detect IRQ, which the kernel reads
# as "something wants to wake the machine" during hibernate's brief
# internal hardware wake to write the image to disk -- aborting the
# poweroff right after the image is fully written (screen blanks, then
# the lock screen just comes back instead of the machine powering off).
#
# Safe regardless of whether hibernation ships: power/wakeup only gates
# system-level wake (ACPI PME# from a sleep state), not the card-detect
# IRQ used for normal hot-plug detection while the machine is awake --
# inserting/removing a card during normal use is unaffected. Installed
# unconditionally, unlike the hibernation infrastructure itself (see
# experimental/enable-hibernation.sh), because it has no downside and
# no per-machine disk cost.
#
# Matched by PCI vendor:device (8086:5aca, Intel N3350/N4200/E3900
# SDXC/MMC Host Controller) via udev rule, applied on every boot -- see
# lib/99-cyberbeest-sdcard-no-wakeup.rules.
# Depends on: none.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/31a-sdcard-no-wakeup.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : disabling SD card reader system wakeup ==="

echo "--- Installing udev rule ---"
install -m 644 "$DIR/lib/99-cyberbeest-sdcard-no-wakeup.rules" /etc/udev/rules.d/99-cyberbeest-sdcard-no-wakeup.rules

echo "--- Reloading udev rules and re-triggering on the device ---"
udevadm control --reload-rules
udevadm trigger --subsystem-match=pci --attr-match=vendor=0x8086 --attr-match=device=0x5aca

echo "--- Current state ---"
for dev in /sys/bus/pci/devices/*/; do
	if [[ "$(cat "$dev/vendor" 2>/dev/null)" == "0x8086" && "$(cat "$dev/device" 2>/dev/null)" == "0x5aca" ]]; then
		echo "$dev: $(cat "$dev/power/wakeup")"
	fi
done

echo "=== $(date) : done ==="
