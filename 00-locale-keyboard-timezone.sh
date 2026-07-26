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

# rsync goes in first, and ahead of the TTY gate below, so it's available
# from the very start of provisioning (including headless run-all.sh passes)
# to send the NN-*.log files this and later steps produce back to the dev
# machine as you go, rather than only after the whole run finishes.
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y rsync

if [ ! -t 0 ]; then
	echo "Not running on a terminal -- skipping interactive locale/keyboard/timezone setup." | tee "$LOG"
	echo "Run this script directly later (sudo bash 00-locale-keyboard-timezone.sh) to configure it." | tee -a "$LOG"
	exit 0
fi

echo "=== $(date) : configuring locale/keyboard/timezone ===" | tee "$LOG"

apt-get -o DPkg::Lock::Timeout=60 install -y locales keyboard-configuration tzdata console-setup

echo "--- Language/locale ---"
echo "Tip: in the checklist, just tick the locale(s) you actually plan to use"
echo "(e.g. de_DE.UTF-8), plus en_US.UTF-8 as a fallback if you want it for"
echo "tools/logs that assume it -- no need to generate every locale in the"
echo "list. The next screen picks which of your ticked locales is the default."
dpkg-reconfigure locales

echo "--- Keyboard layout ---"
# -p high skips the keyboard *model* question (medium priority, always
# "Generic 105-key PC" in practice -- there's no real choice to make here on
# a PC/VM) while still asking the actual layout/language question (critical
# priority, always shown regardless of -p). Preseed the model too, as a
# belt-and-braces default in case anything reads it before this runs.
debconf-set-selections <<-EOF
	keyboard-configuration keyboard-configuration/modelcode string pc105
	keyboard-configuration keyboard-configuration/model select Generic 105-key PC
EOF
dpkg-reconfigure -p high keyboard-configuration
setupcon || true

echo "--- Timezone ---"
dpkg-reconfigure tzdata

echo "=== $(date) : done. Reboot (or log out/in) for the new locale/keyboard to fully apply to the desktop session. ===" | tee -a "$LOG"
