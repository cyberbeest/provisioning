#!/bin/bash
# Installs the Cyberbeest Plymouth boot-splash theme (logo stays visible
# through the LUKS password prompt and shutdown) and matching GRUB styling
# (background image, fast hidden-timeout boot, no stray kernel/loading text
# on the console). See lib/plymouth-theme/.
set -euo pipefail

SELF_DIR="$(dirname "$(readlink -f "$0")")"
THEME_SRC="$SELF_DIR/plymouth-theme"
THEME_DIR="/usr/share/plymouth/themes/cyberbeest"
GRUB_FILE="/etc/default/grub"

# Plymouth runs before any filesystem holding /etc/default/locale is even
# decrypted, so its LUKS prompt text can't be looked up live at boot like
# the desktop-session strings -- it has to be resolved now, from whatever
# locale is active when this provisioning step runs, and baked into the
# theme. Re-run this script (then reboot) after a locale change to update it.
. "$SELF_DIR/i18n.sh"

echo "--- Installing plymouth-themes (base spinner assets our theme reuses) ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y plymouth plymouth-themes

echo "--- Assembling the cyberbeest Plymouth theme ---"
install -d "$THEME_DIR"
# Base animation/UI assets (throbber frames, password entry box, lock icon,
# etc.) come straight from the stock "spinner" theme -- only the script,
# .plymouth descriptor, and watermark images are actually custom.
install -m 644 /usr/share/plymouth/themes/spinner/bullet.png \
	/usr/share/plymouth/themes/spinner/capslock.png \
	/usr/share/plymouth/themes/spinner/entry.png \
	/usr/share/plymouth/themes/spinner/keyboard.png \
	/usr/share/plymouth/themes/spinner/keymap-render.png \
	/usr/share/plymouth/themes/spinner/lock.png \
	/usr/share/plymouth/themes/spinner/throbber-*.png \
	"$THEME_DIR/"
install -m 644 "$THEME_SRC/cyberbeest.plymouth" \
	"$THEME_SRC/watermark.png" "$THEME_SRC/watermark-shutdown.png" \
	"$THEME_DIR/"
# cyberbeest.script itself gets the LUKS prompt and unlock-success message
# substituted in for the current locale rather than being copied verbatim --
# see the i18n.sh comment above and the __LUKS_PROMPT__/__UNLOCK_SUCCESS__
# placeholders in the .script source.
sed -e "s|__LUKS_PROMPT__|$(t plymouth.luks_prompt)|" \
    -e "s|__UNLOCK_SUCCESS__|$(t plymouth.unlock_success)|" \
    -e "s|__SHUTDOWN_TEXT__|$(t plymouth.shutdown_text)|" \
    "$THEME_SRC/cyberbeest.script" \
	> "$THEME_DIR/cyberbeest.script"
chmod 644 "$THEME_DIR/cyberbeest.script"

echo "--- Activating the theme (rebuilds initramfs) ---"
plymouth-set-default-theme -R cyberbeest

echo "--- Installing GRUB background image ---"
# Locale-specific, since the artwork itself has translated text baked in
# (e.g. "Waking Up" vs "Das Biest erwacht") -- see plymouth.grub_background
# in lib/i18n.
install -m 644 "$THEME_SRC/$(t plymouth.grub_background)" /boot/grub/cyberbeest-bg.png

echo "--- Configuring $GRUB_FILE ---"
backup="${GRUB_FILE}.pre-cyberbeest"
[ -e "$backup" ] || cp -p "$GRUB_FILE" "$backup"

set_grub_var() {
	# set_grub_var KEY VALUE -- replaces an existing KEY=... line (commented
	# or not) or appends a new one, matching this machine's config exactly.
	local key="$1" value="$2"
	if grep -qE "^${key}=" "$GRUB_FILE"; then
		sed -i "s|^${key}=.*|${key}=${value}|" "$GRUB_FILE"
	elif grep -qE "^#${key}=" "$GRUB_FILE"; then
		sed -i "s|^#${key}=.*|${key}=${value}|" "$GRUB_FILE"
	else
		echo "${key}=${value}" >> "$GRUB_FILE"
	fi
}

set_grub_var GRUB_TIMEOUT 1
set_grub_var GRUB_TIMEOUT_STYLE hidden
set_grub_var GRUB_BACKGROUND '"/boot/grub/cyberbeest-bg.png"'
set_grub_var GRUB_GFXMODE 1366x768
set_grub_var GRUB_CMDLINE_LINUX_DEFAULT '"quiet splash loglevel=3"'

echo "--- Patching /etc/grub.d/10_linux to hide 'Loading Linux ...' text ---"
# Debian's 10_linux hardcodes quiet_boot="0" and never derives it from the
# kernel cmdline, so those lines print even with "quiet splash" set. This is
# cosmetic (not required for the theme/background to work), so a failure
# here is a warning, not fatal -- e.g. if a future grub2 version rewords the
# line this matches against.
GRUB_LINUX_SCRIPT="/etc/grub.d/10_linux"
OLD_LINE='quiet_boot="0"'
MARKER='# quiet_boot derived from cmdline (setup-grub-plymouth-theme.sh)'
if grep -qF "$MARKER" "$GRUB_LINUX_SCRIPT" 2>/dev/null; then
	echo "$GRUB_LINUX_SCRIPT: already patched."
elif grep -qF "$OLD_LINE" "$GRUB_LINUX_SCRIPT" 2>/dev/null; then
	script_backup="${GRUB_LINUX_SCRIPT}.pre-cyberbeest"
	[ -e "$script_backup" ] || cp -p "$GRUB_LINUX_SCRIPT" "$script_backup"
	insert="${OLD_LINE}\\n${MARKER}\\ncase \" \${GRUB_CMDLINE_LINUX} \${GRUB_CMDLINE_LINUX_DEFAULT} \" in\\n  *\" quiet \"*) quiet_boot=\"1\" ;;\\nesac"
	sed -i "s|${OLD_LINE}|${insert}|" "$GRUB_LINUX_SCRIPT"
	if ! bash -n "$GRUB_LINUX_SCRIPT"; then
		echo "WARNING: patched $GRUB_LINUX_SCRIPT has a syntax error, restoring original." >&2
		cp -p "$script_backup" "$GRUB_LINUX_SCRIPT"
	fi
else
	echo "WARNING: expected line not found in $GRUB_LINUX_SCRIPT, skipping this cosmetic patch." >&2
fi

echo "--- Regenerating GRUB config ---"
update-grub
