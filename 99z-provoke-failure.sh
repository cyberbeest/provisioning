#!/bin/bash
# Test helper for the "Send Report..." button in run-gui: always fails.
#
# Copy it into the provisioning folder, select it in run-gui and run it:
#     cp experimental/99z-provoke-failure.sh .
# The failure adds a "Send Report..." row to the things-to-do pane. The
# report window should show the details printed below replaced by
# <host>, <user>, <ipv4>, <mac> and so on (the shipped defaults "cyberbeest"
# for user and host are left alone on purpose).
#
# Remove it again afterwards, with its log:
#     rm 99z-provoke-failure.sh 99z-provoke-failure.log
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/99z-provoke-failure.log"
exec > >(tee -a "$LOG") 2>&1

USER_NAME="${SUDO_USER:-$(id -un)}"
echo "=== $(date) : provoking a test failure ==="
echo "Details the report window should replace:"
echo "  home folder: $(getent passwd "$USER_NAME" | cut -d: -f6)/.config"
echo "  user:        $USER_NAME"
echo "  hostname:    $(hostname)"
echo "  IPv4:        $(ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1 | head -1)"
echo "  IPv6:        $(ip -6 -o addr show scope global | awk '{print $4}' | cut -d/ -f1 | head -1)"
echo "  MAC:         $(ip -o link | awk '{for (i = 1; i < NF; i++) if ($i == "link/ether") {print $(i+1); exit}}')"
echo "  email:       someone@example.org"
echo "This script always fails, on purpose."
exit 3
