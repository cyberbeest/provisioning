#!/bin/bash
# Applies a desktop wallpaper choice: standard | nature | space | previous.
#   standard  Cyberbeest's own default picture, no rotation.
#   nature / space  xfdesktop's built-in image cycling on that photo pack
#             (no daemon or timer of our own).
#   previous  Whatever was set before the first switch away from a custom
#             picture; falls back to standard when nothing was saved.
# Before leaving a custom picture (not ours, not a pack photo) the current
# xfconf wallpaper keys are saved to ~/.config/cyberbeest/wallpaper-previous.tsv.
# Called by the Wallpaper tab in Cyberbeest Settings.
#
# Run as the desktop user inside the session (needs DISPLAY + D-Bus).
set -uo pipefail

PACK="/usr/share/backgrounds/cyberbeest"
# Cyberbeest standard picture; machines that predate the png->jpg switch
# (see 18-desktop-background.sh) still have the .png.
FALLBACK=""
for f in /usr/share/backgrounds/xfce/cyberbeest-fallback.jpg /usr/share/backgrounds/xfce/cyberbeest-fallback.png; do
	[ -r "$f" ] && { FALLBACK="$f"; break; }
done
SAVED="$HOME/.config/cyberbeest/wallpaper-previous.tsv"
# xfdesktop backdrop-cycle-period: 0 seconds, 1 minutes, 2 hours, 3 startup, 4 hourly, 5 daily
CYCLE_PERIOD=2
CYCLE_TIMER=1
KEYS='(workspace[0-9]+/)?(last-image|image-path|image-style|color-style|backdrop-cycle-enable)$'

theme="${1:-}"
case "$theme" in
	standard|nature|space|previous) ;;
	*) echo "usage: $0 standard|nature|space|previous" >&2; exit 2 ;;
esac

monitors="$(xrandr --current 2>/dev/null | awk '/ connected/{print $1}')"
workspace_count="$(xfconf-query -c xfwm4 -p /general/workspace_count 2>/dev/null)"
workspace_count="${workspace_count:-1}"
first_mon="$(echo "$monitors" | head -1)"

xq() { xfconf-query -c xfce4-desktop "$@"; }
set_key() { # path type value
	xq -p "$1" -n -t "$2" -s "$3"
}

# True when the first monitor's workspace0 shows a picture the user chose
# themselves: not cycling, not one of ours.
is_custom() {
	local w="/backdrop/screen0/monitor$first_mon/workspace0" img
	[ "$(xq -p "$w/backdrop-cycle-enable" 2>/dev/null)" = true ] && return 1
	img="$(xq -p "$w/last-image" 2>/dev/null)"
	case "$img" in
		""|"$PACK"/*|/usr/share/backgrounds/xfce/cyberbeest-fallback.*) return 1 ;;
	esac
	return 0
}

save_current() {
	mkdir -p "$(dirname "$SAVED")"
	xq -p /backdrop -l -v | awk -v keys="$KEYS" '
		$1 ~ /^\/backdrop\/screen0\/monitor/ && $1 ~ keys {
			path = $1; sub(/^[^ ]+ +/, ""); print path "\t" $0 }' > "$SAVED.tmp" \
		&& mv "$SAVED.tmp" "$SAVED"
}

restore_saved() {
	local path val
	while IFS=$'\t' read -r path val; do
		case "$path" in
			*/last-image|*/image-path) set_key "$path" string "$val" ;;
			*/image-style|*/color-style) set_key "$path" int "$val" ;;
			*/backdrop-cycle-enable) set_key "$path" bool "$val" ;;
		esac
	done < "$SAVED"
}

if [ "$theme" != previous ] && is_custom; then
	save_current
fi

if [ "$theme" = previous ] && [ -s "$SAVED" ]; then
	restore_saved
else
	if [ "$theme" = nature ] || [ "$theme" = space ]; then
		first="$(ls "$PACK/$theme"/*.jpg 2>/dev/null | head -1)"
		[ -n "$first" ] || { echo "no images in $PACK/$theme" >&2; exit 1; }
	else
		first="$FALLBACK"
		[ -n "$first" ] || { echo "no Cyberbeest standard picture installed" >&2; exit 1; }
	fi
	echo "$monitors" | while read -r mon; do
		[ -n "$mon" ] || continue
		base="/backdrop/screen0/monitor$mon"
		for ws in $(seq 0 $((workspace_count - 1))); do
			w="$base/workspace$ws"
			set_key "$w/last-image" string "$first"
			set_key "$w/image-style" int 5
			set_key "$w/color-style" int 0
			if [ "$theme" = nature ] || [ "$theme" = space ]; then
				set_key "$w/backdrop-cycle-enable" bool true
				set_key "$w/backdrop-cycle-period" int "$CYCLE_PERIOD"
				set_key "$w/backdrop-cycle-timer" uint "$CYCLE_TIMER"
				set_key "$w/backdrop-cycle-random-order" bool true
			else
				set_key "$w/backdrop-cycle-enable" bool false
			fi
		done
		set_key "$base/image-path" string "$first"
		set_key "$base/last-image" string "$first"
	done
fi

xfdesktop --reload 2>/dev/null || true
