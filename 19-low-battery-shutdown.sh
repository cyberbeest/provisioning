#!/bin/bash
# Configures UPower's critical-battery action: cleanly power off at 5%
# battery instead of the distro default (HybridSleep at 2%), which risks
# losing the suspended session entirely if the battery then dies during or
# after the sleep. PowerOff isn't in UPower's "risky" category, so
# AllowRiskyCriticalPowerAction doesn't need touching.
# Depends on: none.
# Idempotent: safe to re-run (only rewrites the two keys it cares about;
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
	-e 's/^PercentageAction=.*/PercentageAction=5.0/' \
	-e 's/^CriticalPowerAction=.*/CriticalPowerAction=PowerOff/' \
	"$CONF"

echo "--- Resulting config ---"
grep -E '^(PercentageAction|CriticalPowerAction)=' "$CONF"

echo "--- Restarting upower ---"
systemctl restart upower.service

echo "=== $(date) : done ==="
