#!/bin/bash
# Disables suspend/hibernate/hybrid-sleep system-wide; this machine's
# low-power handling is lock+shutdown only (see 26-lid-close-policy.sh
# and 19-low-battery-shutdown.sh), never sleep states.
#
# Masking the systemd sleep targets (rather than setting AllowSuspend=no
# etc. in logind.conf) is what actually blocks it: polkit's
# org.freedesktop.login1.suspend action has allow_active=yes by default,
# so an active local session is pre-authorized to suspend regardless of
# logind's own Allow* config - confirmed live, a direct Suspend() D-Bus
# call still succeeded and the machine actually suspended with
# AllowSuspend=no in place. Masking the targets fails the operation at
# the systemd level itself, for any caller. This also makes
# xfce4-power-manager's low-battery dialog stop offering
# Hibernate/Suspend/Hybrid sleep buttons, since it builds that list from
# logind's CanSuspend/CanHibernate/CanHybridSleep, which report "no"
# once the targets are masked.
# Depends on: none.
# Idempotent: safe to re-run (systemctl mask is a no-op if already masked).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/31-disable-sleep-states.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : disabling sleep states ==="

systemctl mask sleep.target suspend.target hibernate.target \
	hybrid-sleep.target suspend-then-hibernate.target

echo "--- mask state ---"
for t in sleep.target suspend.target hibernate.target hybrid-sleep.target suspend-then-hibernate.target; do
	systemctl is-enabled "$t" 2>&1 || true
done

echo "=== $(date) : done ==="
