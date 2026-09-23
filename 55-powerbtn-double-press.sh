#!/bin/bash
# Makes a second power-button press, within a few seconds of the first
# (which pops up xfce4-power-manager's own "Ask" dialog), force an
# immediate real shutdown -- bypassing that dialog. Handy when the dialog
# is stuck behind other windows, and takes any running VMs down along
# with the rest of the session instead of leaving them parked. See
# lib/cyberbeest-powerbtn-double-press.sh.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/55-powerbtn-double-press.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing power-button double-press shutdown ==="

echo "--- Installing action script to /usr/local/bin/cyberbeest-powerbtn-double-press.sh ---"
install -o root -g root -m 755 \
	"$DIR/lib/cyberbeest-powerbtn-double-press.sh" \
	/usr/local/bin/cyberbeest-powerbtn-double-press.sh

echo "--- Installing acpid event rule ---"
install -o root -g root -m 644 \
	"$DIR/lib/cyberbeest-powerbtn-double.acpi" \
	/etc/acpi/events/cyberbeest-powerbtn-double

echo "--- Reloading acpid ---"
systemctl restart acpid

echo "=== $(date) : done ==="
