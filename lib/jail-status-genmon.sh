#!/bin/bash
# xfce4-genmon script: panel icon showing the app-protection (jail) mode.
# 🔒 all apps jailed | 🔒 + n/m some jailed | 🔓 none. Click opens the settings.
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SELF_DIR/i18n.sh"
. "$HOME/bin/jail-lib.sh" || exit 0

total=0; on=0; names=""
for a in $JAIL_ALL_APPS; do
	# Only count apps that are actually installed.
	case "$a" in
	firefox) p=/usr/bin/firefox-esr ;; chrome) p=/usr/bin/google-chrome-stable ;;
	signal) p=/opt/Signal/signal-desktop ;; element) p=/opt/Element/element-desktop ;;
	telegram) p=/usr/bin/telegram-desktop ;; viber) p=/opt/viber/Viber ;;
	sparrow) p=/opt/sparrowwallet/bin/Sparrow ;; feather) p=/usr/bin/feather ;;
	esac
	[ -e "$p" ] || continue
	total=$((total + 1))
	if jail_enabled "$a"; then on=$((on + 1)); names="$names ${a^}"; fi
done

mode="$(jail_mode)"
badge=""
case "$mode" in
all) icon="🔒"; tip="$(t jail.tip_all)" ;;
none) icon="🔓"; tip="$(t jail.tip_none)" ;;
*) icon="🔒"; badge="<span size='x-small'>${on}/${total}</span>"
	# shellcheck disable=SC2059
	tip="$(printf "$(t jail.tip_some)" "${names# }")" ;;
esac
echo "<txt><span size='small'>&#8202;</span><span size='x-large'>${icon}</span>${badge}<span size='small'>&#8202;</span></txt>"
echo "<tool>${tip}</tool>"
echo "<txtclick>$HOME/.local/bin/jail-settings.py</txtclick>"
