#!/bin/bash
# Hides / restores a genmon panel icon without losing its place or settings.
#   panel-icon.sh hide <plugin-id> <title>   take the icon off the panel; add a Whisker entry
#                                            "Show <title> in Panel" that brings it back
#   panel-icon.sh show <plugin-id>           put it back where it was; remove that entry
# Hiding only removes the id from panel-1's plugin-ids; the plugin's xfconf type and its
# genmon-<id>.rc stay, so settings survive. The old neighbours are remembered in
# ~/.config/cyberbeest/panel-hidden/<id>, which 12-xfce-panel-layout.sh also reads so a
# provisioning re-run doesn't put hidden icons back. Called by gopanel's "Remove from panel".
set -uo pipefail

ACTION="${1:-}" ID="${2:-}" TITLE="${3:-}"
[[ "$ID" =~ ^[0-9]+$ ]] || { echo "Usage: $0 hide <id> <title> | show <id>" >&2; exit 1; }

HIDDEN_DIR="$HOME/.config/cyberbeest/panel-hidden"
APPS="$HOME/.local/share/applications"
ENTRY="$APPS/cyberbeest-show-panel-icon-$ID.desktop"
REC="$HIDDEN_DIR/$ID"

get_ids() { xfconf-query -c xfce4-panel -p /panels/panel-1/plugin-ids | grep -E '^[0-9]+$'; }
set_ids() {
	local args=(-c xfce4-panel -p /panels/panel-1/plugin-ids -n -a) i
	for i in "$@"; do args+=(-t int -s "$i"); done
	xfconf-query "${args[@]}"
}

# One-line description (en|de) of what an icon does, by the script its genmon runs; shown as
# the Whisker entry's description. Unknown scripts get a generic line.
describe() {
	local cmd base
	cmd=$(sed -n 's/^Command=//p' "$HOME/.config/xfce4/panel/genmon-$ID.rc" 2>/dev/null | head -1)
	base=$(basename "${cmd%% *}")
	case "$base" in
	swap-indicator-genmon.sh) echo "A red glow that lights up while memory is being swapped to or from the disk, then fades.|Ein rotes Leuchten, das aufleuchtet, solange Speicher auf die Festplatte aus- oder eingelagert wird, und dann verblasst." ;;
	mic-recording-genmon.sh) echo "Flashes a red dot while an app records from the microphone.|Blinkt rot, solange eine App das Mikrofon aufnimmt." ;;
	connections-genmon.sh) echo "A globe whose tooltip lists which apps hold network connections.|Ein Globus, dessen Tooltip zeigt, welche Apps Netzwerkverbindungen haben." ;;
	clipboard-status-genmon.sh) echo "Shows what kind of content is on the clipboard, with a menu to view or clear it.|Zeigt, welche Art Inhalt in der Zwischenablage liegt, mit Menü zum Ansehen und Leeren." ;;
	panel-status-genmon.sh) echo "Security update status and the auto-shutdown timer for when the screen is locked.|Status der Sicherheitsupdates und der Abschalt-Timer für den gesperrten Bildschirm." ;;
	fasttrack-genmon.sh) echo "Shows whether Fast Track has a new update waiting.|Zeigt, ob Fast Track ein neues Update bereithält." ;;
	*) echo "Put the $TITLE icon back on the panel.|Das Symbol $TITLE wieder in der Leiste anzeigen." ;;
	esac
}

write_entry() {
	local desc en de
	desc=$(describe) en=${desc%%|*} de=${desc#*|}
	cat > "$ENTRY" <<EOT
[Desktop Entry]
Type=Application
Name=Show $TITLE in Panel
Name[de]=$TITLE in der Leiste anzeigen
Comment=$en
Comment[de]=$de
Icon=preferences-desktop
Exec=$HOME/.local/bin/panel-icon.sh show $ID
Categories=Cyberbeest;Settings;
Terminal=false
EOT
	update-desktop-database "$APPS" >/dev/null 2>&1 || true
}

case "$ACTION" in
hide)
	mapfile -t ids < <(get_ids)
	after="" before="" new=() seen=0
	for i in "${ids[@]}"; do
		if [ "$i" = "$ID" ]; then seen=1; continue; fi
		[ "$seen" -eq 1 ] && [ -z "$before" ] && before="$i"
		[ "$seen" -eq 0 ] && after="$i"
		new+=("$i")
	done
	[ "$seen" -eq 1 ] || { echo "plugin $ID is not on the panel" >&2; exit 1; }
	install -d "$HIDDEN_DIR" "$APPS"
	printf 'title=%s\nafter=%s\nbefore=%s\n' "$TITLE" "$after" "$before" > "$REC"
	set_ids "${new[@]}" || exit 1
	write_entry
	;;
show)
	after="" before=""
	if [ -r "$REC" ]; then
		while IFS='=' read -r k v; do
			case "$k" in after) after=$v ;; before) before=$v ;; esac
		done < "$REC"
	fi
	mapfile -t ids < <(get_ids)
	for i in "${ids[@]}"; do [ "$i" = "$ID" ] && { rm -f "$REC" "$ENTRY"; exit 0; }; done
	# the plugin definition may have been dropped while the id was off the panel
	xfconf-query -c xfce4-panel -p "/plugins/plugin-$ID" -n -t string -s genmon 2>/dev/null \
		|| [ "$(xfconf-query -c xfce4-panel -p "/plugins/plugin-$ID" 2>/dev/null)" = genmon ] \
		|| xfconf-query -c xfce4-panel -p "/plugins/plugin-$ID" -s genmon
	new=() placed=0
	has() { local x; for x in "${ids[@]}"; do [ "$x" = "$1" ] && return 0; done; return 1; }
	if [ -n "$after" ] && has "$after"; then
		for i in "${ids[@]}"; do new+=("$i"); [ "$i" = "$after" ] && new+=("$ID"); done; placed=1
	elif [ -n "$before" ] && has "$before"; then
		for i in "${ids[@]}"; do [ "$i" = "$before" ] && new+=("$ID"); new+=("$i"); done; placed=1
	fi
	[ "$placed" -eq 1 ] || new=("${ids[@]}" "$ID")
	set_ids "${new[@]}" || exit 1
	rm -f "$REC" "$ENTRY"
	update-desktop-database "$APPS" >/dev/null 2>&1 || true
	;;
refresh-entry) # rewrite the Whisker entry of an already hidden icon
	[ -r "$REC" ] || exit 1
	TITLE=$(sed -n 's/^title=//p' "$REC")
	write_entry
	;;
*)
	echo "Usage: $0 hide <id> <title> | show <id>" >&2
	exit 1
	;;
esac
