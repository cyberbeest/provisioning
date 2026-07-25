#!/bin/bash
# Lets the installer pick their language, keyboard layout, and timezone --
# unlike every other NN-*.sh step, these are per-user choices to make fresh,
# not settings to clone from the dev machine (which just happens to be
# en_US.UTF-8 / us / Europe/Berlin). Runs first (00-) since it's the most
# fundamental "who is this machine for" choice, before anything else.
#
# Just drives Debian's own interactive reconfiguration tools (whiptail/
# dialog based) rather than reinventing a picker UI:
#   - dpkg-reconfigure locales             -> /etc/default/locale
#   - dpkg-reconfigure keyboard-configuration -> /etc/default/keyboard
#   - dpkg-reconfigure tzdata               -> /etc/timezone, /etc/localtime
#
# Needs a real terminal (whiptail can't run headlessly) -- if stdin isn't a
# TTY (e.g. a scripted/automated run-all.sh pass), this step is skipped with
# a warning rather than hanging, and can be run manually afterwards.
#
# Re-running always re-prompts (like every dpkg-reconfigure), so under
# run-changed.sh it naturally only asks once (skipped on later passes unless
# this script itself changes); under run-all.sh it asks every time, same as
# that script's documented "run everything unconditionally" behavior.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/00-locale-keyboard-timezone.log"

if [ ! -t 0 ]; then
	echo "Not running on a terminal -- skipping interactive locale/keyboard/timezone setup." | tee "$LOG"
	echo "Run this script directly later (sudo bash 00-locale-keyboard-timezone.sh) to configure it." | tee -a "$LOG"
	exit 0
fi

echo "=== $(date) : configuring locale/keyboard/timezone ===" | tee "$LOG"

apt-get update -qq
apt-get install -y locales keyboard-configuration tzdata console-setup

echo "--- Language/locale ---"
dpkg-reconfigure locales

echo "--- Keyboard layout ---"
dpkg-reconfigure keyboard-configuration
setupcon || true

echo "--- Timezone ---"
dpkg-reconfigure tzdata

echo "=== $(date) : done. Reboot (or log out/in) for the new locale/keyboard to fully apply to the desktop session. ===" | tee -a "$LOG"
