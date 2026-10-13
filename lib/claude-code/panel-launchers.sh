#!/bin/bash
# Adds/removes the two Claude launchers (blue starburst icons) in the desktop
# panel, through the xfce4-panel xfconf channel that both xfce4-panel and gopanel
# read. Called by cyberbeest-claude-install.sh / -remove.sh as the normal user.
#   panel-launchers.sh add|remove
# Adds only what is missing; an existing launcher for the same app is kept (its
# generic icon is swapped for the blue one). New plugin ids start at 100 (the
# user range; provisioning owns 200+). Test hooks: XFCONF_CHANNEL, PANEL_DIR,
# NO_RELOAD=1.
set -uo pipefail
CH="${XFCONF_CHANNEL:-xfce4-panel}"
PDIR="${PANEL_DIR:-$HOME/.config/xfce4/panel}"
IDS=/panels/panel-1/plugin-ids
X() { xfconf-query -c "$CH" "$@"; }

# name | desktop file name | Exec | icon | comment ; names that count as "already there"
APPS=(
	"Claude Code|cyberbeest-claude-code.desktop|claude-code.desktop|xfce4-terminal --working-directory=$HOME/claude --title=\"Claude Code\" -e \"bash -ic claude\"|claude-code|Cloud AI assistant (sends your work to Anthropic)"
	"Claude Sessions|cyberbeest-claude-sessions.desktop|claude-sessions.desktop|$HOME/claude/claude-sessions-gui.py|claude-sessions|Live list of all Claude Code sessions"
)

current_ids() { X -p "$IDS" 2>/dev/null | grep -E '^[0-9]+$'; }

# id of a launcher plugin (in panel-1) whose items include any of the given file names
find_launcher() {
	local id f
	for id in $(current_ids); do
		[ "$(X -p /plugins/plugin-$id 2>/dev/null)" = launcher ] || continue
		for f in $(X -p /plugins/plugin-$id/items 2>/dev/null | grep -E '\.desktop$'); do
			for want in "$@"; do [ "$f" = "$want" ] && { echo "$id"; return 0; }; done
		done
	done
	return 1
}

write_ids() { # ids...
	local args=() i
	for i in "$@"; do args+=(-t int -s "$i"); done
	X -p "$IDS" -n "${args[@]}" 2>/dev/null || X -p "$IDS" "${args[@]}"
}

free_id() {
	local n=100
	while current_ids | grep -qx "$n" || [ -e "$PDIR/launcher-$n" ] || [ -n "$(X -p /plugins/plugin-$n 2>/dev/null)" ]; do n=$((n + 1)); done
	echo "$n"
}

add() {
	local spec name file alt exec_ icon comment id changed=0 ids last i
	for spec in "${APPS[@]}"; do
		IFS='|' read -r name file alt exec_ icon comment <<<"$spec"
		if id="$(find_launcher "$file" "$alt")"; then
			# keep it, but swap a generic icon for the blue one
			for f in "$PDIR/launcher-$id/$file" "$PDIR/launcher-$id/$alt"; do
				if [ -f "$f" ] && grep -qE '^Icon=(utilities-terminal|utilities-system-monitor)$' "$f"; then
					sed -i "s|^Icon=.*|Icon=$icon|" "$f"; changed=1; echo "updated icon of launcher-$id"
				fi
			done
			continue
		fi
		id="$(free_id)"
		install -d "$PDIR/launcher-$id"
		cat > "$PDIR/launcher-$id/$file" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=$name
Comment=$comment
Exec=$exec_
Icon=$icon
Terminal=false
Categories=Utility;
StartupNotify=false
EOF
		X -p "/plugins/plugin-$id" -n -t string -s launcher
		X -p "/plugins/plugin-$id/items" -n -t string -s "$file" --force-array
		# place after the last existing launcher, else after the first plugin
		ids=($(current_ids)); last=0
		for i in "${!ids[@]}"; do
			[ "$(X -p /plugins/plugin-${ids[$i]} 2>/dev/null)" = launcher ] && last=$i
		done
		write_ids "${ids[@]:0:$((last + 1))}" "$id" "${ids[@]:$((last + 1))}"
		changed=1; echo "added launcher-$id ($name)"
	done
	return $((changed ? 0 : 3))
}

remove() {
	local spec file alt id ids new i changed=0
	for spec in "${APPS[@]}"; do
		IFS='|' read -r _ file alt _ <<<"$spec"
		while id="$(find_launcher "$file" "$alt")"; do
			ids=($(current_ids)); new=()
			for i in "${ids[@]}"; do [ "$i" = "$id" ] || new+=("$i"); done
			write_ids "${new[@]}"
			X -p "/plugins/plugin-$id" -r -R 2>/dev/null
			rm -rf --one-file-system -- "$PDIR/launcher-$id"
			changed=1; echo "removed launcher-$id"
		done
	done
	return $((changed ? 0 : 3))
}

reload_panel() {
	[ -n "${NO_RELOAD:-}" ] && return 0
	export DISPLAY="${DISPLAY:-:0}"
	local pid exe
	pid="$(pgrep -x gopanel | head -1 || true)"
	if [ -n "$pid" ]; then
		exe="$(readlink -f "/proc/$pid/exe")"
		"$exe" reload || true
	elif pgrep -x xfce4-panel >/dev/null; then
		# never `xfce4-panel -r` (flaky): kill and relaunch
		pkill -9 -x xfce4-panel; sleep 1
		(setsid xfce4-panel >/dev/null 2>&1 &)
	fi
}

case "${1:-}" in
add) add && reload_panel ;;
remove) remove && reload_panel ;;
*) echo "usage: $0 add|remove" >&2; exit 2 ;;
esac
exit 0
