#!/bin/bash
# VM-only overrides layered on top of the normal desktop provisioning.
# Running inside a VM (VirtualBox "Fresh VM" test rig, or any other
# hypervisor) doesn't need the same visual polish or power-saving
# automation as real hardware:
#   - Solid-color background instead of the wallpaper photo -- cheaper to
#     render, and an instant visual tell that this session is the VM
#     guest, not the host (see lib/set-vm-solid-background.sh).
#   - Screensaver/DPMS dimming/auto-lock disabled outright: a disposable
#     test VM has no reason to defend itself against someone stepping away.
#   - lock-shutdown-watcher's auto-shutdown-while-locked disabled too
#     (belt and suspenders now that locking itself is off).
#   - UPower's low-battery PowerOff (19-low-battery-shutdown.sh) softened
#     to Ignore: VirtualBox passes the *host's* battery state through to
#     the guest, so without this a draining host battery could power off
#     the VM on its own.
#   - Battery/wattage/CPU-meter panel plugins removed: battery and wattage
#     readings are the host's, not the VM's, and the CPU meter is a
#     redundant second copy of what the host's own panel already shows
#     right next to this window. mem-liquid is left in place -- guest RAM
#     pressure is real and worth seeing.
#   - The genmon widget's auto-lock half (the "Lock screen after" preset
#     control) dropped, keeping only its security-update-status half --
#     see lib/panel-status-genmon-vm.sh. A control for tuning a delay that
#     no longer does anything (auto-lock is off) is just confusing.
# The panel work runs before the live xfconf overrides below, not after:
# xfce_panel_kill (in lib/xfce-panel-reload.sh) SIGKILLs xfconfd to force
# it to re-read xfce4-panel.xml, which also discards *any* channel's
# in-memory changes xfconfd hadn't yet flushed to its on-disk cache --
# including the screensaver/power-manager overrides, if they'd been made
# moments earlier. Confirmed 2026-09-07: running the panel step last
# silently reverted the screensaver/power-manager writes back to their
# pre-override (16-power-lock-config.sh default) values.
# Skips everything (no-op, exit 0) when systemd-detect-virt reports bare
# metal.
# Depends on: 11-xfce-panel-plugins.sh, 12-xfce-panel-layout.sh,
# 13-lock-shutdown-watcher.sh, 16-power-lock-config.sh,
# 18-desktop-background.sh, 19-low-battery-shutdown.sh.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/90-vm-mode-overrides.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : VM-mode overrides ==="

VIRT="$(systemd-detect-virt || true)"
if [ "$VIRT" = "none" ]; then
	echo "not running in a VM (systemd-detect-virt: none) -- nothing to do"
	echo "=== $(date) : done (skipped) ==="
	exit 0
fi
echo "--- detected virtualization: $VIRT ---"

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
TARGET_UID="$(id -u "$TARGET_USER")"

echo "--- Installing set-vm-solid-background.sh + autostart entry ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/set-vm-solid-background.sh" "$TARGET_HOME/.local/bin/set-vm-solid-background.sh"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/autostart"
sed "s|/home/cyberbeest/|$TARGET_HOME/|g" "$DIR/lib/cyberbeest-set-vm-solid-background.desktop" \
	> "$TARGET_HOME/.config/autostart/cyberbeest-set-vm-solid-background.desktop"
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.config/autostart/cyberbeest-set-vm-solid-background.desktop"

echo "--- Enabling LightDM autologin for $TARGET_USER ---"
# A VM guest has no attacker-with-physical-access threat model the way the
# host laptop does (that's the whole reason 16-power-lock-config.sh locks
# the host down) -- sitting at a login prompt on every boot just adds
# friction for no security benefit here. Debian's lightdm-autologin PAM
# config (unlike e.g. Ubuntu's) doesn't require a nopasswdlogin group
# membership, just this lightdm.conf.d key.
install -d /etc/lightdm/lightdm.conf.d
cat > /etc/lightdm/lightdm.conf.d/61-vm-autologin.conf <<EOF
[Seat:*]
autologin-user=$TARGET_USER
autologin-user-timeout=0
EOF

echo "--- Making sudo passwordless for $TARGET_USER ---"
# Combined with autologin above and the disabled lock screen further down,
# this means the account's password is never actually asked for anywhere
# in normal use -- the password still exists (a Linux account can't
# meaningfully have none at all without touching nullok PAM behavior,
# which is a much bigger and unrelated change), it's just never prompted
# for. Scoped to this one user via a dedicated sudoers.d file rather than
# touching the group-wide sudo config.
cat > /etc/sudoers.d/90-vm-nopasswd <<EOF
$TARGET_USER ALL=(ALL) NOPASSWD:ALL
EOF
chmod 440 /etc/sudoers.d/90-vm-nopasswd
visudo -cf /etc/sudoers.d/90-vm-nopasswd

