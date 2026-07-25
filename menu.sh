#!/bin/bash
# Interactive front-end for run-all.sh: lets the installer deselect NN-*.sh
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
	sudo apt-get update
	sudo apt-get install -y whiptail
fi

scripts=()
for f in [0-9][0-9]-*.sh; do
	[ -e "$f" ] && scripts+=("$f")
done

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

# whiptail returns tags quoted and space-separated, e.g. "01-foo.sh" "02-bar.sh"
selected=()
eval "selected=($selected_raw)"

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

if command -v xfce4-panel >/dev/null 2>&1; then
	echo "Reloading xfce4-panel to pick up new/changed desktop entries..."
	xfce4-panel -r || true
fi
