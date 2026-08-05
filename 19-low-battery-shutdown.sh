#!/bin/bash
# Configures UPower's battery-warning thresholds and critical action:
# cleanly power off at 5% battery instead of the distro default
# (HybridSleep at 2%), which risks losing the suspended session entirely
# if the battery then dies during or after the sleep. PowerOff isn't in
# UPower's "risky" category, so AllowRiskyCriticalPowerAction doesn't
# need touching.
# PercentageLow/PercentageCritical are also widened away from the distro
# defaults (20%/5%) to 15%/8%, so the critical warning has a real gap
# before PowerOff fires at 5% - at the stock 5%/5% setting, the critical
# notification and the shutdown land on the same poll cycle and the
# warning is never actually seen before the machine powers off.
# Depends on: none.
# Idempotent: safe to re-run (only rewrites the keys it cares about;
# backs up the original config the first time).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/19-low-battery-shutdown.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : configuring low-battery shutdown ==="

CONF=/etc/UPower/UPower.conf
if [ -e "$CONF" ] && [ ! -e "$CONF.pre-cyberbeest" ]; then
	cp "$CONF" "$CONF.pre-cyberbeest"
fi

sed -i \
	-e 's/^PercentageLow=.*/PercentageLow=15.0/' \
	-e 's/^PercentageCritical=.*/PercentageCritical=8.0/' \
	-e 's/^PercentageAction=.*/PercentageAction=5.0/' \
	-e 's/^CriticalPowerAction=.*/CriticalPowerAction=PowerOff/' \
	"$CONF"

echo "--- Resulting config ---"
grep -E '^(PercentageLow|PercentageCritical|PercentageAction|CriticalPowerAction)=' "$CONF"

echo "--- Restarting upower ---"
systemctl restart upower.service

echo "=== $(date) : done ==="
