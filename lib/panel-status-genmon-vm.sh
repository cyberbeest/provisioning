#!/bin/bash
# VM-mode replacement for panel-status-genmon.sh: security-update status
# only, with the shutdown-timer half (auto-lock countdown text + its
# "Lock screen after" preset menu) dropped entirely. VM mode disables
# auto-lock outright (see 90-vm-mode-overrides.sh), so a control for
# tuning its delay has nothing left to control and would just be
# confusing clutter on the panel.
# Installed by 90-vm-mode-overrides.sh over the normal
# ~/.local/bin/panel-status-genmon.sh -- same genmon-11 widget/rc file,
# just a different script behind it.

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$SELF_DIR/update-genmon.sh"

security_heading="<b>$(t panel_status_genmon.security_heading)</b>"

ip_addr="$(hostname -I 2>/dev/null | awk '{print $1}')"
[ -n "$ip_addr" ] || ip_addr="$(t panel_status_genmon.ip_unknown)"
ip_line="$(t panel_status_genmon.ip_line)"
ip_line="${ip_line//ADDR/$ip_addr}"

echo "<img>${SECURITY_STATUS_IMG}</img>"
echo "<tool>${ip_line}&#10;&#10;${security_heading}&#10;${SECURITY_STATUS_TOOL}</tool>"
echo "<click>${SECURITY_STATUS_CLICK}</click>"
