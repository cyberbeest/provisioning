#!/bin/bash
# Watches PulseAudio for apps recording from a real microphone and keeps a
# state file for mic-recording-genmon.sh. Event-driven via `pactl subscribe`
# (a new/changed/removed source-output means a recording stream appeared,
# was corked/uncorked or ended). The state file exists only while something
# records; its first line is the (translated) tooltip heading, the others
# are "application (binary, pid N)".
#
# Not counted: monitor sources (what the speakers play), corked (paused)
# streams, and "Peak detect" level-meter streams (pavucontrol, volume UIs).
# Names and PIDs are what the client claims about itself, so this is a
# tripwire, not proof of who is recording.
#
# Installed by 11b-mic-recording-indicator.sh; i18n.sh sits next to this
# script (see lib/i18n.sh on why it resolves its catalogs relative to itself).

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE="${XDG_RUNTIME_DIR:-/tmp}/mic-recording.state"

HEADING="Microphone in use by:"
if [ -f "$SELF_DIR/i18n.sh" ]; then
	. "$SELF_DIR/i18n.sh"
	HEADING="$(t mic_recording.tooltip_heading)"
fi

update() {
	local so src names
	so=$(pactl -f json list source-outputs 2>/dev/null) || return
	src=$(pactl -f json list sources 2>/dev/null) || return
	names=$(jq -r -n --argjson so "$so" --argjson src "$src" '
		($src | map(select(.monitor_of_sink == null) | .index)) as $real
		| $so[]
		| select(.corked == false)
		| select(.source as $s | $real | index($s))
		| select((.properties["media.name"] // "") != "Peak detect")
		| select((.properties["application.id"] // "") != "org.PulseAudio.pavucontrol")
		| (.properties["application.name"] // .properties["application.process.binary"] // "unknown app")
		  + " (" + (.properties["application.process.binary"] // "?")
		  + ", pid " + (.properties["application.process.id"] // "?") + ")"
	' 2>/dev/null)
	if [ -n "$names" ]; then
		printf '%s\n%s\n' "$HEADING" "$names" > "$STATE.tmp" && mv -f "$STATE.tmp" "$STATE"
	else
		rm -f "$STATE"
	fi
}

trap 'rm -f "$STATE" "$STATE.tmp"' EXIT

while true; do
	update
	# pactl subscribe ends when PulseAudio restarts; the loop reconnects.
	while read -r line; do
		case "$line" in
			*"source-output"*|*" on source #"*) update ;;
		esac
	done < <(pactl subscribe 2>/dev/null)
	rm -f "$STATE"
	sleep 5
done
