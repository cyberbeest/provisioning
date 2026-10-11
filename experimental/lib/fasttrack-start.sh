#!/bin/bash
# "Cyberbeest Fast Track" Whisker entry: turns Fast Track on -- starts the
# watcher, adds the panel icon, and remembers "on" so the watcher comes back at
# the next login (see the autostart entry written by enable-cyberbeest-fast-track.sh).
set -uo pipefail
BIN="$HOME/.local/bin"
STATE="$HOME/.local/state/cyberbeest-fasttrack"
mkdir -p "$STATE"
touch "$STATE/enabled"
pgrep -u "$(id -u)" -f '[c]yberbeest-fasttrack\.sh' >/dev/null || setsid -f "$BIN/cyberbeest-fasttrack.sh" >/dev/null 2>&1
"$BIN/fasttrack-panel-icon.sh" add
notify-send --urgency=low --app-name="Fast Track" "Fast Track is on" \
	"You'll get a confirmation box when there is new code. Click the panel icon to stop it." 2>/dev/null || true
