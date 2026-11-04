#!/bin/bash
# IPv6 privacy addresses: outgoing connections use a temporary address that is
# replaced about daily, so a site cannot recognise this machine by one fixed
# IPv6 address across visits (and across networks sharing the prefix). The
# stable address stays for incoming connections. Windows, macOS, iOS and
# Android do this by default; the Linux kernel and plain Debian do not.
#
# Two drop-ins: a sysctl one (kernel default, covers interfaces NetworkManager
# does not manage) and a NetworkManager one (NM sets the value per connection
# and would otherwise fall back to its own default). NetworkManager connections
# that already exist have ip6-privacy "default" (-1) and follow the drop-in.
# No live reconnect: the setting reaches running interfaces through
# the sysctl write below and the router's next advertisement, and everything
# else on the next (re)connect.
# Must be run as root. Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/63a-ipv6-privacy.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : enabling IPv6 privacy addresses ==="

install -d -m 755 /etc/sysctl.d
cat > /etc/sysctl.d/60-cyberbeest-ipv6-privacy.conf <<'EOC'
# Prefer a temporary (regularly replaced) IPv6 address for outgoing connections.
net.ipv6.conf.all.use_tempaddr = 2
net.ipv6.conf.default.use_tempaddr = 2
EOC

if [ -d /etc/NetworkManager ]; then
	install -d -m 755 /etc/NetworkManager/conf.d
	cat > /etc/NetworkManager/conf.d/60-cyberbeest-ipv6-privacy.conf <<'EOC'
[connection]
ipv6.ip6-privacy=2
EOC
	nmcli general reload conf 2>/dev/null || systemctl reload NetworkManager || true
fi

echo "--- Applying to the running system ---"
sysctl -q -p /etc/sysctl.d/60-cyberbeest-ipv6-privacy.conf
for f in /proc/sys/net/ipv6/conf/*/use_tempaddr; do
	case "$f" in */lo/*) continue ;; esac
	echo 2 > "$f" || true
done

sysctl net.ipv6.conf.all.use_tempaddr net.ipv6.conf.default.use_tempaddr
echo "=== done ==="
