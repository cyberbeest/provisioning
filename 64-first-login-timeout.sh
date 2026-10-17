#!/bin/bash
# Powers the machine off if nobody logs in within 15 minutes after the LUKS
# unlock (userspace start). A small systemd service polls logind for a seat0
# login session and exits for good once one appears; if the deadline passes
# first it runs systemctl poweroff. Later idle locks / lid close are
# unaffected.
# Deliberately a service with a /proc/uptime deadline, not a systemd timer:
# OnBootSec would count the time spent at the LUKS prompt (see
# feedback_systemd_timers_luks_boot_delay). Sleep states are masked by
# 31-disable-sleep-states.sh, so monotonic time can't stall mid-wait.
# On autologin images (release VM) a session exists at once, so the service
# exits immediately.
# Plays the shutdown chime (raw ALSA, like the boot chime) just before
# powering off, unless the Sounds profile choice is "no".
# Depends on: none.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/64-first-login-timeout.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing first-login timeout ==="

install -m 755 "$DIR/lib/cyberbeest-first-login-timeout.sh" /usr/local/sbin/cyberbeest-first-login-timeout.sh
install -m 644 "$DIR/lib/cyberbeest-first-login-timeout.service" /etc/systemd/system/cyberbeest-first-login-timeout.service

# Shutdown chime before the poweroff, unless the Sounds profile choice is "no"
PROVISIONING_SOUNDS="yes"
[ -f "$DIR/.provisioning-profile.env" ] && . "$DIR/.provisioning-profile.env"
if [ "$PROVISIONING_SOUNDS" = "no" ]; then
	rm -f /usr/local/share/sounds/cyberbeest-first-login-timeout.wav
else
	install -d -m 755 /usr/local/share/sounds
	install -m 644 "$DIR/lib/assets/cyberbeest-shutdown-chime.wav" /usr/local/share/sounds/cyberbeest-first-login-timeout.wav
fi

systemctl daemon-reload
# enable only: starting now would power off a machine that is up with no
# login session (e.g. while provisioning over SSH)
systemctl enable cyberbeest-first-login-timeout.service

echo "=== $(date) : done. Active from next boot. ==="
