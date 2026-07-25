#!/bin/bash
# Sets the xfce4-desktop wallpaper to the Cyberbeest branding, regardless of
# what XRandR calls the actual monitor (xfdesktop keys its background
# properties by the real output name, e.g. "eDP-1" on this laptop but
# something else entirely on a VM's virtual display -- a static config file
# copied from one machine to another would silently target the wrong
# property path).
#
# xfce4-desktop does NOT eagerly create any /backdrop properties on its own
# at startup -- it only writes them once something (e.g. the Desktop
# Settings dialog) actually sets a value. So rather than wait for xfdesktop
# to "create" a property path that may never appear on its own, derive the
# real monitor name(s) directly from xrandr (authoritative, available as
# soon as X is up) and create the properties ourselves.
#
# Run as the desktop user (not root) -- installed as an XFCE autostart entry.
set -uo pipefail

IMAGE="$HOME/Pictures/Cyberbeest.png"
IMAGE_SIMPLIFIED="$HOME/Pictures/Cyberbeest-simplified.png"

# xrandr can be run before the WM/xfdesktop has fully started, so retry
# briefly rather than assuming X is instantly ready at autostart time.
monitors=""
for _ in $(seq 1 15); do
	monitors="$(xrandr --current 2>/dev/null | awk '/ connected/{print $1}')"
	[ -n "$monitors" ] && break
	sleep 1
done

# Fold in any monitor names xfdesktop already has properties for (e.g. if
# Desktop Settings was already opened once), in case it differs from what
# xrandr reports right now.
existing="$(xfconf-query -c xfce4-desktop -p /backdrop/screen0 -l 2>/dev/null \
	| grep -oE '/monitor[^/]+/' | sed 's#/monitor##;s#/##' | sort -u)"

all_monitors="$(printf '%s\n%s\n' "$monitors" "$existing" | sed '/^$/d' | sort -u)"

if [ -z "$all_monitors" ]; then
	echo "cyberbeest-set-wallpaper: no monitor found via xrandr or xfconf, giving up" >&2
	exit 0
fi

echo "$all_monitors" | while read -r mon; do
	base="/backdrop/screen0/monitor$mon"
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
