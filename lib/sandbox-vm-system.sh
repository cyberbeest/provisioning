#!/bin/bash
# System-level (root) half of a Cyberbeest sandbox VM's own setup -- the
# per-login half is sandbox-vm-session.sh. Runs inside the guest: offline
# at VM setup (the host's lib/download-and-create-sandbox-vm-kvm.sh, via
# virt-customize) and on every guest update (91-sandbox-vm.sh). Idempotent.
#
# Profiled 2026-09-24: ~70 s from click to desktop, most of it avoidable.
#
#  1. Services a sandbox has no use for get a drop-in that skips them while
#     /etc/cyberbeest-sandbox-vm exists, rather than being disabled: the
#     guest's own provisioning (35-, 20-, 13-, 54-, 26-, 37-, ...) re-enables
#     units whenever it updates, but leaves foreign drop-ins alone.
#       - boot and shutdown chime: the host plays its own
#       - Bluetooth: a VM has no radio
#       - dnscrypt-proxy: the guest's DNS already goes to the host's
#         encrypted resolver (libvirt user networking forwards 10.0.2.3 to
#         it), so the guest's own copy only cost 3.6 s on the boot's
#         critical chain
#       - lid switch, lock-screen curtain and lock watchers: no lid, and
#         the sandbox doesn't lock (see sandbox-vm-session.sh)
#       - exim4's daemon: 5 s on the critical chain even when it works;
#         local mail (cron, rkhunter) goes through its sendmail binary,
#         which doesn't need the daemon
#  2. /var/log/exim4 is recreated: an image whose /var/log was emptied
#     without keeping this directory makes exim4 fail at every boot, on
#     the critical chain (4.3 s) and leaving the system "degraded".
#  3. A lean initramfs: the stock MODULES=most packs drivers for every
#     kind of hardware (57 MB), which the firmware then reads from the
#     compressed disk image on every boot. A VM's hardware never changes,
#     so only the modules it needs go in: virtio_blk + ext4 for the root
#     disk, qxl so the boot splash comes up the same way.
#
# Usage: sandbox-vm-system.sh <user> -- the guest account, for the per-user
# autostart override below.
set -euo pipefail

GUEST_USER="${1:?usage: sandbox-vm-system.sh <user>}"
GUEST_HOME="$(getent passwd "$GUEST_USER" | cut -d: -f6)"
# World-readable on purpose: the user units' ConditionPathExists is checked
# by the user's own systemd instance, and /etc/cyberbeest is root-only
# (initial-passwords.conf) -- a marker in there, as on 2026-09-24, made the
# condition silently pass for them. Moved here if found there.
MARKER=/etc/cyberbeest-sandbox-vm
if [ -e /etc/cyberbeest/sandbox-vm ]; then
	touch "$MARKER"
	rm -f /etc/cyberbeest/sandbox-vm
fi
chmod 644 "$MARKER"
CONDITION="[Unit]
# Cyberbeest sandbox VM: not needed here -- see sandbox-vm-system.sh.
ConditionPathExists=!$MARKER
"
SYSTEM_UNITS="cyberbeest-boot-chime.service bluetooth.service blueman-mechanism.service dnscrypt-proxy-local.service exim4.service"
USER_UNITS="cyberbeest-shutdown-chime.service lid-screen-off.service lock-screen-curtain.service lock-shutdown-watcher.service lock-warning-watcher.service"

echo "--- Skipping services a sandbox VM doesn't need ---"
for unit in $SYSTEM_UNITS; do
	mkdir -p "/etc/systemd/system/$unit.d"
	printf '%s' "$CONDITION" >"/etc/systemd/system/$unit.d/cyberbeest-sandbox-vm.conf"
done
# /etc/systemd/user applies to every user's instance of these units.
for unit in $USER_UNITS; do
	mkdir -p "/etc/systemd/user/$unit.d"
	printf '%s' "$CONDITION" >"/etc/systemd/user/$unit.d/cyberbeest-sandbox-vm.conf"
done

# The Bluetooth tray applet would start anyway and complain that it can't
# reach the (skipped) service -- a user-level autostart override hides it.
install -d -o "$GUEST_USER" -g "$GUEST_USER" "$GUEST_HOME/.config/autostart"
cat >"$GUEST_HOME/.config/autostart/blueman.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Blueman Applet
Hidden=true
EOF
chown "$GUEST_USER:$GUEST_USER" "$GUEST_HOME/.config/autostart/blueman.desktop"

echo "--- Making sure exim4 has its log directory ---"
if getent group Debian-exim >/dev/null; then
	install -d -o Debian-exim -g adm -m 2750 /var/log/exim4
fi

echo "--- GRUB: plain console, no wait ---"
# The image comes from the release build, which drives its install over a
# serial console and left GRUB talking to it (GRUB_TERMINAL=serial, 9600
# baud) -- to a port nobody reads. And with the menu hidden anyway, its
# 1-second timeout is pure delay.
if grep -qE '^GRUB_TERMINAL=serial|^GRUB_SERIAL_COMMAND=|^GRUB_TIMEOUT=[1-9]' /etc/default/grub; then
	sed -i -e 's/^GRUB_TERMINAL=serial$/GRUB_TERMINAL=console/' -e '/^GRUB_SERIAL_COMMAND=/d' \
		-e 's/^GRUB_TIMEOUT=[0-9]*$/GRUB_TIMEOUT=0/' /etc/default/grub
	update-grub
fi

echo "--- Lean initramfs ---"
CONF=/etc/initramfs-tools/conf.d/cyberbeest-sandbox-vm
WANT="# Cyberbeest sandbox VM: only the drivers this VM needs -- see sandbox-vm-system.sh.
MODULES=list"
MODULES_FILE=/etc/initramfs-tools/modules
changed=false
if [ "$(cat "$CONF" 2>/dev/null)" != "$WANT" ]; then
	printf '%s\n' "$WANT" >"$CONF"
	changed=true
fi
for mod in virtio_blk ext4 qxl; do
	if ! grep -qx "$mod" "$MODULES_FILE" 2>/dev/null; then
		echo "$mod" >>"$MODULES_FILE"
		changed=true
	fi
done
if [ "$changed" = true ]; then
	update-initramfs -u -k all
fi
