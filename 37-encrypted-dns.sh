#!/bin/bash
# Installs dnscrypt-proxy as a local encrypted DNS stub resolver, so plain DNS
# queries aren't sent in cleartext to whatever router/network is upstream --
# including a hostile/compromised tether (phone hotspot, hotel wifi, etc.).
# Queries go to 127.0.2.1 (dnscrypt-proxy's socket-activated address), which
# forwards them encrypted (DNSCrypt/DoH) to Cloudflare.
#
# Composes correctly with the WireGuard VPN toggle's own DNS-leak protection
# (29-wireguard-vpn-toggle.sh): wg-quick registers its DNS with openresolv at
# an explicit top-priority metric when a profile connects, which still wins
# over this. Order: VPN DNS (when connected) > this local encrypted resolver
# > plain router DNS.
#
# Root cause notes from bring-up (see cyberbeest_encrypted_dns_dnscrypt_proxy
# memory for the full story): the shipped config's listen_addresses MUST be
# left empty ([]) -- it says so in its own comment -- so dnscrypt-proxy relies
# purely on the systemd socket-activation fd instead of trying to self-bind
# port 53, which fails ("permission denied") since the daemon runs as the
# unprivileged _dnscrypt-proxy user. Also: dnscrypt-proxy.socket has
# "Wants=dnscrypt-proxy-resolvconf.service", so starting the socket registers
# 127.0.2.1 into /etc/resolv.conf immediately, regardless of whether the
# backing service is actually up -- so this script verifies end-to-end
# resolution right after starting, and reverts itself if it doesn't work.
#
# Idempotent: safe to re-run.
set -u
LOG="${BASH_SOURCE%.sh}.log"
exec > "$LOG" 2>&1

echo "=== $(date) starting 37-encrypted-dns.sh ==="

revert() {
    echo "--- REVERTING: disabling dnscrypt-proxy, restoring plain DNS ---"
    systemctl disable --now dnscrypt-proxy-resolvconf.service dnscrypt-proxy.socket dnscrypt-proxy.service 2>&1
    cat /etc/resolv.conf
    getent hosts anthropic.com || echo "WARNING: still not resolving after revert, check network itself"
}

echo "--- installing dnscrypt-proxy ---"
apt-get update
apt-get install -y dnscrypt-proxy

echo "--- stopping everything first (idempotent re-run safety) ---"
systemctl stop dnscrypt-proxy-resolvconf.service dnscrypt-proxy.service dnscrypt-proxy.socket 2>&1
systemctl reset-failed dnscrypt-proxy.socket dnscrypt-proxy.service 2>&1

CONF=/etc/dnscrypt-proxy/dnscrypt-proxy.toml
echo "--- configuring $CONF ---"
sed -i "s/^listen_addresses.*/listen_addresses = []/" "$CONF"
sed -i "s/^require_nolog.*/require_nolog = true/" "$CONF"
sed -i "s/^require_nofilter.*/require_nofilter = true/" "$CONF"
sed -i "s/^require_dnssec.*/require_dnssec = true/" "$CONF"
grep -n "^listen_addresses\|^require_nolog\|^require_nofilter\|^require_dnssec" "$CONF"

echo "--- starting socket (also triggers the package's resolvconf registration via Wants=) ---"
systemctl start dnscrypt-proxy.socket
sleep 1

echo "--- triggering the service with an actual query ---"
if command -v dig >/dev/null 2>&1; then
    dig @127.0.2.1 anthropic.com +short +time=3 +tries=1
fi
sleep 1

echo "--- checking service is alive ---"
if ! systemctl is-active --quiet dnscrypt-proxy.service; then
    echo "FAIL: dnscrypt-proxy.service is not active:"
    systemctl status dnscrypt-proxy.service --no-pager -l
    revert
    exit 1
fi

echo "--- final end-to-end resolution check ---"
cat /etc/resolv.conf
if ! getent hosts anthropic.com; then
    echo "FAIL: end-to-end resolution through dnscrypt-proxy did not work"
    revert
    exit 1
fi

echo "--- enabling for persistence across reboots ---"
systemctl enable dnscrypt-proxy.socket dnscrypt-proxy.service dnscrypt-proxy-resolvconf.service 2>&1

# "fritz.box" is a public domain AVM (the FritzBox maker) actually owns, and
# encrypted-DNS resolvers like Cloudflare answer it with AVM's real public
# server rather than the local router. Plain DNS to the router itself doesn't
# have this problem: FritzBox routers specially intercept "fritz.box" queries
# and answer with themselves. Forward that domain in plaintext directly to
# the router's factory-default LAN IP so local admin access keeps working.
RULES=/etc/dnscrypt-proxy/forwarding-rules.txt
echo "--- adding fritz.box forwarding rule (local router access) ---"
cat > "$RULES" <<'EOF'
fritz.box 192.168.178.1
*.fritz.box 192.168.178.1
EOF
CONF=/etc/dnscrypt-proxy/dnscrypt-proxy.toml
# Must sit at the top level (alongside listen_addresses/server_names), not
# appended at EOF -- appending lands inside the trailing [sources.*] table
# and dnscrypt-proxy refuses to start ("Unsupported key in configuration
# file"), breaking all DNS. Insert right after server_names instead.
sed -i "/^forwarding_rules/d" "$CONF"
sed -i "/^server_names/a forwarding_rules = '$RULES'" "$CONF"
systemctl restart dnscrypt-proxy.service
sleep 1
getent hosts anthropic.com || echo "WARNING: general DNS resolution broken after adding forwarding rule"

# "Disable Encrypted DNS" troubleshooting toggle (Whisker entry + panel
# icon): forwarding_rules can't cover every router vendor's own version of
# the fritz.box collision above, so this is the escape hatch. Deliberately
# does NOT disable the systemd units -- see lib/setup_dot_toggle.py -- so a
# reboot always brings encrypted DNS back even if left off.
echo "--- installing dot-toggle sudoers rule ---"
DOT_SUDOERS=/etc/sudoers.d/dot-toggle
TMP_FILE="$(mktemp)"
cat > "$TMP_FILE" <<'EOF'
cyberbeest ALL=(root) NOPASSWD: /usr/bin/systemctl stop dnscrypt-proxy-resolvconf.service dnscrypt-proxy.socket dnscrypt-proxy.service
cyberbeest ALL=(root) NOPASSWD: /usr/bin/systemctl start dnscrypt-proxy.socket
EOF
if visudo -c -f "$TMP_FILE"; then
    install -m 0440 -o root -g root "$TMP_FILE" "$DOT_SUDOERS"
else
    echo "FAIL: visudo syntax check failed for dot-toggle sudoers rule"
fi
rm -f "$TMP_FILE"

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
DIR="$(cd "$(dirname "$BASH_SOURCE")" && pwd)"

echo "--- installing DoT toggle scripts for $TARGET_USER ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
    "$DIR/lib/setup_dot_toggle.py" "$TARGET_HOME/.local/bin/setup_dot_toggle.py"
runuser -u "$TARGET_USER" -- python3 "$TARGET_HOME/.local/bin/setup_dot_toggle.py"

echo "=== $(date) SUCCESS: dnscrypt-proxy is live, DNS resolution confirmed working through it ==="
