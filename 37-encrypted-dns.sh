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

echo "=== $(date) SUCCESS: dnscrypt-proxy is live, DNS resolution confirmed working through it ==="
