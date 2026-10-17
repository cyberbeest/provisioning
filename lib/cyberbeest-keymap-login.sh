#!/bin/bash
# Loads the layout from /etc/default/keyboard into X's main ("Virtual core")
# keyboard at login. On some machines X starts with that keyboard on the US
# layout while the physical keyboards already have the right one: typing on
# the keyboard is fine, but text typed by programs through xdotool (Dictate)
# comes out through the US map, with y and z swapped on a German layout.
# `setxkbmap -query` still reports the right layout then, so it is no help
# for spotting this; `xkbcomp -i 3 :0 - | grep 'xkb_symbols "'` shows the
# map really loaded.
#
# The Menu key remap, if installed, rebuilds the keymap from the current one,
# so it must run after this; it is called again at the end because it may
# also have started earlier in the autostart phase and been overwritten here.
[ -r /etc/default/keyboard ] || exit 0
# shellcheck disable=SC1091
. /etc/default/keyboard
[ -n "${XKBLAYOUT:-}" ] || exit 0
args=(-rules evdev -model "${XKBMODEL:-pc105}" -layout "$XKBLAYOUT")
[ -n "${XKBVARIANT:-}" ] && args+=(-variant "$XKBVARIANT")
[ -n "${XKBOPTIONS:-}" ] && args+=(-option "" -option "$XKBOPTIONS")
setxkbmap "${args[@]}"
remap="$HOME/.local/bin/cyberbeest-menu-key-remap.sh"
[ -x "$remap" ] && "$remap"
exit 0
