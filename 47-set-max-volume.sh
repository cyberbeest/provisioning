#!/bin/bash
# Sets the default speaker and mic volume to 100% -- a one-time default, not
# an enforced setting: PulseAudio persists this via its own stream/device
# restore database, so the user is free to turn it down afterwards and it
# will stay down across reboots.
# Needs a live PulseAudio user session to talk to (pactl, not xfconf --
# there's no on-disk config file to just write ahead of time the way
# 00a-touchpad-tap-global.sh/16-power-lock-config.sh do), so unlike those
# two this applies live, immediately, during the provisioning run itself.
# Idempotent: safe to re-run (just sets the same values again).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/47-set-max-volume.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : setting default speaker/mic volume to 100% ===" | tee -a "$LOG"

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_UID="$(id -u "$TARGET_USER")"

if [ ! -d "/run/user/$TARGET_UID" ]; then
	echo "No active desktop session for $TARGET_USER -- skipping." | tee -a "$LOG"
	echo "MANUAL_TODO: Re-run 47-set-max-volume.sh once logged in to set speaker/mic to 100%." | tee -a "$LOG"
	exit 0
fi

run_as_user() {
	sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" "$@"
}

run_as_user pactl set-sink-volume @DEFAULT_SINK@ 100% | tee -a "$LOG"
run_as_user pactl set-sink-mute @DEFAULT_SINK@ 0 | tee -a "$LOG"
run_as_user pactl set-source-volume @DEFAULT_SOURCE@ 100% | tee -a "$LOG"
run_as_user pactl set-source-mute @DEFAULT_SOURCE@ 0 | tee -a "$LOG"

echo "Speaker and mic set to 100%, unmuted." | tee -a "$LOG"
echo "=== $(date) : done ===" | tee -a "$LOG"
