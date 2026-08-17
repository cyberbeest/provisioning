#!/bin/bash
# Click action for the security-update-check genmon icon (see
# update-genmon.sh): shows the log of the last check/install run.
set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$SELF_DIR/i18n.sh"

LOG_FILE=/var/log/security-update-check-last.log

if [ -r "$LOG_FILE" ]; then
    zenity --text-info --title="$(t update_genmon.log_title)" \
        --filename="$LOG_FILE" --width=800 --height=600 --font="Monospace 9"
else
    zenity --info --title="$(t update_genmon.log_title)" \
        --text="$(t update_genmon.log_missing)" --width=360
fi
