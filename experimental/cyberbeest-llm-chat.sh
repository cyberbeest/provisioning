#!/bin/bash
# Standalone launcher for cyberbeest_llm_chat_gui.py -- NOT part of the numbered NN-*.sh
# provisioning sequence (deliberately unnumbered so run-gui.py's [0-9][0-9]-*.sh
# glob never picks it up). Meant for `git checkout`-ing just this one file onto another
# machine (e.g. a desktop PC) to run the chat UI there, typically with the "Discoverable"
# switch on so a Cyberbeest laptop's own copy of the UI can connect to it remotely.
#
# Assumes llama.cpp and the model are already at ~/claude/local-llm-test/llama.cpp, laid out
# the same way as on the machine this was copied from (see cyberbeest_local_llm_perf memory:
# build/bin/llama-server for CPU-only, build-vulkan/bin/llama-server for the Vulkan build).
# Move/build them there first if this is a fresh machine.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLAMA_DIR="$HOME/claude/local-llm-test/llama.cpp"

if [ ! -d "$LLAMA_DIR" ]; then
	echo "Expected llama.cpp at $LLAMA_DIR but it's not there." >&2
	echo "Move/build it there first (build/bin/llama-server and/or build-vulkan/bin/llama-server, plus the qwen model file), then re-run this script." >&2
	exit 1
fi

if ! python3 -c "import gi; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk" >/dev/null 2>&1; then
	echo "PyGObject/GTK3 bindings not found -- installing (needs sudo)..."
	sudo apt-get update
	sudo apt-get install -y python3-gi gir1.2-gtk-3.0
fi

exec python3 "$SCRIPT_DIR/cyberbeest_llm_chat_gui.py" "$@"
