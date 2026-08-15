#!/bin/bash
# Plays the boot chime directly to ALSA hw, bypassing any user-session
# audio server (none is running yet at this point in boot).
STATE_FILE="/etc/cyberbeest/boot-chime-enabled"
if [ -f "$STATE_FILE" ] && [ "$(cat "$STATE_FILE")" = "0" ]; then
	exit 0
fi
exec aplay -q -D plughw:0,0 /usr/local/share/sounds/cyberbeest-boot-chime.wav
