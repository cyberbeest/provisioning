#!/bin/bash
# Panel item: merges update-genmon.sh (security-update status) and
# shutdown-timer-genmon.sh (auto-shutdown-while-locked status) into a single
# xfce4-genmon-plugin instance -- two separate genmon processes cost an
# extra wrapper-process worth of RAM each, on every shipped machine, for
# widgets that are cheap to compute. genmon supports independent click
# regions for the icon (<click>) and the text (<txtclick>), so each widget
# keeps its own click handler.

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$SELF_DIR/update-genmon.sh"
# shellcheck disable=SC1091
. "$SELF_DIR/shutdown-timer-genmon.sh"

# Lock/auto-shutdown first, security-update status second: users check the
# lock-timer far more often than the update status, which they mostly just
# want to trust silently.
lock_heading="<b>$(t panel_status_genmon.lock_heading)</b>"
security_heading="<b>$(t panel_status_genmon.security_heading)</b>"

# First non-loopback address only -- multiple NICs (e.g. a VPN tunnel) would
# otherwise clutter the tooltip with addresses users didn't ask about.
ip_addr="$(hostname -I 2>/dev/null | awk '{print $1}')"
[ -n "$ip_addr" ] || ip_addr="$(t panel_status_genmon.ip_unknown)"
ip_line="$(t panel_status_genmon.ip_line)"
ip_line="${ip_line//ADDR/$ip_addr}"

echo "<img>${SECURITY_STATUS_IMG}</img>"
echo "<txt>${SHUTDOWN_TIMER_TXT}</txt>"
echo "<tool>${ip_line}&#10;&#10;${lock_heading}&#10;${SHUTDOWN_TIMER_TOOL}&#10;&#10;${security_heading}&#10;${SECURITY_STATUS_TOOL}</tool>"
echo "<click>${SECURITY_STATUS_CLICK}</click>"
echo "<txtclick>${SHUTDOWN_TIMER_TXTCLICK}</txtclick>"
