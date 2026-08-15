#!/bin/bash
# Root-side helper for the startup chime, invoked via pkexec from
# disk_password_gui.py's "Sound" tab. Unlike set-boot-name.sh/
# set-boot-bright-mode.sh, none of this touches plymouth or the initramfs --
# the boot chime is a plain systemd unit that reads its wav straight off
# disk each time (see cyberbeest-boot-chime.sh), so changes here take
# effect on the very next boot with no rebuild step.
#
# Usage:
#   cyberbeest-set-boot-chime enable|disable
#   cyberbeest-set-boot-chime import <path-to-wav> <original-basename>
#     Installs <path-to-wav> as the active chime and also files it away in
#     the history dir (named "<timestamp>-<sanitized-basename>.wav") so it
#     shows back up in the GUI's dropdown later. Caller (the GUI) is
#     responsible for already having converted the source file to a plain
#     wav via ffmpeg -- this script just moves bytes into place as root.
#   cyberbeest-set-boot-chime select default|<history-filename>
#     Re-activates an already-known sound (the shipped default, or a name
#     previously returned by `import`) without adding a new history entry.
set -euo pipefail

SOUNDS_DIR="/usr/local/share/sounds"
ACTIVE="$SOUNDS_DIR/cyberbeest-boot-chime.wav"
DEFAULT="$SOUNDS_DIR/cyberbeest-boot-chime-default.wav"
HISTORY_DIR="$SOUNDS_DIR/cyberbeest-boot-chime-history"
STATE_FILE="/etc/cyberbeest/boot-chime-enabled"
SELECTED_FILE="/etc/cyberbeest/boot-chime-selected"
MAX_HISTORY=10

cmd="${1:-}"

case "$cmd" in
enable|disable)
	install -d -m 755 /etc/cyberbeest
	printf '%s' "$([ "$cmd" = enable ] && echo 1 || echo 0)" > "$STATE_FILE"
	chmod 644 "$STATE_FILE"
	;;

import)
	src="${2:-}"
	basename_hint="${3:-sound.wav}"
	if [ -z "$src" ] || [ ! -f "$src" ]; then
		echo "Usage: $0 import <path-to-wav> <original-basename>" >&2
		exit 1
	fi
	# Strip to safe characters only -- this runs as root off a name that
	# ultimately traces back to a user-picked filename.
	safe="$(printf '%s' "$basename_hint" | tr -cd 'A-Za-z0-9._-')"
	safe="${safe:-sound.wav}"
	entry="$(date +%Y%m%d-%H%M%S)-${safe}"

	install -d -m 755 "$HISTORY_DIR"
	install -m 644 "$src" "$HISTORY_DIR/$entry"
	install -m 644 "$src" "$ACTIVE"

	install -d -m 755 /etc/cyberbeest
	printf '%s' "$entry" > "$SELECTED_FILE"
	chmod 644 "$SELECTED_FILE"

	# Prune down to the most recent MAX_HISTORY entries so re-imports don't
	# grow this directory forever.
	# shellcheck disable=SC2012
	ls -1t "$HISTORY_DIR" | tail -n "+$((MAX_HISTORY + 1))" | while IFS= read -r old; do
		rm -f "$HISTORY_DIR/$old"
	done
	;;

select)
	name="${2:-}"
	if [ -z "$name" ]; then
		echo "Usage: $0 select default|<history-filename>" >&2
		exit 1
	fi
	if [ "$name" = "default" ]; then
		src="$DEFAULT"
	else
		src="$HISTORY_DIR/$name"
	fi
	if [ ! -f "$src" ]; then
		echo "No such sound: $name" >&2
		exit 1
	fi
	install -m 644 "$src" "$ACTIVE"
	install -d -m 755 /etc/cyberbeest
	printf '%s' "$name" > "$SELECTED_FILE"
	chmod 644 "$SELECTED_FILE"
	;;

*)
	echo "Usage: $0 enable|disable|import|select ..." >&2
	exit 1
	;;
esac
