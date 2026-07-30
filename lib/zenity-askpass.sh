#!/bin/bash
# SUDO_ASKPASS helper for run-gui.py, used the first time it needs a sudo
# password in a given run: sudo execs this and reads the password from its
# stdout. run-gui.py also runs this directly (not via sudo) to grab the
# password into memory once, then reuses it via cached-askpass.sh for the
# rest of that run instead of popping a fresh dialog per script -- see
# RunGuiWindow._get_sudo_password().
zenity --password --title="Cyberbeest provisioning" \
	--text="Enter your sudo password to run provisioning scripts as root:" \
	2>/dev/null
