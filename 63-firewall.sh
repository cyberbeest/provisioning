#!/bin/bash
# Installs a default-deny-inbound nftables firewall. Before this script,
# nothing filtered inbound traffic at all: nftables/iptables were only
# present as incidental dependencies (pulled in by libvirt-daemon-system),
# with their systemd units disabled and /etc/nftables.conf left at the
# stock Debian template (empty chains, implicit accept). See the
# conversation this was written from: a "security laptop" shipping with
# zero packet filtering was the actual gap, not any one exposed port.
#
# Uses its own uniquely-named table (cyberbeest_filter), not the generic
# "filter" name the stock template uses, and "destroy table ...; table
# ... { ... }" rather than "flush ruleset" -- this machine also ships
# QEMU/KVM for the Sandbox VM feature (56-cyberbeest-sandbox-vm-kvm.sh),
# and libvirt installs its own nftables tables for VM bridge NAT/forwarding
# whenever a VM network is started. A global "flush ruleset" (the pattern
# the stock template and most nftables.conf tutorials use) would nuke
# those right along with everything else the moment this ruleset gets
# reloaded while a VM happens to be running. Scoping every operation to
# our own table name means this can never touch libvirt's rules, in either
# direction, regardless of boot/VM-start ordering. "destroy" (added in
# nftables 1.0) is a delete that doesn't error if the table doesn't exist
# yet, which is what makes re-running this script safe: a plain "flush
# table" wouldn't be enough here, since it only empties a chain's rules,
# not the chain's hook/priority/policy binding -- redeclaring an identical
# base-chain hook spec on top of one that already exists is a hard error
# ("File exists"), which is exactly why the stock template resorts to a
# global flush instead. Destroying and fully redeclaring our own table
# sidesteps that without needing the global hammer.
#
# Only the "input" chain is touched (policy drop) -- "forward"/"output"
# are left alone entirely, so this can't interact with libvirt's VM
# forwarding/NAT or restrict anything this machine itself initiates
# (updates, VPN, browsing, etc).
#
# What's actually let in, and why:
#   - loopback, and any reply traffic to a connection *we* opened
#     (ct state established,related) -- the two rules that make a
#     default-deny firewall usable at all.
#   - the ICMP/ICMPv6 types RFC 4890 calls out as required for basic IPv6
#     operation (neighbor discovery, path MTU discovery, MLD) plus ping,
#     which is otherwise silently and confusingly dropped.
#   - tcp/22 (SSH) -- see 99-remove-openssh-server.sh: openssh-server is
#     purged on every shipped machine, which makes this a no-op there, but
#     that same script's own comment describes sshd sometimes getting
#     manually re-enabled on a live unit to debug something. This rule
#     means that debugging path still works instead of quietly breaking
#     the moment this firewall lands.
#   - udp/5353 (mDNS) -- see 62-lan-printer-discovery.sh: avahi-daemon is
#     masked/stopped by default, so this is also a no-op most of the time,
#     but becomes necessary the moment someone uses that toggle's "Enable
#     LAN Printer Discovery" launcher -- without this rule, turning
#     avahi-daemon on would still leave it unreachable from the network,
#     defeating the one thing it's for. (Its two "legacy unicast"
#     companion ports on random high ports aren't opened -- ordinary mDNS
#     printer/scanner discovery doesn't need them.)
#
# Everything else inbound is silently dropped.
#
# Also writes /etc/cyberbeest/firewall-allowed-ports, a world-readable
# "proto port name" listing generated from the exact same ALLOWED_PORTS
# array the rules above come from. panel-status-genmon.sh (the auto-lock
# tooltip) reads it to only show a listening port as network-exposed if
# the firewall actually lets it through -- it can't query the live nft
# ruleset itself since that needs root, and hand-copying this list into a
# second script would just be one more thing to forget to update.
#
# Run this in an isolated VM first, not straight on real hardware --
# firewall misconfiguration is exactly the class of bug that's supposed to
# be debugged in a throwaway VM, never live (same reasoning as the
# network-kill-switch and suspend/shutdown testing rules already followed
# elsewhere in provisioning). If this machine is ever reached only over
# SSH, double-check the tcp/22 rule reaches this exact host before
# trusting this on it.
#
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/63-firewall.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) starting 63-firewall.sh ==="

