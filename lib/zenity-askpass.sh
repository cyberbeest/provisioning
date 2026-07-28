#!/bin/bash
# SUDO_ASKPASS helper for run-gui.py: sudo execs this and reads the password
# from its stdout, so run-gui.py never has to see/hold the password itself.
zenity --password --title="Cyberbeest provisioning" \
	--text="Enter your sudo password to run provisioning scripts as root:" \
	2>/dev/null
