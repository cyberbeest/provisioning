#!/bin/bash
# Applies the Cyberbeest-recommended touchpad feel: tap-to-click at the
# Xorg/libinput level (so it works on the LightDM greeter too, not just once
# xfsettingsd starts in the desktop session -- XFCE's own tap-to-click
# setting only covers the latter), plus the per-user pointer tuning
# (sensitivity, motion threshold, tap-to-click, natural/reverse scrolling)
# dialed in on the reference Cyberbeest hardware.
#
# Numbered 00a- rather than the next free NN slot: like
# 00-locale-keyboard-timezone.sh's Menu-key-remap step, this needs a real
# terminal (whiptail) and a yes/no human confirmation rather than being a
# silent config step, and run-gui.py opens each NEEDS_TERMINAL script in its
# own xterm window. Sitting right after 00- means both of provisioning's
# upfront interactive confirmations happen back-to-back before the rest of
# the run settles into the normal streamed-log flow, instead of a second
# confirmation dialog popping up out of nowhere partway through.
#
# Like 00-locale-keyboard-timezone.sh, this always re-prompts on a bare
# re-run (whiptail has no concept of "already answered") -- self-skips if
# already completed since this script was last edited, using the same
# log-newer-than-script check, so "Run all" doesn't re-pop the confirmation
# on every pass. Delete the log (or edit this script) to be asked again.
#
# When run-gui.py's "Provisioning profile" dialog has already collected an
# answer for this (see .provisioning-profile.env, written by that dialog),
# this whiptail prompt is skipped entirely and the script runs piped like
# every other step -- no terminal/whiptail needed at all in that case.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/00a-touchpad-tap-global.log"
PROFILE_FILE="$DIR/.provisioning-profile.env"

if [ -e "$LOG" ] && [ "$LOG" -nt "$0" ]; then
	echo "Already configured touchpad tuning since this script was last edited -- skipping."
	echo "Delete $LOG (or edit this script) to be prompted again."
	exit 0
fi

# run-gui.py's "Provisioning profile" dialog collects this question (and
# 00-locale-keyboard-timezone.sh's) upfront and drops the answers here, so
# provisioning can run start-to-finish without popping a whiptail prompt
# mid-run. Falls back to asking here directly (below) when run standalone,
# e.g. via menu.sh or by hand.
PROFILE_DRIVEN=0
if [ -e "$PROFILE_FILE" ]; then
	# shellcheck disable=SC1090
	. "$PROFILE_FILE"
	[ "${PROVISIONING_PROFILE:-}" = "1" ] && PROFILE_DRIVEN=1
fi

if [ "$PROFILE_DRIVEN" -eq 0 ] && [ ! -t 0 ]; then
	# Same reasoning as 00-locale-keyboard-timezone.sh: backdate the log so a
	# later interactive run still prompts, instead of this headless skip
	# permanently masking it.
	echo "Not running on a terminal -- skipping interactive touchpad setup." | tee "$LOG"
	echo "Run this script directly later (sudo bash 00a-touchpad-tap-global.sh) to configure it." | tee -a "$LOG"
	touch -d @0 "$LOG"
	exit 0
fi

echo "=== $(date) : configuring touchpad tuning ===" | tee "$LOG"

if [ "$PROFILE_DRIVEN" -eq 1 ]; then
	APPLY="${PROVISIONING_TOUCHPAD_TUNING:-no}"
	echo "Using the pre-collected provisioning profile answer for touchpad tuning." | tee -a "$LOG"
else
	apt-get -o DPkg::Lock::Timeout=60 install -y whiptail
	APPLY="no"
	if whiptail --title "Touchpad tuning (Cyberbeest reference hardware)" --yesno \
		"Apply Cyberbeest's recommended touchpad feel?\n\nThis makes tap-to-click work everywhere, including the LightDM login screen (normally tap-to-click only kicks in once you're logged into the desktop), and sets the scrolling direction, sensitivity and motion threshold dialed in on the reference Cyberbeest hardware.\n\nSay Yes for standard Cyberbeest hardware. Say No to leave the touchpad at its Debian/libinput defaults." \
		16 78; then
		APPLY="yes"
	fi
fi

echo "Apply touchpad tuning: $APPLY" | tee -a "$LOG"

if [ "$APPLY" != "yes" ]; then
	echo "=== $(date) : skipped by user choice ===" | tee -a "$LOG"
	exit 0
fi

