#!/bin/bash
# Powers the machine off if nobody logs in within TIMEOUT seconds of userspace
# coming up (i.e. of the LUKS passphrase having been accepted). Exits as soon
# as the first seat0 login session (graphical or VT) exists; later locks,
# lid closes etc. are not this daemon's business.
# Env (for testing): TIMEOUT (default 900), POLL (default 10), DRY_RUN=1.
set -u
TIMEOUT="${TIMEOUT:-900}"
POLL="${POLL:-10}"

has_login_session() {
	local s
	for s in $(loginctl list-sessions --no-legend | awk '{print $1}'); do
		# Class=user + Seat=seat0 excludes the greeter (Class=greeter)
		# and SSH logins (no seat).
		if [ "$(loginctl show-session "$s" -p Class --value 2>/dev/null)" = user ] &&
			[ "$(loginctl show-session "$s" -p Seat --value 2>/dev/null)" = seat0 ]; then
			return 0
		fi
	done
	return 1
}

# Monotonic deadline from /proc/uptime (immune to wall-clock jumps).
now() { awk '{print int($1)}' /proc/uptime; }
deadline=$(( $(now) + TIMEOUT ))

while [ "$(now)" -lt "$deadline" ]; do
	if has_login_session; then
		echo "login detected, exiting"
		exit 0
	fi
	sleep "$POLL"
done

if has_login_session; then
	echo "login detected, exiting"
	exit 0
fi
echo "no login within ${TIMEOUT}s, powering off"
if [ "${DRY_RUN:-}" = 1 ]; then
	echo "DRY_RUN: would play chime and poweroff"
	exit 0
fi
# Same raw-ALSA route as the boot chime (no audio server at the greeter).
# aplay runs to completion before poweroff, so nothing cuts it off; the
# wav is only installed when the Sounds profile choice allows it.
CHIME=/usr/local/share/sounds/cyberbeest-first-login-timeout.wav
[ -f "$CHIME" ] && timeout 10 aplay -q -D plughw:0,0 "$CHIME"
exec systemctl poweroff
