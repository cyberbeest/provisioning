#!/bin/bash
# VM-mode desktop background: forces every monitor/workspace slot in
# xfce4-desktop to a flat solid color instead of an image -- cheaper to
# render than the wallpaper photo, an instant visual tell that this
# session is the VM guest, not the host, and (blue, rather than something
# lighter) keeps the white desktop-icon labels legible.
#
# Unlike lib/set-fallback-wallpaper.sh, this always overrides rather than
# only filling in unset keys: VM mode is an explicit product choice, not a
# fallback for a key nobody's touched yet.
#
# Run as the desktop user, with DISPLAY/DBUS_SESSION_BUS_ADDRESS set --
# installed as an XFCE autostart entry by 90-vm-mode-overrides.sh so it
# runs at every login, since the real monitor name isn't known any earlier
# (same reasoning as set-fallback-wallpaper.sh).
#
# Writes "rgba1", NOT "color1": xfdesktop 4.20's actual backdrop painter
# (xfce-desktop.c) only reads /rgba1 (a GdkRGBA double array) -- "color1"
# is a legacy uint16-array key the Desktop Settings dialog still displays/
# round-trips for backward compat, but the renderer itself ignores it
# outright. Writing color1 alone (even with color-style=Solid and
# image-style=None both correctly set) silently renders plain white.
# Confirmed via `strings /usr/bin/xfdesktop`, which only references
# "/rgba1"/"/rgba2" as backdrop xfconf paths, not "/color1"/"/color2".
set -uo pipefail

COLOR_R=0.113725
COLOR_G=0.207843
COLOR_B=0.341176
COLOR_A=1.000000   # #1D3557, flat dark blue -- readable against white desktop-icon labels

monitors=""
for _ in $(seq 1 15); do
	monitors="$(xrandr --current 2>/dev/null | awk '/ connected/{print $1}')"
	[ -n "$monitors" ] && break
	sleep 1
done
if [ -z "$monitors" ]; then
	echo "set-vm-solid-background: no monitor found via xrandr, giving up" >&2
	exit 0
fi

workspace_count="$(xfconf-query -c xfwm4 -p /general/workspace_count 2>/dev/null)"
workspace_count="${workspace_count:-1}"

echo "$monitors" | while read -r mon; do
	base="/backdrop/screen0/monitor$mon"
	xfconf-query -c xfce4-desktop -p "$base/image-style" -n -t int -s 0
	xfconf-query -c xfce4-desktop -p "$base/color-style" -n -t int -s 0
	xfconf-query -c xfce4-desktop -p "$base/rgba1" -n \
		-t double -t double -t double -t double \
		-s "$COLOR_R" -s "$COLOR_G" -s "$COLOR_B" -s "$COLOR_A"

	ws=0
	while [ "$ws" -lt "$workspace_count" ]; do
		wsbase="$base/workspace$ws"
		xfconf-query -c xfce4-desktop -p "$wsbase/image-style" -n -t int -s 0
		xfconf-query -c xfce4-desktop -p "$wsbase/color-style" -n -t int -s 0
		xfconf-query -c xfce4-desktop -p "$wsbase/rgba1" -n \
			-t double -t double -t double -t double \
			-s "$COLOR_R" -s "$COLOR_G" -s "$COLOR_B" -s "$COLOR_A"
		ws=$((ws + 1))
	done
done

xfdesktop --reload 2>/dev/null || true
