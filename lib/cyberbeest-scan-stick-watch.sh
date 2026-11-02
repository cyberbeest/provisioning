#!/bin/bash
# Pops up an offer to scan this computer from the Cyberbeest boot stick the
# moment one is plugged in. Runs as a systemd user service (installed by
# 59a-scan-stick-boot.sh). Accepting hands over to
# cyberbeest-scan-stick-helper.sh (root, via pkexec), which verifies the stick
# and reboots into its "Scan this computer" entry.
#
# The stick is recognised by its filesystem label ("Cyberbeest Combined", the
# volume id combine-live-and-installer.sh gives it). udev's ID_FS_LABEL has
# spaces turned into underscores, so the comparison is done in that form.
# Label alone is not trusted: the helper checks a signed manifest before booting anything.
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$SELF_DIR/i18n.sh"

LABEL="Cyberbeest Combined"
HELPER="${CB_SCAN_STICK_HELPER:-/usr/local/lib/cyberbeest/cyberbeest-scan-stick-helper.sh}"
export DISPLAY="${DISPLAY:-:0}"

# The question dialog's pid, per device, so unplugging the stick can close it
# (offer runs in a background subshell the main loop can't see into).
PID_DIR="${XDG_RUNTIME_DIR:-/tmp}/cyberbeest-scan-stick-watch"
mkdir -p "$PID_DIR"

# zenity's --text is Pango markup: escape what the translated text may contain.
markup_escape() { local s="$1"; s="${s//&/&amp;}"; s="${s//</&lt;}"; echo "${s//>/&gt;}"; }

offer() {
	local dev="$1" ro text pidf="$PID_DIR/${1##*/}.pid"
	ro="$(cat "/sys/block/${dev#/dev/}/ro" 2>/dev/null || echo 0)"
	text="$(markup_escape "$(t scan_stick.question)")"
	# A read-only stick is what makes "the stick stays clean" true; say so (in
	# bold) if the write-protect switch is off, but don't block -- the scan
	# still works.
	[ "$ro" = 1 ] || text="$text

<b>$(markup_escape "$(t scan_stick.unprotected)")</b>"

	zenity --question --title="$(t scan_stick.title)" --width=420 \
		--ok-label="$(t scan_stick.ok)" --cancel-label="$(t scan_stick.cancel)" \
		--text="$text" &
	echo $! >"$pidf"
	wait $!; local qrc=$?
	rm -f "$pidf"
	[ "$qrc" -eq 0 ] || return 0   # cancelled, or closed because the stick was unplugged

	local out rc
	zenity --progress --pulsate --no-cancel --auto-close --title="$(t scan_stick.title)" \
		--text="$(t scan_stick.checking)" </dev/zero >/dev/null 2>&1 &
	local zpid=$!
	out="$(pkexec "$HELPER" "$dev" 2>&1)"; rc=$?
	kill "$zpid" 2>/dev/null
	if [ "$rc" -ne 0 ]; then
		zenity --error --title="$(t scan_stick.title)" --width=420 \
			--text="$(t scan_stick.failed)

$(printf '%s\n' "$out" | grep '^ERROR:' | tail -n1 | sed 's/^ERROR: //')"
	fi
}

declare -A SEEN=()
declare -A P=()
flush() {
	local dev="${P[DEVNAME]:-}" action="${P[ACTION]:-}"
	if [ -n "$dev" ] && [ "$action" = remove ]; then
		unset "SEEN[$dev]"
		local pidf="$PID_DIR/${dev##*/}.pid"
		[ -f "$pidf" ] && kill "$(cat "$pidf")" 2>/dev/null
	elif [ -n "$dev" ] && [ "${P[DEVTYPE]:-}" = disk ] && [ "${P[ID_FS_TYPE]:-}" = iso9660 ] \
		&& [ "${P[ID_FS_LABEL]:-}" = "${LABEL// /_}" ] && [ -z "${SEEN[$dev]:-}" ]; then
		SEEN[$dev]=1
		offer "$dev" &
	fi
	P=()
}

udevadm monitor --udev --property --subsystem-match=block |
while IFS= read -r line; do
	if [ -z "$line" ]; then
		flush
	elif [[ "$line" == *=* ]] && [[ "$line" != UDEV* ]]; then
		P["${line%%=*}"]="${line#*=}"
	fi
done
