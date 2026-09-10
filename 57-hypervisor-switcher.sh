#!/bin/bash
# Installs the hypervisor switcher (see lib/cyberbeest-hypervisor-switch.sh
# for why one is needed: VirtualBox and KVM can't both hold VT-x/AMD-V at
# once, so with both installed side by side -- 53-virtualbox.sh and
# 53a-qemu-kvm-boxes.sh -- something has to let the user pick which one is
# actually active). Adds two Whisker menu entries, "Switch Sandbox VM to
# VirtualBox" and "... to QEMU/KVM", each running the switch via pkexec's
# graphical password prompt.
#
# Deliberately not gated on both 53-virtualbox.sh and 53a-qemu-kvm-boxes.sh
# having run: installs unconditionally so the menu entries exist regardless
# of provisioning order, and lib/cyberbeest-hypervisor-switch.sh itself
# checks whether the target hypervisor is actually installed before trying
# to switch to it.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/57-hypervisor-switcher.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing the hypervisor switcher ==="

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- Installing the switch scripts ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/cyberbeest-hypervisor-switch-ui.sh" "$TARGET_HOME/.local/bin/cyberbeest-hypervisor-switch-ui.sh"
# The privileged half stays root-owned, root-only -- it's invoked via
# pkexec, never run directly by the user.
install -o root -g root -m 755 \
	"$DIR/lib/cyberbeest-hypervisor-switch.sh" "$TARGET_HOME/.local/bin/cyberbeest-hypervisor-switch.sh"

echo "--- Adding Whisker menu launchers ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/applications"
cat > "$TARGET_HOME/.local/share/applications/cyberbeest-switch-to-vbox.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Switch Sandbox VM to VirtualBox
Comment=Makes VirtualBox the active hypervisor (deactivates QEMU/KVM)
Exec=$TARGET_HOME/.local/bin/cyberbeest-hypervisor-switch-ui.sh vbox
Icon=computer
Categories=System;
Terminal=false
EOF
cat > "$TARGET_HOME/.local/share/applications/cyberbeest-switch-to-kvm.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Switch Sandbox VM to QEMU/KVM
Comment=Makes QEMU/KVM the active hypervisor (deactivates VirtualBox)
Exec=$TARGET_HOME/.local/bin/cyberbeest-hypervisor-switch-ui.sh kvm
Icon=computer
Categories=System;
Terminal=false
EOF
chown "$TARGET_USER:$TARGET_USER" \
	"$TARGET_HOME/.local/share/applications/cyberbeest-switch-to-vbox.desktop" \
	"$TARGET_HOME/.local/share/applications/cyberbeest-switch-to-kvm.desktop"

echo "=== $(date) : done ==="
