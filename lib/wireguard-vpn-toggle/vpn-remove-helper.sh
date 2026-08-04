#!/bin/bash
# Privileged half of VPN profile removal: stops the tunnel if active and
# deletes its config from /etc/wireguard. Invoked via the scoped sudoers
# rule in /etc/sudoers.d/vpn-toggle.
#
# Usage: vpn-remove-helper.sh <profile-name>
set -euo pipefail

NAME="${1:-}"
[[ "$NAME" =~ ^[a-zA-Z0-9_-]{1,32}$ ]] || { echo "Invalid profile name: $NAME" >&2; exit 1; }

systemctl stop "wg-quick@${NAME}" >/dev/null 2>&1 || true
rm -f "/etc/wireguard/${NAME}.conf"
echo "removed"
