#!/bin/bash
# Remaps the (otherwise unused) Menu/context-menu key to act as the German
# ISO "<>|" key -- canonical Cyberbeest hardware ships an ANSI-body (104-key)
# keyboard with German stickers/keymap applied, so the physical ISO key
# between left Shift and Y (keycode 94, normally < / > / |) doesn't exist.
# Menu key: plain = <, Shift = >, AltGr = |. Installed by
# 00-locale-keyboard-timezone.sh, opt-in, only offered for German keyboard.
#
# Plain xmodmap doesn't work here: the Menu key's compiled XKB type only
# supports 2 levels, so handing it 4 symbols via xmodmap gets silently
# split into two keyboard *groups* of 2 levels each instead of 4 levels in
# one group -- AltGr addresses level 3 within a group, so it can never
# reach the symbols that landed in group 2. Declaring the key's type as
# FOUR_LEVEL via a real xkb_symbols override is what actually makes AltGr
# reach the 3rd/4th level.
mkdir -p "$HOME/.xkb/symbols"
cat > "$HOME/.xkb/symbols/cyberbeest" <<'EOF'
partial default alphanumeric_keys
xkb_symbols "menu_lsgt" {
    key <COMP> {
        type = "FOUR_LEVEL",
        symbols[Group1] = [ less, greater, bar, dead_belowmacron ]
    };
};
EOF

CURRENT_LAYOUT="$(setxkbmap -query | awk -F': *' '/^layout/{print $2}')"
CURRENT_MODEL="$(setxkbmap -query | awk -F': *' '/^model/{print $2}')"
CURRENT_RULES="$(setxkbmap -query | awk -F': *' '/^rules/{print $2}')"

# setxkbmap's own -symbols apply path errors out here ("Error loading new
# keyboard description", exit 5) even though the keymap it prints is valid --
# piping that printed source through xkbcomp directly is what actually works.
setxkbmap -I"$HOME/.xkb" -rules "${CURRENT_RULES:-evdev}" -model "${CURRENT_MODEL:-pc104}" \
	-layout "${CURRENT_LAYOUT:-de}" \
	-symbols "pc+${CURRENT_LAYOUT:-de}+inet(evdev)+cyberbeest(menu_lsgt)" -print \
	| xkbcomp -I"$HOME/.xkb" - "$DISPLAY" >/dev/null 2>&1