echo "--- Disabling getty@tty1 (races LightDM for the console, flashing a text login prompt at boot) ---"
# There's no Conflicts= between display-manager.service and getty@tty1 in
# this systemd/lightdm build, so both start and briefly race for tty1,
# showing a flash of the text console login before LightDM's greeter takes
# over. Left enabled on real hardware (16-power-lock-config.sh's threat
# model, and it's a legitimate fallback if X ever fails to start there) --
# a VM guest doesn't need that fallback, and autologin above means the
# text prompt would never actually get used for logging in anyway.
systemctl disable getty@tty1.service || true

echo "--- Switching GRUB/Plymouth's boot resolution to 800x600 (avoids a scrollbar in the VBox window) ---"
# 15-grub-plymouth-theme.sh hardcodes GRUB_GFXMODE=1366x768 to match the
# real laptop panel. Tried "auto" first, expecting it to pick whatever
# mode matches the current VirtualBox window -- it doesn't: "auto" (and
# the hardcoded 1366x768) both resolve to a standard VBE mode from
# VirtualBox's virtual video BIOS's fixed advertised list (1024x768),
# which is *taller* than a typical VBox window's content area (~655px in
# testing), so GRUB/Plymouth still render with a vertical scrollbar until
# X starts and vmwgfx takes over at whatever custom size the window
# actually is -- that custom-size negotiation is an OS-level (Guest
# Additions) feature GRUB's own video driver doesn't have access to.
# There's also no single "right" answer here anyway: the real deployment
# target is an arbitrary end-user's VirtualBox window at an arbitrary
# size, not this dev VM's current one. 800x600 is a safe floor -- short
# enough to fit inside essentially any reasonably-sized window without
# scrolling, at the cost of some crispness on a larger one.
# Fixed at image-build/first-boot time, same as GRUB_GFXMODE always was.
GRUB_DEFAULTS_FILE=/etc/default/grub
if [ -e "$GRUB_DEFAULTS_FILE" ]; then
	sed -i -e 's/^GRUB_GFXMODE=.*/GRUB_GFXMODE=800x600/' "$GRUB_DEFAULTS_FILE"
	update-grub
fi

echo "--- Dropping the GRUB background image (redundant with the Plymouth splash right after it) ---"
# 15-grub-plymouth-theme.sh sets GRUB_BACKGROUND so the "Das Biest erwacht"
# artwork shows during GRUB itself, before Plymouth's own splash (a
# separate, differently-styled screen) takes over moments later -- on real
# hardware that gives continuous branding from power-on through the LUKS
# prompt. In a VM, GRUB's own boot phase is just an instant flash before
# Plymouth's screen anyway, so it's redundant rather than additive.
# Just commenting out/removing the variable doesn't work: /etc/grub.d/
# 05_debian_theme's set_background_image fallback chain, when
# GRUB_BACKGROUND is unset, still finds /boot/grub/cyberbeest-bg.png on
# its own (a *second*, independent fallback tier that scans /boot/grub/
# for any image file) and uses that anyway. Setting GRUB_BACKGROUND to an
# empty string (present but empty, not unset) instead makes that same
# script take its "explicit background requested but invalid" path,
# which calls set_default_theme (plain color scheme, no image) and exits
# immediately -- skipping every fallback search, deliberately.
if [ -e "$GRUB_DEFAULTS_FILE" ]; then
	sed -i -e 's/^#\?GRUB_BACKGROUND=.*/GRUB_BACKGROUND=""/' "$GRUB_DEFAULTS_FILE"
	update-grub
fi

echo "--- Swapping the bright-mode boot logo for the VM-specific one ---"
# cyberbeest-for-print.png is what the Plymouth theme shows on its
# near-white "bright mode" background (see cyberbeest.script) -- bright
# mode exists so a real LUKS unlock prompt doubles as a flashlight for
# typing in the dark, and ships on by default. A VM guest has no LUKS
# prompt to light up (see 90-vm-mode-overrides.sh's autologin section --
# it's a non-interactive splash here), so swap in a VM-specific logo
# instead of the marketing/print artwork. Pre-scaled to 322x322 (Lanczos)
# same as watermark.png/watermark-shutdown.png, to avoid Plymouth's own
# low-quality bilinear scaling -- see lib/plymouth-theme/ for the source.
THEME_DIR=/usr/share/plymouth/themes/cyberbeest
if [ -d "$THEME_DIR" ]; then
	install -m 644 "$DIR/lib/plymouth-theme/cyberbeest-for-print-vm.png" \
		"$THEME_DIR/cyberbeest-for-print.png"
	plymouth-set-default-theme -R cyberbeest
