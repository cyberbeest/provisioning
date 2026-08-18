#!/bin/bash
# Debian's xdg-user-dirs-update runs silently on every XFCE login (see
# /etc/xdg/autostart/xdg-user-dirs.desktop) and, on a user's very first
# login, creates the standard folders (Desktop, Pictures, ...) translated
# into their locale -- under German that's e.g. ~/Bilder instead of
# ~/Pictures, a real rename, not a symlink or display-only label. Left
# alone, that collides with this project's own provisioning: several later
# scripts (09-cyberbeest-logout-dialog.sh is the earliest) write straight
# into "$TARGET_HOME/Pictures" before any real login has ever happened, so
# under German the first login would then create a second, empty ~/Bilder
# as the "official" XDG Pictures folder -- orphaning everything already
# installed into ~/Pictures, since Desktop Settings' image picker and any
# other XDG-aware app follow XDG_PICTURES_DIR, not a hardcoded English name.
#
# Fix: run xdg-user-dirs-update for real (as the target user, under their
# actual configured locale) right here, before any other script touches one
# of these folders -- so whichever name comes out is genuinely the one
# xfdesktop/Thunar/GTK file pickers already agree on -- then add the fixed
# English name as a symlink to it, so "$HOME/Pictures" (etc.) keeps
# resolving correctly regardless of locale, for this project's own scripts
# and for any third-party app that hardcodes the English name.
#
# Re-provisioning a machine that already has real content sitting in the
# English-named folder (e.g. set up before this script existed) is handled
# without moving anything: if the newly-created translated folder is still
# empty, it's replaced with a symlink pointing *back* at the existing
# English one instead, so both names keep working either way. Only if both
# somehow already have independent real content is a MANUAL_TODO logged
# instead of guessing which one to keep.
#
# Depends on: 00-locale-keyboard-timezone.sh (sets the locale this reads).
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/08-xdg-user-dirs.log"
# Save the real console on fd 3, same convention as 18-desktop-background.sh,
# so a MANUAL_TODO reaches whoever's running this directly instead of only
# landing in the log file.
exec 3>&1
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : reconciling XDG user directories ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y xdg-user-dirs

echo "--- Running xdg-user-dirs-update as $TARGET_USER, under their configured locale ---"
# Same locale lookup lib/i18n.sh uses: /etc/default/locale, not the
# invoking (root/sudo) shell's own LANG, which is often unset/stripped.
LOCALE_VALUE="$(. /etc/default/locale 2>/dev/null; echo "${LANG:-en_US.UTF-8}")"
su - "$TARGET_USER" -c "LANG='$LOCALE_VALUE' LC_ALL='$LOCALE_VALUE' xdg-user-dirs-update"

USER_DIRS_FILE="$TARGET_HOME/.config/user-dirs.dirs"
DEFAULTS_FILE="/etc/xdg/user-dirs.defaults"

echo "--- Reconciling fixed English names against the (possibly translated) real folders ---"
while IFS='=' read -r key default_name; do
	[ -n "$key" ] || continue
	var="XDG_${key}_DIR"
	real_name="$(grep "^${var}=" "$USER_DIRS_FILE" 2>/dev/null | sed -E 's/^[A-Z_]+="\$HOME\/(.*)"$/\1/' || true)"
	real_name="${real_name%%/*}" # first path element only, in case a *.dirs entry ever nests one
	[ -n "$real_name" ] || continue
	if [ "$real_name" = "$default_name" ]; then
		continue # untranslated in this locale (e.g. Downloads, Videos under German) -- nothing to do
	fi

	eng_path="$TARGET_HOME/$default_name"
	real_path="$TARGET_HOME/$real_name"

	if [ -L "$eng_path" ] || [ -L "$real_path" ]; then
		: # already reconciled on a previous run
	elif [ -d "$eng_path" ] && [ -n "$(ls -A "$eng_path" 2>/dev/null)" ]; then
		# English name already has real content (e.g. re-provisioning a
		# machine set up before this script existed).
		if [ -d "$real_path" ] && [ -z "$(ls -A "$real_path" 2>/dev/null)" ]; then
			rmdir "$real_path"
			ln -s "$default_name" "$real_path"
			chown -h "$TARGET_USER:$TARGET_USER" "$real_path"
			echo "$default_name already had content -- linked $real_name -> $default_name instead"
		else
			echo "MANUAL_TODO: both ~/$default_name and ~/$real_name have files in them for your $key folder -- xdg-user-dirs couldn't tell which to treat as the real one, so both were left as-is. Move anything you want into one of them by hand." >&3
		fi
	else
		if [ -d "$eng_path" ]; then rmdir "$eng_path" 2>/dev/null || true; fi
		ln -s "$real_name" "$eng_path"
		chown -h "$TARGET_USER:$TARGET_USER" "$eng_path"
		echo "Linked $default_name -> $real_name"
	fi
done < <(grep -v '^#' "$DEFAULTS_FILE" | grep '=')

echo "=== $(date) : done ==="
