#!/bin/bash
# Runs at every login inside a Cyberbeest *sandbox* VM (the VM a Cyberbeest
# laptop runs untrusted apps in -- marked by /etc/cyberbeest/sandbox-vm,
# written by the host's lib/download-and-create-sandbox-vm-kvm.sh). Not used
# on laptops or in the standalone VM product, which keep their full setup.
#
# Inside the sandbox some of the laptop's own setup is just noise:
#   - auto-lock, screensaver and display blanking: the host locks itself,
#     and a second lock screen inside a window helps no one
#   - the KITT scanner in the panel: constant motion in a second panel
#     right next to the host's own
#   - the photo wallpaper: replaced by a faint "VM" watermark on dark blue,
#     so it's obvious at a glance which desktop is the VM
# Re-applied at every login rather than once, since the guest's own
# provisioning (12-, 16-, 18-) puts its defaults back whenever it updates.
# Only writes what differs, and restarts the panel only if the scanner is
# actually there.
#
# Installed to ~/.local/bin (with its autostart entry and the tile image) by
# 91-sandbox-vm.sh, and by the host's VM setup for a fresh VM.
set -uo pipefail

TILE="$HOME/.local/share/cyberbeest/vm-background-tile.png"
BASE_R=0.113725 BASE_G=0.207843 BASE_B=0.341176  # #1D3557 behind the tile
KITT_TYPE="kitt-scanner"

set_prop() {  # channel property type value
	local current
	current="$(xfconf-query -c "$1" -p "$2" 2>/dev/null)"
	[ "$current" = "$4" ] || xfconf-query -c "$1" -p "$2" -n -t "$3" -s "$4"
}

# xfconfd can drop writes made right after login; wait until it answers.
for _ in $(seq 1 30); do
	xfconf-query -c xfce4-panel -p /panels >/dev/null 2>&1 && break
	sleep 1
done

set_prop xfce4-screensaver /saver/enabled bool false
set_prop xfce4-screensaver /saver/idle-activation/enabled bool false
set_prop xfce4-screensaver /lock/enabled bool false
PM=/xfce4-power-manager
set_prop xfce4-power-manager "$PM/dpms-enabled" bool false
set_prop xfce4-power-manager "$PM/brightness-on-ac" int 9
set_prop xfce4-power-manager "$PM/brightness-on-battery" int 9

# Background: per connector, known only now (see 18-desktop-background.sh).
monitors=""
for _ in $(seq 1 15); do
	monitors="$(xrandr --current 2>/dev/null | awk '/ connected/{print $1}')"
	[ -n "$monitors" ] && break
	sleep 1
done
workspaces="$(xfconf-query -c xfwm4 -p /general/workspace_count 2>/dev/null || echo 1)"
changed=false
for mon in $monitors; do
	ws=0
	while [ "$ws" -lt "$workspaces" ]; do
		base="/backdrop/screen0/monitor$mon/workspace$ws"
		if [ "$(xfconf-query -c xfce4-desktop -p "$base/last-image" 2>/dev/null)" != "$TILE" ] \
			|| [ "$(xfconf-query -c xfce4-desktop -p "$base/image-style" 2>/dev/null)" != 2 ]; then
			xfconf-query -c xfce4-desktop -p "$base/color-style" -n -t int -s 0
			xfconf-query -c xfce4-desktop -p "$base/rgba1" -n -t double -t double -t double -t double \
				-s "$BASE_R" -s "$BASE_G" -s "$BASE_B" -s 1
			xfconf-query -c xfce4-desktop -p "$base/image-style" -n -t int -s 2  # tiled
			xfconf-query -c xfce4-desktop -p "$base/last-image" -n -t string -s "$TILE"
			changed=true
		fi
		ws=$((ws + 1))
	done
done
[ "$changed" = true ] && { xfdesktop --reload >/dev/null 2>&1 || true; }

# KITT scanner: drop it from every panel's plugin-ids, then restart the
# panel so it goes away now rather than at the next login.
kitt_ids=""
for prop in $(xfconf-query -c xfce4-panel -l 2>/dev/null | grep -E '^/plugins/plugin-[0-9]+$'); do
	[ "$(xfconf-query -c xfce4-panel -p "$prop" 2>/dev/null)" = "$KITT_TYPE" ] && kitt_ids="$kitt_ids ${prop##*-}"
done
if [ -n "$kitt_ids" ]; then
	for panel in $(xfconf-query -c xfce4-panel -p /panels 2>/dev/null | grep -E '^[0-9]+$'); do
		ids="$(xfconf-query -c xfce4-panel -p "/panels/panel-$panel/plugin-ids" 2>/dev/null | grep -E '^[0-9]+$')"
		keep=()
		found=false
		for id in $ids; do
			if [[ " $kitt_ids " == *" $id "* ]]; then found=true; else keep+=(-t int -s "$id"); fi
		done
		[ "$found" = true ] && xfconf-query -c xfce4-panel -p "/panels/panel-$panel/plugin-ids" -n -a "${keep[@]}"
	done
	for id in $kitt_ids; do
		xfconf-query -c xfce4-panel -p "/plugins/plugin-$id" -r -R
	done
	# Kill and relaunch, never `xfce4-panel -r`, which restarts from the
	# panel's own cached config and can write that back over the change
	# just made -- same approach as lib/xfce-panel-reload.sh.
	pkill -9 -u "$(id -u)" -x xfce4-panel
	for _ in $(seq 1 60); do
		pgrep -u "$(id -u)" -x xfce4-panel >/dev/null || break
		sleep 0.5
	done
	setsid xfce4-panel >/dev/null 2>&1 </dev/null &
fi
