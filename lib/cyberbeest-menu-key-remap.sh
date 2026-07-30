#!/bin/bash
# Remaps the (otherwise unused) Menu/context-menu key to act as the German
# ISO "<>|" key -- canonical Cyberbeest hardware ships an ANSI-body (104-key)
# keyboard with German stickers/keymap applied, so the physical ISO key
# between left Shift and Y (keycode 94, normally < / > / |) doesn't exist.
# Menu key: plain = <, Shift = >, AltGr = |. Installed by
# 00-locale-keyboard-timezone.sh, opt-in, only offered for German keyboard.
xmodmap -e "keycode 135 = less greater bar dead_belowmacron" 2>/dev/null
