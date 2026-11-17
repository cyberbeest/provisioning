#!/bin/bash
# Root helper for the Firewall GUI (lib/cyberbeest_firewall_gui.py), run via
# pkexec -- see lib/com.cyberbeest.firewall.policy. Installed to
# /usr/local/lib/cyberbeest/ by 63b-firewall-gui.sh.
#
# Usage: cyberbeest-firewall-helper.sh set     (the whole list on stdin)
#
# stdin is one "proto port name" per line, the complete set of ports the user
# has opened on top of 63-firewall.sh's built-in ones. Nothing else is
# accepted: the caller is an unprivileged GUI, so every field is validated
# here and nothing from stdin ever reaches a shell or nft as anything but a
# checked proto/number/short-name.
#
# What it writes:
#   /etc/cyberbeest/firewall-extra-user.nft  accept rules; 63-firewall.sh's
#       nftables.conf pulls in firewall-extra*.nft inside the input chain
#   /etc/cyberbeest/firewall-user-ports      same list as "proto port name",
#       world-readable, for the GUI and the auto-lock tooltip
# The ruleset is syntax-checked before it is applied; on any failure the
# previous files are put back, so a bad list can never leave the machine
# with a broken or half-applied firewall.
set -euo pipefail
export LC_ALL=C PATH=/usr/sbin:/usr/bin:/sbin:/bin

DIR=/etc/cyberbeest
EXTRA="$DIR/firewall-extra-user.nft"
LIST="$DIR/firewall-user-ports"
CONF=/etc/nftables.conf
MAX_ENTRIES=64

[ "${1:-}" = set ] || { echo "usage: $0 set  (list on stdin)" >&2; exit 2; }
[ -f "$CONF" ] || { echo "firewall is not installed ($CONF missing)" >&2; exit 3; }

# An nftables.conf from before the include existed would silently ignore our
# rules file -- refuse rather than pretend ports were opened.
grep -q 'firewall-extra\*\.nft' "$CONF" \
	|| { echo "the firewall rules are out of date (re-run 63-firewall.sh)" >&2; exit 3; }

exec 9>/run/cyberbeest-firewall.lock
flock -w 20 9 || { echo "another firewall change is running" >&2; exit 4; }

declare -A seen=()
entries=()
while IFS= read -r line || [ -n "$line" ]; do
	[ -n "$line" ] || continue
	read -r proto port name <<< "$line"
	[[ "$proto" =~ ^(tcp|udp)$ ]] || { echo "bad protocol: $proto" >&2; exit 5; }
	[[ "$port" =~ ^[0-9]{1,5}$ ]] || { echo "bad port: $port" >&2; exit 5; }
	port=$((10#$port))
	{ [ "$port" -ge 1 ] && [ "$port" -le 65535 ]; } || { echo "port out of range: $port" >&2; exit 5; }
	[[ "$name" =~ ^[A-Za-z0-9\ ._+-]{0,32}$ ]] || { echo "bad name" >&2; exit 5; }
	[ -z "${seen[$proto:$port]+x}" ] || continue
	seen[$proto:$port]=1
	entries+=("$proto $port $name")
	[ "${#entries[@]}" -le "$MAX_ENTRIES" ] || { echo "too many entries" >&2; exit 5; }
done

install -d -m 755 "$DIR"
new_extra="$(mktemp "$DIR/.extra.XXXXXX")"
new_list="$(mktemp "$DIR/.list.XXXXXX")"
old_extra="$(mktemp "$DIR/.oldextra.XXXXXX")"
old_list="$(mktemp "$DIR/.oldlist.XXXXXX")"
trap 'rm -f "$new_extra" "$new_list" "$old_extra" "$old_list"' EXIT

had_extra=false; had_list=false
[ -f "$EXTRA" ] && { cp -p "$EXTRA" "$old_extra"; had_extra=true; }
[ -f "$LIST" ] && { cp -p "$LIST" "$old_list"; had_list=true; }

{
	echo "# Written by the Firewall tool (cyberbeest_firewall_gui.py) -- do not edit by hand."
	for e in "${entries[@]}"; do
		read -r proto port name <<< "$e"
		echo ""
		echo "		# ${name:-port $port}"
		echo "		$proto dport $port accept"
	done
} > "$new_extra"
for e in "${entries[@]}"; do echo "$e"; done > "$new_list"
chmod 644 "$new_extra" "$new_list"

restore() {
	if $had_extra; then cp -p "$old_extra" "$EXTRA"; else rm -f "$EXTRA"; fi
	if $had_list; then cp -p "$old_list" "$LIST"; else rm -f "$LIST"; fi
}

if [ "${#entries[@]}" -gt 0 ]; then
	mv -f "$new_extra" "$EXTRA"
else
	rm -f "$EXTRA"
fi
mv -f "$new_list" "$LIST"

if ! nft -c -f "$CONF"; then
	echo "ruleset check failed; keeping the previous rules" >&2
	restore
	exit 6
fi

# Reload, not stop+start: nftables.service's ExecStop is a global
# "flush ruleset" that would take libvirt's own tables with it (see
# 63-firewall.sh).
live_ok() {
	local out e proto port name
	out="$(nft list chain inet cyberbeest_filter input 2>/dev/null)" || return 1
	for e in "${entries[@]}"; do
		read -r proto port name <<< "$e"
		grep -q "$proto dport $port accept" <<< "$out" || return 1
	done
}

if ! systemctl reload-or-restart nftables.service || ! live_ok; then
	echo "applying the ruleset failed; going back to the previous rules" >&2
	restore
	systemctl reload-or-restart nftables.service || true
	exit 7
fi
echo "ok: ${#entries[@]} port(s) opened"
