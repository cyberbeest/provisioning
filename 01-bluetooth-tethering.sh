#!/bin/bash
# Installs blueman so end users have a Bluetooth GUI (Whisker menu -> Bluetooth
# Manager) to pair their own phone and tether over Bluetooth PAN if they want.
# Ships with Bluetooth disabled by default (rfkill-blocked) -- users opt in via
# the Blueman GUI themselves; we just want it available, not on out of the box.
# Idempotent: safe to re-run.
set -euo pipefail
LOG="$(dirname "$0")/01-bluetooth-tethering.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : provisioning bluetooth tethering support ==="

if dpkg -s blueman >/dev/null 2>&1; then
	echo "blueman already installed, skipping apt install"
else
	apt-get -o DPkg::Lock::Timeout=60 update
	apt-get -o DPkg::Lock::Timeout=60 install -y blueman
fi

if dpkg -s rfkill >/dev/null 2>&1; then
	echo "rfkill already installed, skipping apt install"
else
	apt-get -o DPkg::Lock::Timeout=60 install -y rfkill
fi

update-desktop-database /usr/share/applications || true

echo "=== enabling rfkill state persistence ==="
systemctl enable --now systemd-rfkill.socket

if ls /var/lib/systemd/rfkill/*bluetooth* >/dev/null 2>&1; then
	echo "bluetooth rfkill state already saved (user has toggled it before), leaving as-is"
else
	echo "no saved bluetooth rfkill state yet -- setting initial default to blocked"
	rfkill block bluetooth
fi

echo "=== done ==="
