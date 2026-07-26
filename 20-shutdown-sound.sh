#!/bin/bash
# Installs a short chime that plays whenever the machine actually powers off
# -- a manual shutdown, the lock-shutdown-watcher auto-shutdown timer, or a
# low-battery critical shutdown (see 19-low-battery-shutdown.sh) -- but not
# on reboot.
#
# Implemented as a systemd --user daemon that holds a logind shutdown
# "delay" inhibitor lock (see cyberbeest-shutdown-chime-daemon.py) rather
# than a system-level ExecStop hook: a delay lock genuinely blocks logind
# from proceeding until the lock is released (bounded by
# InhibitDelayMaxSec, default 5s), and it runs from a still-alive user
# session, so PulseAudio/PipeWire work normally -- an earlier ExecStop-based
# version raced actual poweroff against `aplay` finishing (playback started
# but got cut off, and adding a trailing sleep to buy margin made it go
# silent entirely, most likely PulseAudio/PipeWire's own teardown muting
# the amp before the raw ALSA aplay ran).
# Depends on: none.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/20-shutdown-sound.log"
exec > "$LOG" 2>&1

echo "=== $(date) : installing shutdown chime ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
TARGET_UID="$(id -u "$TARGET_USER")"

echo "--- Installing sound asset ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/sounds"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/assets/cyberbeest-shutdown-chime.wav" \
	"$TARGET_HOME/.local/share/sounds/cyberbeest-shutdown-chime.wav"

echo "--- Installing daemon script ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/cyberbeest-shutdown-chime-daemon.py" \
	"$TARGET_HOME/.local/bin/cyberbeest-shutdown-chime-daemon.py"

echo "--- Installing systemd --user unit ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/systemd/user"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/cyberbeest-shutdown-chime.service" \
	"$TARGET_HOME/.config/systemd/user/cyberbeest-shutdown-chime.service"

echo "--- Enabling it now, if the target user has an active session ---"
if [ -d "/run/user/$TARGET_UID" ]; then
	sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" \
		systemctl --user daemon-reload
	sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" \
		systemctl --user enable --now cyberbeest-shutdown-chime.service
else
	echo "no active session for $TARGET_USER -- it'll start at next login"
fi

echo "=== $(date) : done ==="