echo "--- ensuring nftables is installed (idempotent) ---"
apt-get -o DPkg::Lock::Timeout=60 install -y nftables

# Single source of truth for "which ports does this firewall actually let
# in" -- both the nft accept rules below and the world-readable companion
# file at ALLOWED_PORTS_FILE are generated from this array, so the
# auto-lock tooltip (panel-status-genmon.sh, which can't read the live
# nftables ruleset itself without root) can stay in sync with this
# ruleset without a second, hand-maintained copy of the same list to
# forget to update.
# Format per entry: "proto|port|name|why".
ALLOWED_PORTS=(
	"tcp|22|SSH|no-op on shipped machines (openssh-server purged by 99-remove-openssh-server.sh); keeps working if sshd is ever manually re-enabled to debug a live unit (see that script's own comment)"
	"udp|5353|mDNS|no-op while avahi-daemon is masked/stopped (its default state, see 62-lan-printer-discovery.sh); needed the moment Enable LAN Printer Discovery is used. Its two legacy-unicast companion ports on random high ports aren't opened -- ordinary mDNS printer/scanner discovery doesn't need them"
)

CONF=/etc/nftables.conf
echo "--- writing $CONF ---"
cat > "$CONF" <<'EOF'
#!/usr/sbin/nft -f

# Cyberbeest default-deny-inbound firewall. Scoped to its own table so it
# never touches libvirt's own nftables tables for VM networking -- see
# 63-firewall.sh's comment for why a global "flush ruleset" isn't used
# here.

destroy table inet cyberbeest_filter

table inet cyberbeest_filter {
	chain input {
		type filter hook input priority filter; policy drop;

		# Loopback and replies to connections we opened ourselves --
		# without these two, nothing on this host would work at all.
		iif "lo" accept
		ct state established,related accept
		ct state invalid drop

		# RFC 4890-minimum ICMPv6 (neighbor discovery, path MTU
		# discovery, multicast listener discovery) -- IPv6 silently
		# breaks without these. Plus ICMPv4 ping/unreachable/ttl-exceeded.
		icmpv6 type { destination-unreachable, packet-too-big, time-exceeded, parameter-problem, mld-listener-query, mld-listener-report, mld-listener-done, nd-router-solicit, nd-router-advert, nd-neighbor-solicit, nd-neighbor-advert, nd-redirect } accept
		icmp type { echo-request, destination-unreachable, time-exceeded, parameter-problem } accept
EOF

for entry in "${ALLOWED_PORTS[@]}"; do
	IFS='|' read -r proto port name why <<< "$entry"
	{
		echo ""
		echo "		# $name -- $why."
		echo "		$proto dport $port accept"
	} >> "$CONF"
done

cat >> "$CONF" <<'EOF'
	}
}
EOF
chmod 755 "$CONF"

ALLOWED_PORTS_FILE=/etc/cyberbeest/firewall-allowed-ports
echo "--- writing $ALLOWED_PORTS_FILE (read by the auto-lock tooltip) ---"
: > "$ALLOWED_PORTS_FILE"
for entry in "${ALLOWED_PORTS[@]}"; do
	IFS='|' read -r proto port name why <<< "$entry"
	echo "$proto $port $name" >> "$ALLOWED_PORTS_FILE"
done
chmod 644 "$ALLOWED_PORTS_FILE"

echo "--- checking syntax ---"
if ! nft -c -f "$CONF"; then
    echo "FAIL: nft syntax/semantic check failed for $CONF" >&2
    exit 1
fi

echo "--- enabling nftables.service for boot persistence ---"
systemctl enable nftables.service

echo "--- applying ruleset now (reload, not stop+start -- see 63-firewall.sh's ExecStop note) ---"
# nftables.service's own ExecStop is "nft flush ruleset" (global, not
# scoped) -- ExecReload is just "nft -f /etc/nftables.conf" again, same as
# ExecStart, so ask for a reload specifically rather than a restart, in
# case this ever re-runs while nftables.service is already active with a
# VM's own tables sitting alongside ours.
systemctl reload-or-restart nftables.service

echo "--- verifying our table is actually loaded ---"
if ! nft list table inet cyberbeest_filter >/dev/null 2>&1; then
    echo "FAIL: cyberbeest_filter table not present after apply" >&2
    exit 1
fi

echo "=== $(date) SUCCESS: default-deny-inbound firewall is live ==="
