#!/bin/bash
# EXPERIMENTAL: TinyTTS as the English voice for Claude Code's spoken replies. About 6x faster
# than Piper on the N3350 (~0.45 s per second of speech), at the price of Node (apt nodejs/npm),
# ~30 MB of npm packages and a resident helper (~220 MB RAM, loaded when a prompt is sent,
# exits after 15 idle minutes). The model takes ~14 s to load, so a reply that arrives before
# it is ready is spoken by Piper. German always stays on Piper. Single male voice, English only.
#
# Needs the Claude Code flow (cyberbeest-claude-install.sh) installed first, so Piper and the
# speak-replies mod exist. Re-running the Claude Code installer puts the Piper-only speak.py
# back; run this script again afterwards.
# Usage: sudo bash enable-tinytts.sh
# Undo:  sudo bash disable-tinytts.sh
# Idempotent: safe to re-run.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/enable-tinytts.log"
exec > >(tee -a "$LOG") 2>&1
echo "=== $(date) : enabling TinyTTS ==="

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
TTS="$TARGET_HOME/.local/share/claude-tts"
SRC="$DIR/lib/tinytts"
MODEL_URL=https://huggingface.co/backtracking/tiny-tts/resolve/main/tinytts.onnx
MODEL_SHA=2a12614685c76597d3eeec6772f2c9ce132001cf6ea8a80609f8db9fd7fb745f

if [ ! -f "$TTS/speak.py" ]; then
	echo "Claude Code spoken replies are not installed -- run the Claude Code installer first." >&2
	exit 1
fi

if ! command -v node >/dev/null || ! command -v npm >/dev/null; then
	echo "--- Node (apt) ---"
	DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs npm
fi

as_user() { sudo -u "$TARGET_USER" "$@"; }

echo "--- Files ---"
as_user install -m 755 "$SRC/speak.py" "$SRC/synth_tiny.js" "$TTS/"
as_user install -d "$TTS/tiny"
echo '{"name":"claude-tts-tiny","private":true,"dependencies":{"tiny-tts":"5.0.1"}}' | as_user tee "$TTS/tiny/package.json" >/dev/null
(cd "$TTS/tiny" && as_user npm install --silent --no-audit --no-fund)
# onnxruntime-node ships GPU provider libraries (~285 MB) this CPU-only use never loads
rm -f "$TTS"/tiny/node_modules/onnxruntime-node/bin/napi-v*/linux/*/libonnxruntime_providers_{cuda,tensorrt}.so

if [ ! -s "$TTS/tiny/tinytts.onnx" ]; then
	echo "--- Model ---"
	as_user curl -fsSL -o "$TTS/tiny/tinytts.onnx.part" "$MODEL_URL"
	if [ "$(sha256sum "$TTS/tiny/tinytts.onnx.part" | cut -d' ' -f1)" != "$MODEL_SHA" ]; then
		rm -f "$TTS/tiny/tinytts.onnx.part"
		echo "Model checksum mismatch, not installing." >&2
		exit 1
	fi
	as_user mv "$TTS/tiny/tinytts.onnx.part" "$TTS/tiny/tinytts.onnx"
fi

echo "TinyTTS enabled: English replies use it from the next prompt on (Piper until it has loaded)."
