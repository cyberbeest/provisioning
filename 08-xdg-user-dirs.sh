#!/bin/bash
# Debian's xdg-user-dirs-update runs silently on every XFCE login (see
# /etc/xdg/autostart/xdg-user-dirs.desktop) and, on a user's very first
# login ever, creates the standard folders (Desktop, Pictures, ...)
# translated into their locale -- under German that's e.g. ~/Bilder instead
# of ~/Pictures, a real rename, not a symlink or display-only label.
#
# Crucially, that translation only ever happens the FIRST time
# user-dirs.dirs is created for a user. On every later run -- including one
# we trigger ourselves further down -- xdg-user-dirs-update leaves already-
# defined entries alone no matter what the locale is by then (see its man
# page: retranslating on a locale change is left to a separate interactive
# tool, xdg-user-dirs-gtk-update, which isn't installed here). If the very
# first XFCE session's autostart ran before 00-locale-keyboard-timezone.sh's
# locale change had taken effect for that session, user-dirs.dirs ends up
# permanently stamped with English names even under a German locale --
# simply re-running xdg-user-dirs-update afterward can NOT fix that.
#
# Left alone, that collides with this project's own provisioning: several
# later scripts (09-cyberbeest-logout-dialog.sh is the earliest) write
# straight into "$TARGET_HOME/Pictures" before any real login has ever
# happened, so under German the "official" XDG Pictures folder should be
# ~/Bilder -- Desktop Settings' image picker and any other XDG-aware app
# follow XDG_PICTURES_DIR, not a hardcoded English name.
#
# Fix: don't trust whatever xdg-user-dirs-update last wrote to
# user-dirs.dirs. Ask gettext directly, under the target user's actual
# configured locale, what each standard folder's name should currently be;
# if that differs from the English default, rename the real directory to
# the translated name ourselves (a plain mv -- lossless whether the English
# folder was empty or already had real content in it, e.g. a machine set up
# before this script existed), then patch user-dirs.dirs itself so
# XDG-aware apps agree.
#
# No compatibility symlink is left behind under the English name: every
# script in this repo that touches one of these folders resolves it via
# lib/xdg-dirs.sh's `xdg_dir` (a thin wrapper around the `xdg-user-dir`
# tool this script installs) instead of hardcoding an English path, so
# nothing here depends on the English name existing.
#
# Only if both the English and translated names already exist as
# independent real directories is a MANUAL_TODO logged instead of guessing
# which one to keep.
#
# Depends on: 00-locale-keyboard-timezone.sh (sets the locale this reads).
# Idempotent: safe to re-run (also cleans up an English-name symlink left by
# an older version of this script, back when it used to create one).
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
apt-get -o DPkg::Lock::Timeout=60 install -y xdg-user-dirs gettext-base

echo "--- Running xdg-user-dirs-update as $TARGET_USER, under their configured locale ---"
# Same locale lookup lib/i18n.sh uses: /etc/default/locale, not the
# invoking (root/sudo) shell's own LANG, which is often unset/stripped.
# This creates user-dirs.dirs (translated) on a genuinely first-ever run,
# or is a no-op for any folder that already has an entry -- see header.
LOCALE_VALUE="$(. /etc/default/locale 2>/dev/null; echo "${LANG:-en_US.UTF-8}")"
su - "$TARGET_USER" -c "LANG='$LOCALE_VALUE' LC_ALL='$LOCALE_VALUE' xdg-user-dirs-update"

USER_DIRS_FILE="$TARGET_HOME/.config/user-dirs.dirs"
DEFAULTS_FILE="/etc/xdg/user-dirs.defaults"

echo "--- Reconciling fixed English names against what this locale actually translates them to ---"
while IFS='=' read -r key default_name; do
	[ -n "$key" ] || continue
	var="XDG_${key}_DIR"
	translated_name="$(LANG="$LOCALE_VALUE" LC_ALL="$LOCALE_VALUE" gettext -d xdg-user-dirs "$default_name")"
	if [ "$translated_name" = "$default_name" ]; then
		continue # genuinely untranslated in this locale (e.g. Downloads, Videos under German) -- nothing to do
	fi

	eng_path="$TARGET_HOME/$default_name"
	real_path="$TARGET_HOME/$translated_name"

	# Clean up a symlink left by an older version of this script -- nothing
	# in this repo relies on the English name any more (see header).
	[ -L "$eng_path" ] && rm -f "$eng_path"

	if [ -d "$real_path" ]; then
		if [ -d "$eng_path" ] && [ -n "$(ls -A "$eng_path" 2>/dev/null)" ]; then
			echo "MANUAL_TODO: both ~/$default_name and ~/$translated_name have files in them for your $key folder -- xdg-user-dirs couldn't tell which to treat as the real one, so both were left as-is. Move anything you want into one of them by hand." >&3
		else
			[ -d "$eng_path" ] && rmdir "$eng_path" 2>/dev/null
		fi
	elif [ -d "$eng_path" ]; then
		# Lossless whether $eng_path is empty (the common case: this
		# locale's own first-login run just never fired) or already has
		# real content (re-provisioning a machine set up before this
		# script existed) -- either way there's nothing at $real_path yet
		# to conflict with.
		mv "$eng_path" "$real_path"
		sed -i "s#^${var}=.*#${var}=\"\$HOME/${translated_name}\"#" "$USER_DIRS_FILE"
		echo "Renamed $default_name -> $translated_name"
	else
		mkdir -p "$real_path"
		chown "$TARGET_USER:$TARGET_USER" "$real_path"
		sed -i "s#^${var}=.*#${var}=\"\$HOME/${translated_name}\"#" "$USER_DIRS_FILE"
		echo "Created $translated_name"
	fi
done < <(grep -v '^#' "$DEFAULTS_FILE" | grep '=')

echo "=== $(date) : done ==="
