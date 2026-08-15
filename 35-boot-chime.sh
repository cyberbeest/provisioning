#!/bin/bash
# Installs a chime that plays as early as possible after the audio DSP/codec
# finishes init at boot (right when /dev/snd/controlC0 appears), well before
# the LightDM greeter is up.
#
# Implemented as a udev-activated, system-level oneshot systemd unit that
# plays directly to ALSA via aplay: no PulseAudio/PipeWire session exists
# yet at that point in boot, so this must talk to the hw device directly
# rather than going through a user-session sound server (see
# 20-shutdown-sound.sh for why the shutdown chime instead runs from a live
# user session -- the two chimes sit on opposite sides of that same
# constraint).
# Depends on: none.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/35-boot-chime.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing boot chime ==="

echo "--- Installing alsa-utils (for aplay) ---"
apt-get update -qq
apt-get install -y alsa-utils

echo "--- Installing sound asset ---"
install -d -m 755 /usr/local/share/sounds
install -m 644 "$DIR/lib/assets/cyberbeest-boot-chime.wav" /usr/local/share/sounds/cyberbeest-boot-chime.wav
# Untouched reference copy so the "Cyberbeest standard chime" entry in the
# GUI's sound dropdown can always be restored, even after custom imports.
install -m 644 "$DIR/lib/assets/cyberbeest-boot-chime.wav" /usr/local/share/sounds/cyberbeest-boot-chime-default.wav
install -d -m 755 /usr/local/share/sounds/cyberbeest-boot-chime-history

echo "--- Installing play script ---"
install -m 755 "$DIR/lib/cyberbeest-boot-chime.sh" /usr/local/bin/cyberbeest-boot-chime.sh

echo "--- Installing sound settings helper (enable/disable/import/select, run via pkexec) ---"
install -m 755 "$DIR/lib/cyberbeest-set-boot-chime.sh" /usr/local/sbin/cyberbeest-set-boot-chime

echo "--- Enabled by default ---"
install -d -m 755 /etc/cyberbeest
if [ ! -f /etc/cyberbeest/boot-chime-enabled ]; then
	printf '1' > /etc/cyberbeest/boot-chime-enabled
	chmod 644 /etc/cyberbeest/boot-chime-enabled
fi

echo "--- Installing systemd unit (device-activated, no [Install]/enable needed) ---"
install -m 644 "$DIR/lib/cyberbeest-boot-chime.service" /etc/systemd/system/cyberbeest-boot-chime.service

echo "--- Installing udev rule that pulls the service in when controlC0 appears ---"
install -m 644 "$DIR/lib/99-cyberbeest-boot-chime.rules" /etc/udev/rules.d/99-cyberbeest-boot-chime.rules

echo "--- Reloading systemd + udev rules ---"
systemctl daemon-reload
udevadm control --reload-rules

echo "=== $(date) : done. Chime will fire on next reboot right after DSP init. ==="
