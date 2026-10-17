#!/bin/bash
# Flips claude-sudo-helper-gui.sh between its two post-first-password modes:
#   ask  - every script still needs a one-click OK/Cancel (safer default)
#   auto - once the password is cached, scripts run with no dialog at all
# The running daemon re-reads this file on every marker, so no restart is
# needed after toggling. Usage: run with no args to flip, or pass "ask"/"auto"
# to set it explicitly.

DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
MODE_FILE="$DIR/claude-sudo-helper-gui.confirm-mode"

current="$(cat "$MODE_FILE" 2>/dev/null)"
[[ "$current" == "auto" ]] || current="ask"

case "${1:-}" in
    ask|auto)
        new="$1"
        ;;
    "")
        if [[ "$current" == "ask" ]]; then new="auto"; else new="ask"; fi
        ;;
    *)
        echo "Usage: $0 [ask|auto]" >&2
        exit 1
        ;;
esac

echo "$new" >"$MODE_FILE"

if [[ "$new" == "auto" ]]; then
    body="Cached-password scripts will now run with no confirmation dialog."
else
    body="Cached-password scripts will now still need a one-click OK."
fi
notify-send --urgency=normal --app-name="Claude sudo helper" "Confirm mode: $new" "$body" 2>/dev/null || true
echo "confirm mode set to: $new"
