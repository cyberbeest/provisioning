#!/bin/bash
# Lets the installer pick their language, keyboard layout, and timezone --
# unlike every other NN-*.sh step, these are per-user choices to make fresh,
# not settings to clone from the dev machine (which just happens to be
# en_US.UTF-8 / us / Europe/Berlin). Runs first (00-) since it's the most
# fundamental "who is this machine for" choice, before anything else.
#
# Language and keyboard are driven by a single "which country?" question
# instead of Debian's own dpkg-reconfigure locales/keyboard-configuration
# checklists -- those list every locale/layout in existence, which is a lot
# of scrolling for a choice that's obvious for the vast majority of installs,
# and the product only ships English/German UI catalogs anyway (see
# lib/i18n.py). Country picks sensible defaults for both, but language and
# keyboard are still separate confirm/override steps -- e.g. someone in
# Germany might still want an English UI, or be typing on a US keyboard.
# Timezone still goes through the real `dpkg-reconfigure tzdata` since a
# short curated list can't cover it as well as the real region/city picker.
#
# Needs a real terminal (whiptail can't run headlessly) -- if stdin isn't a
# TTY (e.g. a scripted/automated run-all.sh pass), this step is skipped with
# a warning rather than hanging, and can be run manually afterwards.
#
# Unlike every other NN-*.sh step, re-running this one always re-prompts
# (like every dpkg-reconfigure) rather than being a no-op -- so it self-skips
# the interactive part if it's already completed successfully since it was
# last edited (log newer than script, same test run-changed.sh uses), even
# under run-all.sh/menu.sh which otherwise always run every step. Delete the
# log (or edit this script) to force it to prompt again.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/00-locale-keyboard-timezone.log"

# rsync goes in first, and ahead of the skip/TTY checks below, so it's
# available from the very start of provisioning (including headless
# run-all.sh passes) to send the NN-*.log files this and later steps produce
# back to the dev machine as you go, rather than only after the whole run
# finishes.
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y rsync

if [ -e "$LOG" ] && [ "$LOG" -nt "$0" ]; then
	echo "Already configured locale/keyboard/timezone since this script was last edited -- skipping."
	echo "Delete $LOG (or edit this script) to be prompted again."
	exit 0
fi

if [ ! -t 0 ]; then
	# Deliberately not treated as "done" by the skip check above: backdate the
	# log so it stays older than this script and a later interactive run still
	# prompts, instead of this headless skip permanently masking it.
	echo "Not running on a terminal -- skipping interactive locale/keyboard/timezone setup." | tee "$LOG"
	echo "Run this script directly later (sudo bash 00-locale-keyboard-timezone.sh) to configure it." | tee -a "$LOG"
	touch -d @0 "$LOG"
	exit 0
fi

apt-get -o DPkg::Lock::Timeout=60 install -y whiptail locales keyboard-configuration tzdata console-setup x11-xkb-utils

echo "=== $(date) : configuring locale/keyboard/timezone ===" | tee "$LOG"

# code|Display name|default language (en/de)|en locale|de locale|keyboard layout
COUNTRIES=(
	"DE|Germany|de|en_US.UTF-8|de_DE.UTF-8|de"
	"AT|Austria|de|en_US.UTF-8|de_AT.UTF-8|at"
	"CH|Switzerland|de|en_US.UTF-8|de_CH.UTF-8|ch"
	"US|United States|en|en_US.UTF-8|de_DE.UTF-8|us"
	"GB|United Kingdom|en|en_GB.UTF-8|de_DE.UTF-8|gb"
	"IE|Ireland|en|en_IE.UTF-8|de_DE.UTF-8|gb"
	"CA|Canada|en|en_CA.UTF-8|de_DE.UTF-8|us"
	"AU|Australia|en|en_AU.UTF-8|de_DE.UTF-8|us"
	"NZ|New Zealand|en|en_NZ.UTF-8|de_DE.UTF-8|us"
	"XE|Other (default: English UI)|en|en_US.UTF-8|de_DE.UTF-8|us"
	"XD|Other (default: German UI)|de|en_US.UTF-8|de_DE.UTF-8|de"
)

