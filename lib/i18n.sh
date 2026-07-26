#!/bin/bash
# Shared i18n helper for provisioning shell scripts. Source this, then call
# `t KEY` to print the current-locale string for KEY (falls back to English,
# then to KEY itself if neither catalog has it).
#
# Locale source of truth is /etc/default/locale (written by
# 00-locale-keyboard-timezone.sh's `dpkg-reconfigure locales`) -- read
# directly rather than trusting $LANG, since scripts run via sudo/systemd
# often have a stripped environment even in a live desktop session.

_I18N_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/i18n"

_i18n_locale() {
	local lang=""
	if [ -r /etc/default/locale ]; then
		lang="$(. /etc/default/locale 2>/dev/null; echo "${LANG:-}")"
	fi
	lang="${lang:-${LANG:-en_US.UTF-8}}"
	lang="${lang%%_*}"
	echo "${lang%%.*}"
}

# Always declared (even empty) so `t` never hits an undeclared-array error
# under `set -u`, whether or not a translated catalog was found.
declare -gA STRINGS_EN=()
declare -gA STRINGS_L10N=()

[ -f "$_I18N_DIR/strings.en.sh" ] && . "$_I18N_DIR/strings.en.sh"

_I18N_LOCALE="$(_i18n_locale)"
if [ "$_I18N_LOCALE" != "en" ] && [ -f "$_I18N_DIR/strings.$_I18N_LOCALE.sh" ]; then
	. "$_I18N_DIR/strings.$_I18N_LOCALE.sh"
fi

t() {
	local key="$1"
	if [ -n "${STRINGS_L10N[$key]+x}" ]; then
		printf '%s' "${STRINGS_L10N[$key]}"
	elif [ -n "${STRINGS_EN[$key]+x}" ]; then
		printf '%s' "${STRINGS_EN[$key]}"
	else
		printf '%s' "$key"
	fi
}