echo "--- Global tap-to-click (Xorg/libinput, covers the LightDM greeter) ---" | tee -a "$LOG"
CONF_DIR="/etc/X11/xorg.conf.d"
CONF_FILE="$CONF_DIR/90-touchpad-tap.conf"
mkdir -p "$CONF_DIR"
cat > "$CONF_FILE" <<'EOF'
Section "InputClass"
    Identifier "libinput touchpad tap-to-click"
    MatchIsTouchpad "on"
    MatchDevicePath "/dev/input/event*"
    Driver "libinput"
    Option "Tapping" "on"
EndSection
EOF
echo "Wrote $CONF_FILE" | tee -a "$LOG"

echo "--- Per-user touchpad tuning (xfconf) ---" | tee -a "$LOG"
TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

# The touchpad's xfconf property node is keyed off its raw input device
# name (e.g. "SYNA3602:00 0911:5288 Touchpad"), which xfce4-settings turns
# into a property path by dropping every ':' and turning spaces into '_'
# (verified against a live xfconf dump: "SYNA3602:00 0911:5288 Touchpad" ->
# "/SYNA360200_09115288_Touchpad/..."). "0911:5288" here is the chip's
# vendor:product ID, not a per-unit serial (confirmed via /proc/bus/input/
# devices' empty "Uniq=" field) -- but NOT constant across units either:
# a second machine (2026-08-26), same touchpad model (SYNA3602:00) but a
# different board (see below), reported "347D:7640" instead. Good thing
# this is derived fresh from the kernel's own device list every run rather
# than hardcoded.
TOUCHPAD_NAME="$(awk -F'"' '/^N: Name=/{name=$2} /^N: Name=/ && name ~ /[Tt]ouchpad/{print name; exit}' /proc/bus/input/devices)"

if [ -z "$TOUCHPAD_NAME" ]; then
	echo "No touchpad device found in /proc/bus/input/devices -- skipping per-user xfconf tuning." | tee -a "$LOG"
	echo "MANUAL_TODO: No touchpad detected -- open Settings > Mouse and Touchpad to tune it by hand if one is attached later." | tee -a "$LOG"
else
	NODE="$(printf '%s' "$TOUCHPAD_NAME" | tr -d ':' | tr ' ' '_')"
	echo "Touchpad device: $TOUCHPAD_NAME -> xfconf node /$NODE" | tee -a "$LOG"

	# Written to disk only, like 16-power-lock-config.sh's xfconf channel
	# files -- deliberately NOT pushed live via xfconf-query. Tried that
	# first, and on a live machine it made the pointer crawl: xfce4-
	# settings-helper translates this generic "Acceleration" value into
	# whatever scale the actual bound driver (synaptics vs. libinput) wants,
	# and catching a live xfconf change this early in a session (00a- runs
	# right after login, before xfce4-settings-helper's own device-
	# capability probe has necessarily settled) risked that translation
	# running against stale/incomplete device info. A fresh login re-derives
	# it correctly every time, and a reboot/logout is already required for
	# the global tap-to-click piece above, so there's no reason to also
	# force this live in the same script run.
	XML_DIR="$TARGET_HOME/.config/xfce4/xfconf/xfce-perchannel-xml"
	install -d -o "$TARGET_USER" -g "$TARGET_USER" "$XML_DIR"
	DEST="$XML_DIR/pointers.xml"
	if [ -e "$DEST" ] && [ ! -e "$DEST.pre-cyberbeest" ]; then
		cp "$DEST" "$DEST.pre-cyberbeest"
	fi
	cat > "$DEST" <<EOF
<?xml version="1.1" encoding="UTF-8"?>

<channel name="pointers" version="1.0">
  <property name="$NODE" type="empty">
    <property name="Properties" type="empty">
      <property name="libinput_Tapping_Enabled" type="int" value="1"/>
    </property>
    <property name="RightHanded" type="bool" value="true"/>
    <property name="ReverseScrolling" type="bool" value="true"/>
    <property name="Threshold" type="int" value="1"/>
    <property name="Acceleration" type="double" value="5"/>
  </property>
</channel>
EOF
	chown "$TARGET_USER:$TARGET_USER" "$DEST"
	echo "Wrote $DEST (node /$NODE)" | tee -a "$LOG"
fi

echo "=== $(date) : done. Reboot (or log out/in) for both changes above to fully apply. ===" | tee -a "$LOG"
echo "MANUAL_TODO: Reboot (or log out/in) for the touchpad tap-to-click and tuning changes to fully apply." | tee -a "$LOG"
