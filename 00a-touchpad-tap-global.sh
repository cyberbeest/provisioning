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
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/00a-touchpad-tap-global.log"

if [ -e "$LOG" ] && [ "$LOG" -nt "$0" ]; then
	echo "Already configured touchpad tuning since this script was last edited -- skipping."
	echo "Delete $LOG (or edit this script) to be prompted again."
	exit 0
fi

if [ ! -t 0 ]; then
	# Same reasoning as 00-locale-keyboard-timezone.sh: backdate the log so a
	# later interactive run still prompts, instead of this headless skip
	# permanently masking it.
	echo "Not running on a terminal -- skipping interactive touchpad setup." | tee "$LOG"
	echo "Run this script directly later (sudo bash 00a-touchpad-tap-global.sh) to configure it." | tee -a "$LOG"
	touch -d @0 "$LOG"
	exit 0
fi

apt-get -o DPkg::Lock::Timeout=60 install -y whiptail

echo "=== $(date) : configuring touchpad tuning ===" | tee "$LOG"

APPLY="no"
if whiptail --title "Touchpad tuning (Cyberbeest reference hardware)" --yesno \
	"Apply Cyberbeest's recommended touchpad feel?\n\nThis makes tap-to-click work everywhere, including the LightDM login screen (normally tap-to-click only kicks in once you're logged into the desktop), and sets the scrolling direction, sensitivity and motion threshold dialed in on the reference Cyberbeest hardware.\n\nSay Yes for standard Cyberbeest hardware. Say No to leave the touchpad at its Debian/libinput defaults." \
	16 78; then
	APPLY="yes"
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
TARGET_UID="$(id -u "$TARGET_USER")"
HAVE_SESSION=0
if [ -d "/run/user/$TARGET_UID" ]; then
	HAVE_SESSION=1
	DBUS_ADDR="unix:path=/run/user/$TARGET_UID/bus"
fi

# The touchpad's xfconf property node is keyed off its raw input device
# name (e.g. "SYNA3602:00 0911:5288 Touchpad"), which xfce4-settings turns
# into a property path by dropping every ':' and turning spaces into '_'
# (verified against a live xfconf dump: "SYNA3602:00 0911:5288 Touchpad" ->
# "/SYNA360200_09115288_Touchpad/..."). That name embeds a per-unit serial,
# so it can't be hardcoded -- read it from the kernel's own device list
# instead and derive the node fresh on whatever machine this runs on.
TOUCHPAD_NAME="$(awk -F'"' '/^N: Name=/{name=$2} /^N: Name=/ && name ~ /[Tt]ouchpad/{print name; exit}' /proc/bus/input/devices)"

if [ -z "$TOUCHPAD_NAME" ]; then
	echo "No touchpad device found in /proc/bus/input/devices -- skipping per-user xfconf tuning." | tee -a "$LOG"
	echo "MANUAL_TODO: No touchpad detected -- open Settings > Mouse and Touchpad to tune it by hand if one is attached later." | tee -a "$LOG"
elif [ "$HAVE_SESSION" -ne 1 ]; then
	echo "No active desktop session for $TARGET_USER -- skipping per-user xfconf tuning." | tee -a "$LOG"
	echo "MANUAL_TODO: Re-run 00a-touchpad-tap-global.sh once logged in to apply the per-user touchpad tuning (sensitivity/scrolling)." | tee -a "$LOG"
else
	NODE="$(printf '%s' "$TOUCHPAD_NAME" | tr -d ':' | tr ' ' '_')"
	echo "Touchpad device: $TOUCHPAD_NAME -> xfconf node /$NODE" | tee -a "$LOG"

	set_prop() {
		sudo -u "$TARGET_USER" DBUS_SESSION_BUS_ADDRESS="$DBUS_ADDR" \
			xfconf-query -c pointers -p "/$NODE/$1" -n -t "$2" -s "$3"
	}
	set_prop "Acceleration" double "5.000000"
	set_prop "Threshold" int "1"
	set_prop "RightHanded" bool "true"
	set_prop "ReverseScrolling" bool "true"
	set_prop "Properties/libinput_Tapping_Enabled" int "1"
	echo "Applied touchpad tuning under /$NODE" | tee -a "$LOG"
fi

echo "=== $(date) : done. Reboot (or log out/in) for the global tap-to-click change to fully apply. ===" | tee -a "$LOG"
echo "MANUAL_TODO: Reboot (or log out/in) for the LightDM-level tap-to-click change to fully apply." | tee -a "$LOG"
