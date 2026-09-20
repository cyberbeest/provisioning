#!/bin/bash
# xfce4-genmon-plugin script: shows what kind of content currently sits in
# the X11 clipboard (text/image/files/empty), sourced from the state file
# clipboard-watcher.sh maintains. Security angle: any app can read the
# clipboard, so a breached app is an instant leak of whatever's sitting in
# it -- this makes that exposure visible instead of invisible, and (via
# clipboard-watcher.sh's auto-clear timer) bounds how long it lasts.
#
# Click opens clipboard-status-menu.py, a context menu of the commands
# relevant to whatever's currently in the clipboard (view/edit, show image,
# clear) plus the always-available auto-clear settings command.
#
# Tooltip is deliberately a single line with no content preview (only the
# type + age + auto-clear countdown) -- hovering needs no click, so a
# preview there would be visible to anyone looking over your shoulder;
# seeing *what's* in the clipboard requires the deliberate click into the
# menu/viewer instead.

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# i18n.sh (and its i18n/ catalog dir) is installed next to this script -- see
# lib/i18n.sh's own comment about resolving relative to BASH_SOURCE.
. "$SELF_DIR/i18n.sh"

STATE_FILE="$HOME/.config/cyberbeest/clipboard-status.state"
CONFIG_FILE="$HOME/.config/cyberbeest/clipboard-status.conf"
# Must match clipboard-watcher.sh's DEFAULT_AUTO_CLEAR_SECS and
# clipboard-auto-clear-settings.py's/clipboard-status-menu.py's DEFAULTS --
# duplicated rather than shared, same convention the shutdown-timer family
# of scripts uses.
DEFAULT_AUTO_CLEAR_SECS=900

TYPE="empty"
PREVIEW=""
CHANGED=0
if [ -f "$STATE_FILE" ]; then
	# shellcheck disable=SC1090
	source "$STATE_FILE"
fi

auto_clear_seconds() {
	local val
	val=$(grep '^AUTO_CLEAR_SECONDS=' "$CONFIG_FILE" 2>/dev/null | tail -n1 | cut -d= -f2)
	echo "${val:-$DEFAULT_AUTO_CLEAR_SECS}"
}

# Unit suffixes (s/m/h) are left untranslated, same convention as
# shutdown-timer-genmon.sh's fmt() -- short enough to read as universal.
fmt_duration() {
	local secs=$1
	if [ "$secs" -lt 60 ]; then
		echo "${secs}s"
	elif [ "$secs" -lt 3600 ]; then
		if [ $(( secs % 60 )) -eq 0 ]; then
			echo "$(( secs / 60 ))m"
		else
			echo "$(( secs / 60 ))m $(( secs % 60 ))s"
		fi
	elif [ $(( secs % 3600 )) -eq 0 ]; then
		echo "$(( secs / 3600 ))h"
	else
		echo "$(( secs / 3600 ))h $(( (secs % 3600) / 60 ))m"
	fi
}

case "$TYPE" in
	text)   icon="📋" ;;
	image)  icon="🖼" ;;
	files)  icon="📁" ;;
	empty)  icon="⬜" ;;
	*)      icon="❓" ;;
esac

age=""
if [ "$CHANGED" -gt 0 ] 2>/dev/null; then
	now=$(date +%s)
	secs=$(( now - CHANGED ))
	if [ "$secs" -lt 60 ]; then
		age="${secs}s"
	elif [ "$secs" -lt 3600 ]; then
		age="$(( secs / 60 ))m"
	else
		age="$(( secs / 3600 ))h"
	fi
fi

# genmon's rc-level Font/UseLabel options control a separate, optional
# caption widget, not the actual <txt> content (confirmed via `strings
# libgenmon.so`, which shows <txt> going through gtk_label_set_markup()),
# so Pango markup embedded directly here is what actually controls
# size/weight. The hair-space padding sits in its own small-sized span
# rather than inside the icon's x-large span -- a space character scales
# with font size same as any glyph, so putting it inside the enlarged span
# would make it just as oversized as the icon instead of a small,
# size-independent gap.
echo "<txt><span size='small'>&#8202;</span><span size='x-large'>${icon}</span><span size='small'>&#8202;</span></txt>"

delay=$(auto_clear_seconds)

if [ "$TYPE" = "empty" ]; then
	if [ "$delay" -gt 0 ] 2>/dev/null; then
		setting="$(t clipboard_genmon.auto_clear_prefix) $(fmt_duration "$delay")"
	else
		setting="$(t clipboard_genmon.auto_clear_prefix) $(t clipboard_genmon.never)"
	fi
	tooltip="$(t clipboard_genmon.empty_with_setting)"
	tooltip="${tooltip//SETTING/$setting}"
else
	case "$TYPE" in
		text)    label="$(t clipboard_genmon.label_text)" ;;
		image)   label="$(t clipboard_genmon.label_image)" ;;
		files)   label="$(t clipboard_genmon.label_files)" ;;
		*)       label="$(t clipboard_genmon.label_unknown)" ;;
	esac

	countdown=""
	if [ "$delay" -gt 0 ] 2>/dev/null && [ "$CHANGED" -gt 0 ] 2>/dev/null; then
		remaining=$(( delay - (now - CHANGED) ))
		[ "$remaining" -lt 0 ] && remaining=0
		countdown="$(t clipboard_genmon.countdown)"
		countdown="${countdown//DURATION/$(fmt_duration "$remaining")}"
	fi

	tooltip="$(t clipboard_genmon.status)"
	tooltip="${tooltip//LABEL/$label}"
	tooltip="${tooltip//AGE/$age}"
	tooltip="${tooltip//COUNTDOWN/$countdown}"
fi
echo "<tool>${tooltip}</tool>"
echo "<txtclick>$HOME/.local/bin/clipboard-status-menu.py</txtclick>"
