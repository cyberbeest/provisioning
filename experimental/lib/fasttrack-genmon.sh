#!/bin/bash
# Fast Track panel item (genmon plugin-230, added by enable-cyberbeest-fast-track.sh).
# State comes from the watcher's files in ~/.local/state/cyberbeest-fasttrack:
# "remote" = newest main commit seen on the v-server, 
STATE="$HOME/.local/state/cyberbeest-fasttrack"
ICON_DIR="$HOME/.local/share/cyberbeest-fasttrack"
ICON_OK="$ICON_DIR/fasttrack-ok.png"
ICON_NEW="$ICON_DIR/fasttrack-update.png"
ICON_OFF="$ICON_DIR/fasttrack-off.png"

repo=""
for d in "$HOME/provisioning-bleeding" "$HOME/provisioning"; do [ -d "$d/.git" ] && { repo="$d"; break; }; done
head="$(git -C "$repo" rev-parse HEAD 2>/dev/null)"
remote="$(cat "$STATE/remote" 2>/dev/null)"

if [ -e /etc/cyberbeest/fasttrack-disabled ]; then
	echo "<img>${ICON_OFF}</img>"
	echo "<tool>Fast Track is disabled on this machine.&#10;Click for options.</tool>"
elif [ -n "$remote" ] && [ -n "$head" ] && [ "$remote" != "$head" ] \
	&& ! git -C "$repo" merge-base --is-ancestor "$remote" HEAD 2>/dev/null; then
	echo "<img>${ICON_NEW}</img>"
	echo "<tool>Fast Track: a new update is available.&#10;Click for options.</tool>"
else
	echo "<img>${ICON_OK}</img>"
	echo "<tool>Fast Track: up to date.&#10;Click for options.</tool>"
fi
echo "<click>$HOME/.local/bin/fasttrack-menu.py</click>"
