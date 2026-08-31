#!/bin/bash
# Makes sure every currently-known monitor/workspace slot in xfce4-desktop
# has SOME wallpaper set, defaulting to our fallback image rather than
# xfdesktop's own compiled-in default (a teal swirl with the XFCE mouse
# logo).
#
# Why this exists at all: 18-desktop-background.sh's `update-alternatives`
# dance for /usr/share/images/desktop-base/default does NOT work as its own
# comment claims. That comment assumed xfdesktop falls back to the
# desktop-base default image whenever it can't find a matching per-monitor
# xfconf key. Verified empirically (screenshot, this repo's provisioning VM,
# 2026-08-31) that this is false: with no /backdrop/screen0/monitor<NAME>
# key matching the real xrandr output name, xfdesktop ignores
# desktop-base's alternative entirely and renders its own hardcoded
# default. The only thing that actually controls what renders is an
# xfconf key scoped to the real monitor name and workspace index.
#
# This script only fills in properties that are still unset, so it never
# clobbers a human's manual "pick Cyberbeest in Desktop Settings" choice
# (per 18-desktop-background.sh's own MANUAL_TODO).
#
# Run as the desktop user, with DISPLAY/DBUS_SESSION_BUS_ADDRESS set --
# installed as an XFCE autostart entry so it runs at every login, since the
# monitor name (and workspace count) aren't known until then.
set -uo pipefail

IMAGE="/usr/share/backgrounds/xfce/cyberbeest-fallback.png"

# xrandr can be run before the WM/xfdesktop has fully started, so retry
# briefly rather than assuming X is instantly ready at autostart time.
monitors=""
for _ in $(seq 1 15); do
	monitors="$(xrandr --current 2>/dev/null | awk '/ connected/{print $1}')"
	[ -n "$monitors" ] && break
	sleep 1
done
if [ -z "$monitors" ]; then
	echo "set-fallback-wallpaper: no monitor found via xrandr, giving up" >&2
	exit 0
fi

workspace_count="$(xfconf-query -c xfwm4 -p /general/workspace_count 2>/dev/null)"
workspace_count="${workspace_count:-1}"

is_unset() {
	! xfconf-query -c xfce4-desktop -p "$1" >/dev/null 2>&1
}

echo "$monitors" | while read -r mon; do
	base="/backdrop/screen0/monitor$mon"
	ws=0
	while [ "$ws" -lt "$workspace_count" ]; do
		wsbase="$base/workspace$ws"
		if is_unset "$wsbase/last-image"; then
			xfconf-query -c xfce4-desktop -p "$wsbase/last-image" -n -t string -s "$IMAGE"
			xfconf-query -c xfce4-desktop -p "$wsbase/image-style" -n -t int -s 5
			xfconf-query -c xfce4-desktop -p "$wsbase/color-style" -n -t int -s 0
		fi
		ws=$((ws + 1))
	done
	# Pre-workspace-support xfdesktop versions only look at the monitor-level
	# keys, not any workspace<N> sub-property -- keep both in sync.
	if is_unset "$base/image-path"; then
		xfconf-query -c xfce4-desktop -p "$base/image-path" -n -t string -s "$IMAGE"
		xfconf-query -c xfce4-desktop -p "$base/last-image" -n -t string -s "$IMAGE"
		xfconf-query -c xfce4-desktop -p "$base/image-style" -n -t int -s 5
		xfconf-query -c xfce4-desktop -p "$base/image-show" -n -t bool -s true
	fi
done

xfdesktop --reload 2>/dev/null || true
