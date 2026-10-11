#!/bin/bash
# Live K.I.T.T.-style view of the Silero VAD Dictate uses (gated, normalized level meter).
# Dev tool: runs with Dictate's own Python environment. Keys: N toggles normalization, Q/Esc quits.
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$HOME/.local/share/dictate/app/.venv/bin/python" "$DIR/vad_live.py" "$@"
