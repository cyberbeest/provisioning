#!/bin/bash
# SUDO_ASKPASS helper for run-gui.py, used the first time it needs a sudo
# password in a given run: sudo execs this and reads the password from its
# stdout. run-gui.py also runs this directly (not via sudo) to grab the
# password into memory once, then reuses it via cached-askpass.sh for the
# rest of that run instead of popping a fresh dialog per script -- see
# RunGuiWindow._get_sudo_password().
#
# --forms (not the simpler --password) because this zenity version ignores
# --text on a --password dialog entirely, always showing its own fixed,
# formally-addressed ("Sie") built-in prompt instead -- --forms respects a
# custom heading and field label, letting this match the informal ("du")
# tone the rest of Cyberbeest's own dialogs use. A single --add-password
# field's value is what lands on stdout, same as --password would give.
. "$(cd "$(dirname "$0")" && pwd)/i18n.sh"
zenity --forms --title="$(t askpass.title)" --text="$(t askpass.heading)" \
	--add-password="$(t askpass.field_label)" \
	2>/dev/null