echo "--- Country ---"
echo "Picks sensible defaults for language and keyboard below -- both are still"
echo "asked separately and can be changed, e.g. if you're in Germany but want"
echo "an English UI, or typing on a US keyboard. For anything more unusual than"
echo "this list (a different regional locale, a less common keyboard layout),"
echo "run 'dpkg-reconfigure locales' or 'dpkg-reconfigure keyboard-configuration'"
echo "by hand afterwards -- this picker only covers the common cases."

country_args=()
for row in "${COUNTRIES[@]}"; do
	IFS='|' read -r code name _ _ _ _ <<<"$row"
	status="OFF"
	[ "$code" = "US" ] && status="ON"
	country_args+=("$code" "$name" "$status")
done
COUNTRY=$(whiptail --title "Country" --radiolist \
	"Choose the country this machine will be used in:" 22 70 12 \
	"${country_args[@]}" 3>&1 1>&2 2>&3)

default_lang="" en_locale="" de_locale="" kbd_default=""
for row in "${COUNTRIES[@]}"; do
	IFS='|' read -r code _ lang en_loc de_loc kbd <<<"$row"
	if [ "$code" = "$COUNTRY" ]; then
		default_lang="$lang"
		en_locale="$en_loc"
		de_locale="$de_loc"
		kbd_default="$kbd"
	fi
done

echo "--- Language ---"
en_status="OFF"; de_status="OFF"
[ "$default_lang" = "en" ] && en_status="ON" || de_status="ON"
LANG_CHOICE=$(whiptail --title "Language" --radiolist \
	"Choose the system/UI language:" 12 60 2 \
	"en" "English" "$en_status" \
	"de" "Deutsch (German)" "$de_status" \
	3>&1 1>&2 2>&3)

if [ "$LANG_CHOICE" = "de" ]; then
	LOCALE="$de_locale"
else
	LOCALE="$en_locale"
fi

echo "--- Keyboard layout ---"
kbd_status_de="OFF" kbd_status_at="OFF" kbd_status_ch="OFF" kbd_status_us="OFF" kbd_status_gb="OFF"
case "$kbd_default" in
	de) kbd_status_de="ON" ;;
	at) kbd_status_at="ON" ;;
	ch) kbd_status_ch="ON" ;;
	us) kbd_status_us="ON" ;;
	gb) kbd_status_gb="ON" ;;
esac
KEYBOARD=$(whiptail --title "Keyboard layout" --radiolist \
	"Choose the physical keyboard layout:" 15 60 5 \
	"de" "German" "$kbd_status_de" \
	"at" "Austrian" "$kbd_status_at" \
	"ch" "Swiss German" "$kbd_status_ch" \
	"us" "US" "$kbd_status_us" \
	"gb" "UK" "$kbd_status_gb" \
	3>&1 1>&2 2>&3)

echo "Country: $COUNTRY | Language: $LANG_CHOICE | Locale: $LOCALE | Keyboard: $KEYBOARD" | tee -a "$LOG"

MENU_KEY_REMAP="no"
if [ "$KEYBOARD" = "de" ]; then
	if whiptail --title "Menu key remap (canonical Cyberbeest hardware only)" --yesno \
		"Canonical Cyberbeest laptops ship an ANSI-body (104-key) keyboard with German stickers/keymap applied, so the physical ISO key left of Y -- normally < / > / | on a real German keyboard -- doesn't exist. This can remap the unused Menu key to act as that key instead (plain = <, Shift = >, AltGr = |).\n\nOnly say Yes if this really is canonical Cyberbeest hardware -- on a real German (ISO) keyboard or different hardware this would break the Menu key for no reason." \
		15 78; then
		MENU_KEY_REMAP="yes"
	fi
fi

