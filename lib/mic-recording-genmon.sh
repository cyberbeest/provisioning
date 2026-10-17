#!/bin/bash
# Panel icon for mic-recording-watcher.sh: invisible while nothing records,
# flashes a red dot (red/pale pink) while an app records from the microphone.
# UpdatePeriod must be 500 ms for the flashing; the idle path is a single
# file test (no i18n here: the watcher already wrote the translated heading
# as the state file's first line).

STATE="${XDG_RUNTIME_DIR:-/tmp}/mic-recording.state"
[ -f "$STATE" ] || exit 0

# Flip a toggle on every refresh rather than deriving the phase from the
# clock: refresh interval and flash phase are both ~500 ms, so a clock-based
# phase can alias and always show the same colour.
FLIP="${XDG_RUNTIME_DIR:-/tmp}/mic-recording.flip"
if [ -f "$FLIP" ]; then rm -f "$FLIP"; color="#cc0000"; else : > "$FLIP"; color="#ffb0b0"; fi

tip=""
while IFS= read -r l; do
	l=${l//&/&amp;}; l=${l//</&lt;}; l=${l//>/&gt;}
	tip+="${tip:+&#10;}$l"
done < "$STATE"

echo "<txt><b><span foreground=\"$color\">●</span></b></txt>"
echo "<tool>$tip</tool>"
