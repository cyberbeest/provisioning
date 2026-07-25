#!/bin/bash
# Sets the xfce4-desktop wallpaper to the Cyberbeest branding, regardless of
# what XRandR calls the actual monitor (xfdesktop keys its background
# properties by the real output name, e.g. "eDP-1" on this laptop but
# something else entirely on a VM's virtual display -- a static config file
# copied from one machine to another would silently target the wrong
# property path). Instead this runs at each session start, finds whatever
# monitor name(s) xfdesktop has actually created properties for, and sets
# the background on all of them.
#
# Run as the desktop user (not root) -- installed as an XFCE autostart entry.
set -uo pipefail

IMAGE="$HOME/Pictures/Cyberbeest.png"
IMAGE_SIMPLIFIED="$HOME/Pictures/Cyberbeest-simplified.png"

# Wait for xfdesktop to have initialized its per-monitor properties (it
# autostarts alongside this script, so give it a few seconds).
monitors=""
for _ in $(seq 1 15); do
	monitors="$(xfconf-query -c xfce4-desktop -p /backdrop/screen0 -l 2>/dev/null \
		| grep -oE '/monitor[^/]+/' | sort -u)"
	[ -n "$monitors" ] && break
	sleep 1
done

if [ -z "$monitors" ]; then
	echo "cyberbeest-set-wallpaper: xfdesktop never created any monitor properties, giving up" >&2
	exit 0
fi

echo "$monitors" | while read -r mon; do
	mon="${mon#/}"
	mon="${mon%/}"
	base="/backdrop/screen0/$mon"
	xfconf-query -c xfce4-desktop -p "$base/image-path" -n -t string -s "$IMAGE"
	xfconf-query -c xfce4-desktop -p "$base/last-image" -n -t string -s "$IMAGE"
	xfconf-query -c xfce4-desktop -p "$base/last-single-image" -n -t string -s "$IMAGE"
	xfconf-query -c xfce4-desktop -p "$base/image-style" -n -t int -s 4
	xfconf-query -c xfce4-desktop -p "$base/image-show" -n -t bool -s true

	# Per-workspace overrides (if this xfce4-desktop version has any) get the
	# simplified/square logo crop, matching this machine's active setup.
	xfconf-query -c xfce4-desktop -p "$base" -l 2>/dev/null \
		| grep -E '/workspace[0-9]+/last-image$' | while read -r ws_prop; do
		xfconf-query -c xfce4-desktop -p "$ws_prop" -s "$IMAGE_SIMPLIFIED"
	done
done

xfdesktop --reload 2>/dev/null || true