echo "--- Applying locale ($LOCALE) ---"
# Always also generate en_US.UTF-8 as a fallback for tools/logs that assume
# it, unless it's already the chosen locale.
gen_locales="$LOCALE UTF-8"
[ "$LOCALE" != "en_US.UTF-8" ] && gen_locales="$gen_locales, en_US.UTF-8 UTF-8"
debconf-set-selections <<-EOF
	locales locales/default_environment_locale select $LOCALE
	locales locales/locales_to_be_generated multiselect $gen_locales
EOF

# debconf-set-selections + dpkg-reconfigure alone does NOT actually apply
# this on a machine that already has a locale configured -- which every one
# of these does out of the box (see file header). locales.config re-derives
# both questions below from whatever's *already* in /etc/default/locale and
# /etc/locale.gen and unconditionally overwrites our preseed with that
# before dpkg-reconfigure ever applies it, so the old locale silently wins
# regardless of what was picked here. Write /etc/locale.gen and set LANG
# directly instead; dpkg-reconfigure below then just reaffirms debconf's
# own state to match what's now on disk, which keeps a later manual
# `dpkg-reconfigure locales` from re-prompting.
{
	echo "$LOCALE UTF-8"
	[ "$LOCALE" != "en_US.UTF-8" ] && echo "en_US.UTF-8 UTF-8"
} >/etc/locale.gen
locale-gen
update-locale --no-checks LANG
update-locale "LANG=$LOCALE"

dpkg-reconfigure -f noninteractive locales

echo "--- Applying keyboard layout ($KEYBOARD) ---"
# Model is always "Generic 105-key PC" in practice -- there's no real choice
# to make here on a PC/VM -- so it's preseeded rather than asked.
debconf-set-selections <<-EOF
	keyboard-configuration keyboard-configuration/modelcode string pc105
	keyboard-configuration keyboard-configuration/model select Generic 105-key PC
	keyboard-configuration keyboard-configuration/layoutcode string $KEYBOARD
	keyboard-configuration keyboard-configuration/variantcode string
	keyboard-configuration keyboard-configuration/xkb-keymap select $KEYBOARD
EOF
dpkg-reconfigure -f noninteractive keyboard-configuration
setupcon || true

# keyboard-configuration's own package scripts never call update-initramfs
# themselves (confirmed by grepping its postinst/config for "initramfs" --
# nothing), so without this the LUKS unlock prompt keeps using whatever
# keymap was baked in at image-build time regardless of the layout chosen
# above.
echo "--- Updating initramfs (keyboard layout for the LUKS unlock prompt) ---"
update-initramfs -u -k all

if [ "$MENU_KEY_REMAP" = "yes" ]; then
	echo "--- Installing Menu key remap (German <>| key) ---"
	TARGET_USER="${SUDO_USER:-cyberbeest}"
	TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
	install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
	install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
		"$DIR/lib/cyberbeest-menu-key-remap.sh" "$TARGET_HOME/.local/bin/cyberbeest-menu-key-remap.sh"
	install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/autostart"
	sed "s|/home/cyberbeest/|$TARGET_HOME/|g" "$DIR/lib/cyberbeest-menu-key-remap.desktop" \
		> "$TARGET_HOME/.config/autostart/cyberbeest-menu-key-remap.desktop"
	chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.config/autostart/cyberbeest-menu-key-remap.desktop"
fi

echo "--- Timezone ---"
dpkg-reconfigure tzdata

echo "=== $(date) : done. Reboot (or log out/in) for the new locale/keyboard to fully apply to the desktop session. ===" | tee -a "$LOG"
# run-gui.py's terminal-script path doesn't stream this script's own output
# live (see NEEDS_TERMINAL in run-gui.py) -- it re-reads the log file for
# MANUAL_TODO lines afterwards instead, so this needs to land in $LOG too.
echo "MANUAL_TODO: Reboot (or log out/in) for the new locale/keyboard to fully apply." | tee -a "$LOG"
