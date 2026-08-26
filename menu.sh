#!/bin/bash
# Interactive whiptail front-end: lets the installer deselect NN-*.sh
# scripts that don't apply to this machine (e.g. skip bluetooth tethering on
# a VM with no Bluetooth), then runs the selected ones in numeric order.
#
# Each script is expected to run as root itself (see README.md), so this
# invokes them with sudo directly -- there's a human at the keyboard during
# an install, unlike the RUNME/claude-sudo-helper.sh convention in ../CLAUDE.md
# which exists for Claude to request sudo without holding it itself.
#
# Some scripts depend on earlier ones (see the "Depends on" comment at the
# top of each NN-*.sh) -- deselecting a dependency without also deselecting
# what depends on it will make the later script fail.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if ! command -v whiptail >/dev/null 2>&1; then
	echo "Installing whiptail (needed for the selection menu)..."
	sudo apt-get -o DPkg::Lock::Timeout=60 update
	sudo apt-get -o DPkg::Lock::Timeout=60 install -y whiptail
fi

scripts=()
# The optional trailing letter (e.g. 00a-) lets a script slot in right after
# an existing NN- step without renumbering everything after it -- see
# run-gui.py's list_scripts() for the sort-order reasoning.
for f in [0-9][0-9]-*.sh [0-9][0-9][a-z]-*.sh; do
	[ -e "$f" ] && scripts+=("$f")
done
# LC_ALL=C: a locale-aware sort here (e.g. en_US.UTF-8) treats '-' as
# ignorable punctuation, so "00a-touchpad..." sorts *before*
# "00-locale...", defeating the whole point of the 00a- naming trick. Plain
# byte order (same as Python's sorted() in run-gui.py) gets it right.
mapfile -t scripts < <(printf '%s\n' "${scripts[@]}" | LC_ALL=C sort)

if [ "${#scripts[@]}" -eq 0 ]; then
	echo "No NN-*.sh provisioning scripts found in $DIR" >&2
	exit 1
fi

# Build the whiptail checklist: each item is "tag" "description" "status",
# with all items ON by default. Description comes from the first comment
# line after the shebang in each script.
checklist_args=()
for f in "${scripts[@]}"; do
	desc="$(sed -n '2p' "$f" | sed 's/^# *//')"
	checklist_args+=("$f" "$desc" "ON")
done

selected_raw="$(whiptail --title "Cyberbeest provisioning" \
	--checklist "Choose which provisioning scripts to run (space to toggle, enter to confirm):" \
	24 100 "${#scripts[@]}" \
	"${checklist_args[@]}" \
	3>&1 1>&2 2>&3)" || {
	echo "Cancelled, nothing run."
	exit 0
}

# whiptail returns tags quoted and space-separated, e.g. "01-foo.sh" "02-bar.sh".
# Parse with xargs (which understands shell-style quoting) instead of eval,
# so a stray quote/backtick/$( ) in a script's description line -- which
# ends up as the tag text whiptail hands back -- can't be interpreted as code.
selected=()
while IFS= read -r -d '' tag; do
	selected+=("$tag")
done < <(xargs printf '%s\0' <<<"$selected_raw")

if [ "${#selected[@]}" -eq 0 ]; then
	echo "Nothing selected, nothing run."
	exit 0
fi

echo "Will run, in order:"
printf '  %s\n' "${selected[@]}"
read -rp "Proceed? [Y/n] " confirm
case "$confirm" in
	[nN]*) echo "Cancelled, nothing run."; exit 0 ;;
esac

for script in "${selected[@]}"; do
	echo "=== running $script ==="
	if sudo bash "$script"; then
		echo "=== $script done (log: ${script%.sh}.log) ==="
	else
		echo "=== $script FAILED (log: ${script%.sh}.log) ===" >&2
		echo "Stopping here since later scripts may depend on this one." >&2
		exit 1
	fi
done

echo "=== all selected provisioning scripts completed ==="

# menu.sh itself normally runs as the invoking user (it sudos per-script, see
# above), so this reload usually just works. But if someone runs the whole
# thing via `sudo ./menu.sh`, this runs as root and can't reach the logged-in
# user's D-Bus session bus directly -- drop back to that user for the reload,
# reading the bus address off their actual running panel process (most
# reliable) rather than assuming the standard /run/user/<uid>/bus path.
if command -v xfce4-panel >/dev/null 2>&1; then
	echo "Reloading xfce4-panel to pick up new/changed desktop entries..."
	if [ "$(id -u)" -eq 0 ] && [ -n "${SUDO_USER:-}" ]; then
		TARGET_UID="$(id -u "$SUDO_USER")"
		PANEL_PID="$(pgrep -u "$SUDO_USER" -x xfce4-panel | head -1)" || true
		DBUS_ADDR=""
		if [ -n "$PANEL_PID" ]; then
			# cat (not `< file`) so a PID that vanishes between pgrep and here
			# just yields empty output instead of a fatal shell redirection error.
			DBUS_ADDR="$(cat "/proc/$PANEL_PID/environ" 2>/dev/null | tr '\0' '\n' | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')" || true
		fi
		DBUS_ADDR="${DBUS_ADDR:-unix:path=/run/user/$TARGET_UID/bus}"
		su - "$SUDO_USER" -c "DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$DBUS_ADDR' xfce4-panel -r" || true
	else
		xfce4-panel -r || true
	fi
fi
