#!/bin/bash
# Turns Fast Track off: stops the watcher, removes the panel icon, and forgets
# "on" so it doesn't come back at login. The Whisker entry turns it on again.
set -uo pipefail
STATE="$HOME/.local/state/cyberbeest-fasttrack"
rm -f "$STATE/enabled"
pkill -u "$(id -u)" -f '[c]yberbeest-fasttrack\.sh' || true
notify-send --urgency=low --app-name="Fast Track" "Fast Track is off" 2>/dev/null || true
"$HOME/.local/bin/fasttrack-panel-icon.sh" remove
