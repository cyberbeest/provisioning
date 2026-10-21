#!/bin/bash
# Screenshot to clipboard + ~/Pictures/Screenshots, both as JPG.
# Usage: cyberbeest-screenshot.sh screen|window
set -u
mode="${1:-screen}"
dir="$(xdg-user-dir PICTURES 2>/dev/null || echo "$HOME/Pictures")/Screenshots"
mkdir -p "$dir"
file="$dir/Screenshot_$(date +%Y-%m-%d_%H-%M-%S).jpg"

target=root
what="Full screen"
if [ "$mode" = window ]; then
	win="$(xdotool getactivewindow 2>/dev/null || true)"
	if [ -n "$win" ]; then
		target="$win"
		what="Window: $(xdotool getwindowname "$win" 2>/dev/null)"
	fi
fi

import -window "$target" -quality 90 "$file" || exit 1
# Most apps only accept image/png when pasting, so the clipboard gets the
# saved JPG's pixels as PNG (xclip can serve just one type).
convert "$file" png:- | xclip -selection clipboard -t image/png -i
notify-send -i "$file" "Screenshot copied" "$what" 2>/dev/null || true
