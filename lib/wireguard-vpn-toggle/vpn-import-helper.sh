#!/bin/bash
# Privileged half of VPN profile import: copies a user-picked WireGuard
# .conf into /etc/wireguard/<name>.conf as root:root mode 600 (so the
# private key inside it is never readable by the cyberbeest user, same as
# wg-quick expects), and injects a standard fwmark-based kill switch into
# the [Interface] section if the config doesn't already define its own
# PostUp/PreDown (many providers, e.g. IVPN's manual configs, already
# ship one -- don't double up).
#
# Usage: vpn-import-helper.sh <src-file> <profile-name>
# Invoked via the scoped sudoers rule in /etc/sudoers.d/vpn-toggle, called
# by ~/.local/bin/vpn-import.sh (the unprivileged zenity-driven half).
set -euo pipefail

SRC="${1:-}"
NAME="${2:-}"

[[ "$NAME" =~ ^[a-zA-Z0-9_-]{1,32}$ ]] || { echo "Invalid profile name: $NAME" >&2; exit 1; }

# Defensive scoping: only ever copy from inside the invoking (real, pre-sudo)
# user's home directory. The picked file is already something that user's
# own session could read, so this isn't a privilege boundary -- it just
# stops this NOPASSWD helper from being repurposed as a generic root file
# copier for arbitrary source paths.
REAL_USER="${SUDO_USER:-cyberbeest}"
REAL_HOME="$(getent passwd "$REAL_USER" | cut -d: -f6)"
SRC_REAL="$(readlink -f -- "$SRC" 2>/dev/null || true)"
[ -n "$SRC_REAL" ] && [ -f "$SRC_REAL" ] || { echo "Source file not found: $SRC" >&2; exit 1; }
case "$SRC_REAL" in
    "$REAL_HOME"/*) ;;
    *) echo "Source file must be under $REAL_HOME" >&2; exit 1 ;;
esac

install -d -m 700 -o root -g root /etc/wireguard
DEST="/etc/wireguard/${NAME}.conf"
install -m 600 -o root -g root "$SRC_REAL" "$DEST"

if grep -q '^\[Interface\]' "$DEST" && ! grep -qE '^\s*PostUp\s*=' "$DEST"; then
    # Standard fwmark kill switch: reject any outbound traffic that isn't
    # going out the tunnel interface itself, isn't destined for a local/
    # LAN address, and isn't tagged with the fwmark wg-quick assigns for
    # its own routing table -- so the handshake/DHCP/local traffic that
    # needs to bypass the tunnel still works, everything else is blocked
    # if the tunnel ever drops. Applies to both IPv4 and IPv6.
    # Each hook is written defensively (-C/-I guard on the way up, "|| true"
    # on the way down, ip6tables wrapped in a binary check): wg-quick aborts
    # its whole up/down sequence the instant any single hook line exits
    # non-zero, and on a box with IPv6 disabled a bare `ip6tables -I` can
    # fail silently, which then makes the matching `-D` on teardown fail
    # too (deleting a rule that was never inserted) -- aborting `wg-quick
    # down` partway through and leaving the systemd unit stuck in `failed`
    # with the interface gone but no clean confirmation, or worse, later
    # hooks (like the IPv4 rule removal) skipped entirely. Tunnel-up should
    # fail if the IPv4 kill switch can't apply (fail closed); tunnel-down
    # must always succeed cleanly regardless (never trap the user in an
    # ambiguous state after they've asked to disconnect).
    tmp="$(mktemp)"
    awk '
        /^\[Interface\]/ && !done {
            print
            print "PostUp = iptables -C OUTPUT ! -o %i -m mark ! --mark $(wg show %i fwmark) -m addrtype ! --dst-type LOCAL -j REJECT 2>/dev/null || iptables -I OUTPUT ! -o %i -m mark ! --mark $(wg show %i fwmark) -m addrtype ! --dst-type LOCAL -j REJECT"
            print "PostUp = command -v ip6tables >/dev/null 2>&1 && (ip6tables -C OUTPUT ! -o %i -m mark ! --mark $(wg show %i fwmark) -m addrtype ! --dst-type LOCAL -j REJECT 2>/dev/null || ip6tables -I OUTPUT ! -o %i -m mark ! --mark $(wg show %i fwmark) -m addrtype ! --dst-type LOCAL -j REJECT) || true"
            print "PreDown = iptables -D OUTPUT ! -o %i -m mark ! --mark $(wg show %i fwmark) -m addrtype ! --dst-type LOCAL -j REJECT || true"
            print "PreDown = command -v ip6tables >/dev/null 2>&1 && ip6tables -D OUTPUT ! -o %i -m mark ! --mark $(wg show %i fwmark) -m addrtype ! --dst-type LOCAL -j REJECT 2>/dev/null || true"
            done=1
            next
        }
        { print }
    ' "$DEST" > "$tmp"
    install -m 600 -o root -g root "$tmp" "$DEST"
    rm -f "$tmp"
fi

echo "imported"
