#!/bin/bash
# Makes a second power-button press, within a few seconds of the first
# (which pops up xfce4-power-manager's own "Ask" dialog), force an
# immediate real shutdown -- bypassing that dialog. Handy when the dialog
# is stuck behind other windows, and takes any running VMs down along
# with the rest of the session instead of leaving them parked. See
# lib/cyberbeest-powerbtn-double-press.sh.
# Installs acpid itself -- not part of a stock Debian Xfce install (it was
# only present on the dev machine, via acpi-support-base, which is why the
# first version of this script assumed it). Just acpid, not
# acpi-support-base (a Recommends of acpid, hence --no-install-recommends):
# that one adds its own powerbtn-acpi-support rule,
# which shuts down on the first press whenever it doesn't spot a running
# power manager.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/55-powerbtn-double-press.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing power-button double-press shutdown ==="

echo "--- Installing acpid ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y --no-install-recommends acpid

echo "--- Installing action script to /usr/local/bin/cyberbeest-powerbtn-double-press.sh ---"
install -o root -g root -m 755 \
	"$DIR/lib/cyberbeest-powerbtn-double-press.sh" \
	/usr/local/bin/cyberbeest-powerbtn-double-press.sh

echo "--- Installing acpid event rule ---"
install -d -o root -g root -m 755 /etc/acpi/events
install -o root -g root -m 644 \
	"$DIR/lib/cyberbeest-powerbtn-double.acpi" \
	/etc/acpi/events/cyberbeest-powerbtn-double

echo "--- Reloading acpid ---"
systemctl enable acpid.service
systemctl restart acpid.service

echo "=== $(date) : done ==="
