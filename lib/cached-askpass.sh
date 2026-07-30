#!/bin/sh
# SUDO_ASKPASS helper for run-gui.py, used for every sudo call after the
# first one in a run: just echoes back the password run-gui.py already
# collected via zenity-askpass.sh and is holding in memory (see
# RunGuiWindow._get_sudo_password()), instead of popping a fresh graphical
# prompt for every single script.
printf '%s\n' "$CACHED_SUDO_PASSWORD"
