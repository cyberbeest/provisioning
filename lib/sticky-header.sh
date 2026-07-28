# Sticky 2-line header (current script + how many are left) pinned to the
# top of the terminal while each script's own output scrolls normally
# underneath it, via a DECSTBM scroll-region escape sequence -- not an
# alt-screen app, so normal terminal scrollback still works afterward.
# Purely cosmetic: a no-op when stdout isn't a real terminal (headless run,
# or output piped/redirected to a file), so run-all.sh/run-changed.sh's own
# "=== running $script ===" lines are what shows up there instead.
#
# Usage: source this, then sticky_header_start, sticky_header_set NAME
# REMAINING per script, sticky_header_stop when done (trap it on EXIT so a
# Ctrl-C doesn't leave the terminal's scroll region stuck).

_STICKY_ACTIVE=0

sticky_header_start() {
	{ [ -t 1 ] && command -v tput >/dev/null 2>&1; } || return 0
	_STICKY_ACTIVE=1
	local lines
	lines=$(tput lines)
	tput civis 2>/dev/null                   # hide cursor
	printf '\e[3;%dr' "$lines"                # reserve top 2 lines as header
	printf '\e[3;1H'                          # park cursor at top of scroll region
}

sticky_header_set() {
	local name="$1" remaining="$2"
	if [ "$_STICKY_ACTIVE" != 1 ]; then
		echo "=== running $name ($remaining more to go) ==="
		return 0
	fi
	local cols
	cols=$(tput cols)
	tput sc                                   # save cursor position
	tput cup 0 0; tput el
	printf '%s▶ %s%s' "$(tput bold; tput setaf 6)" "$name" "$(tput sgr0)"
	if [ "$remaining" -gt 0 ]; then
		printf '  %s(+%s more)%s' "$(tput setaf 8)" "$remaining" "$(tput sgr0)"
	fi
	tput cup 1 0; tput el
	printf '%s%s%s' "$(tput setaf 8)" "$(printf '%*s' "$cols" '' | tr ' ' '-')" "$(tput sgr0)"
	tput rc                                   # restore cursor position
}

sticky_header_stop() {
	[ "$_STICKY_ACTIVE" = 1 ] || return 0
	printf '\e[r'                             # reset scroll region to full screen
	# Resetting the scroll region homes the cursor back to row 1 as a side
	# effect on most terminals, which would otherwise leave the next shell
	# prompt sitting where the header used to be instead of at the bottom.
	tput cup "$(( $(tput lines) - 1 ))" 0
	tput cnorm 2>/dev/null                    # show cursor
	printf '\n'
	_STICKY_ACTIVE=0
}
