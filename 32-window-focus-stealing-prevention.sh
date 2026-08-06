#!/bin/bash
# Stops brand-new windows from stealing keyboard focus. Without this, any
# new window -- including a background daemon's zenity dialog (e.g.
# claude-sudo-helper-gui.sh's "Run this as root?" confirm prompt) -- grabs
# keyboard focus the instant it appears. Since GTK dialogs default-focus
# their affirmative button, a stray keypress meant for whatever window the
# user was actually in (e.g. spacebar to scroll a page) can land on "Yes"
# and silently confirm a root script run. Discovered 2026-08-06 after the
# sudo-helper ran a couple of RUNME scripts the user didn't remember
# approving.
#
# xfwm4 has two separate settings that both sound relevant here:
#   prevent_focus_stealing -- only stops an *already-mapped* window from
#     re-requesting focus later; does NOT affect a window's initial focus
#     on first mapping. Tested live (2026-08-06): turning this on by itself
#     did NOT stop a fresh zenity dialog from grabbing focus.
#   focus_new -- controls whether newly-mapped windows receive focus at
#     all. This is the one that actually matters here; confirmed via
#     xdotool that setting it to false keeps the active window active when
#     a new dialog appears.
# Both are set for belt-and-suspenders, but focus_new=false is the fix.
# With these on, new windows demand attention (flash in the taskbar)
# instead of stealing focus outright.
# Idempotent: safe to re-run. Applies live via xfconf, no restart needed.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/32-window-focus-stealing-prevention.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : enabling xfwm4 focus-stealing prevention ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_UID="$(id -u "$TARGET_USER")"

if [ -d "/run/user/$TARGET_UID" ]; then
	sudo -u "$TARGET_USER" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$TARGET_UID/bus" \
		xfconf-query -c xfwm4 -p /general/prevent_focus_stealing -n -t bool -s true
	sudo -u "$TARGET_USER" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$TARGET_UID/bus" \
		xfconf-query -c xfwm4 -p /general/focus_new -n -t bool -s false
else
	echo "no active session for $TARGET_USER -- xfconf needs a running session, skipping;" \
		"re-run this script once logged in"
fi

echo "=== $(date) : done ==="
