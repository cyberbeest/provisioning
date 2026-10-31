#!/bin/bash
# Undo for enable-tinytts.sh: English goes back to Piper (speak.py falls back by itself when
# the tiny/ folder is gone). Node stays installed.
set -euo pipefail
TARGET_USER="${SUDO_USER:?run via sudo}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
TTS="$TARGET_HOME/.local/share/claude-tts"
# the resident helper runs under the process name claude-voice, started with --serve
for pid in $(pgrep -u "$TARGET_USER" -x claude-voice || true); do
	if tr '\0' ' ' <"/proc/$pid/cmdline" | grep -q -- '--serve'; then kill "$pid" || true; fi
done
rm -rf --one-file-system -- "$TTS/tiny" "$TTS/synth_tiny.js"
rm -f "$TTS/tiny.sock" "$TTS/tiny.sock.starting"
echo "TinyTTS removed."