else
	echo "no $THEME_DIR yet (15-grub-plymouth-theme.sh hasn't run) -- skipping logo swap"
fi

echo "--- Softening UPower's low-battery PowerOff to Ignore (VM sees the host's battery) ---"
UPOWER_CONF=/etc/UPower/UPower.conf
if [ -e "$UPOWER_CONF" ]; then
	sed -i -e 's/^CriticalPowerAction=.*/CriticalPowerAction=Ignore/' "$UPOWER_CONF"
	systemctl restart upower.service || true
fi

echo "--- Installing the security-status-only genmon (dropping the auto-lock control) ---"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/panel-status-genmon-vm.sh" "$TARGET_HOME/.local/bin/panel-status-genmon.sh"

echo "--- Removing battery/wattage/CPU-meter plugins from the panel ---"
PANEL_XML="$TARGET_HOME/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml"
if [ -e "$PANEL_XML" ]; then
	sed -i \
		-e '\|<value type="int" value="12"/>|d' \
		-e '\|<value type="int" value="13"/>|d' \
		-e '\|<value type="int" value="14"/>|d' \
		-e '\|<property name="plugin-12" type="string" value="power-manager-plugin"/>|d' \
		-e '\|<property name="plugin-13" type="string" value="wattage-panel"/>|d' \
		-e '\|<property name="plugin-14" type="string" value="kitt-scanner"/>|d' \
		"$PANEL_XML"

	. "$DIR/lib/xfce-panel-reload.sh"
	if xfce_panel_dbus_addr; then
		xfce_panel_kill
		xfce_panel_launch
	fi
else
	echo "no xfce4-panel.xml yet (12-xfce-panel-layout.sh hasn't run) -- skipping panel edit"
fi

TARGET_UID_RUNTIME="/run/user/$TARGET_UID"
if [ -d "$TARGET_UID_RUNTIME" ]; then
	SESSION_PID="$(pgrep -u "$TARGET_USER" -x xfce4-session | head -1)"
	DBUS_ADDR=""
	if [ -n "$SESSION_PID" ]; then
		DBUS_ADDR="$(cat "/proc/$SESSION_PID/environ" 2>/dev/null | tr '\0' '\n' | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')" || true
	fi
	DBUS_ADDR="${DBUS_ADDR:-unix:path=$TARGET_UID_RUNTIME/bus}"

	echo "--- Applying the solid background now ---"
	su - "$TARGET_USER" -c "DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$DBUS_ADDR' $TARGET_HOME/.local/bin/set-vm-solid-background.sh" || true

	# Verified-retry (not a plain one-shot xfconf-query -s): a freshly
	# (re)started xfconfd -- the normal state right after login here, since
	# VM mode is applied at the end of a provisioning run or right after a
	# reboot -- has silently no-op'd some of these writes in testing, with
	# no error and the property left unset. See lib/xfconf-set-retry.sh.
	echo "--- Disabling screensaver/lock/DPMS dimming live ---"
	su - "$TARGET_USER" -c "
		DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$DBUS_ADDR'
		export DISPLAY DBUS_SESSION_BUS_ADDRESS
		. '$DIR/lib/xfconf-set-retry.sh'
		xfconf_set_retry xfce4-screensaver /lock/enabled false -- -n -t bool -s false
		xfconf_set_retry xfce4-screensaver /saver/idle-activation/enabled false -- -n -t bool -s false
		xfconf_set_retry xfce4-power-manager /xfce4-power-manager/dpms-enabled false -- -n -t bool -s false
		xfconf_set_retry xfce4-power-manager /xfce4-power-manager/brightness-inactivity-on-ac 0 -- -n -t uint -s 0
		xfconf_set_retry xfce4-power-manager /xfce4-power-manager/brightness-inactivity-on-battery 0 -- -n -t uint -s 0
	"

	echo "--- Disabling lock-shutdown-watcher ---"
	rm -f "$TARGET_HOME/.config/systemd/user/default.target.wants/lock-shutdown-watcher.service"
	su - "$TARGET_USER" -c "XDG_RUNTIME_DIR='$TARGET_UID_RUNTIME' DBUS_SESSION_BUS_ADDRESS='$DBUS_ADDR' systemctl --user stop lock-shutdown-watcher.service" || true
else
	echo "no active session for $TARGET_USER -- background/screensaver/panel changes will need a login to apply"
fi

echo "=== $(date) : done ==="
