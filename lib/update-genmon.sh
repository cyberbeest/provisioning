#!/bin/bash
# Panel item: security-update status for xfce4-genmon-plugin.

HISTORY_LOG=/var/log/apt/history.log
STATUS_FILE=/var/lib/security-update-status
PHASE_FILE=/run/security-update-check.phase

# Renders as "N min past" / "N min ahead" of now, in whole minutes.
minutes_label() {
    local target_epoch="$1" now_epoch="$2" diff mins
    diff=$(( now_epoch - target_epoch ))
    if [ "$diff" -ge 0 ]; then
        mins=$(( diff / 60 ))
        echo "${mins} min past"
    else
        mins=$(( (-diff) / 60 ))
        echo "${mins} min ahead"
    fi
}

now_epoch="$(date +%s)"

last_check_epoch=""
last_check_duration=""
last_check_result=""
last_check_reason=""
if [ -r "$STATUS_FILE" ]; then
    # shellcheck disable=SC1090
    . "$STATUS_FILE"
    last_check_epoch="${LAST_CHECK_EPOCH:-}"
    last_check_duration="${LAST_CHECK_DURATION_SECONDS:-}"
    last_check_result="${LAST_CHECK_RESULT:-}"
    last_check_reason="${LAST_CHECK_REASON:-}"
    # genmon's <tool> text is Pango markup, so escape entities before splicing
    # the (untrusted, apt-output-derived) reason string into it.
    last_check_reason="${last_check_reason//&/&amp;}"
    last_check_reason="${last_check_reason//</&lt;}"
    last_check_reason="${last_check_reason//>/&gt;}"
fi
CHECK_INTERVAL_SECONDS=$(( 120 * 60 ))
BOOT_SEC=$(( 5 * 60 ))  # matches OnBootSec=5min in security-update-check.timer
BOOT_GRACE_SECONDS=$(( 6 * 60 ))

# security-update-check.timer has both OnBootSec=5min and
# OnUnitActiveSec=120min triggers, but security-update-check.sh now skips
# without running if the last real check was under 120 minutes ago (so
# frequent reboots don't hammer Debian's mirrors). That means a boot-driven
# run only actually does anything if a check was already due -- so only
# treat this as "waiting for the first check" when the 120-minute interval
# had already elapsed before boot; otherwise the OnBootSec trigger will just
# skip and the existing last-check status stands.
uptime_seconds="$(awk '{print int($1)}' /proc/uptime 2>/dev/null)"
boot_epoch=""
[ -n "$uptime_seconds" ] && boot_epoch=$(( now_epoch - uptime_seconds ))
awaiting_first_check=false
if [ -n "$boot_epoch" ] && [ $(( now_epoch - boot_epoch )) -lt "$BOOT_GRACE_SECONDS" ] \
   && { [ -z "$last_check_epoch" ] || [ $(( boot_epoch - last_check_epoch )) -ge "$CHECK_INTERVAL_SECONDS" ]; }; then
    awaiting_first_check=true
fi

# security-update-check.timer fires on OnUnitActiveSec (monotonic), so
# systemd never populates NextElapseUSecRealtime for it -- derive the next
# run ourselves instead of querying systemd. While waiting for the first
# post-boot run, base it on boot time + OnBootSec rather than
# last_check_epoch + interval, which would still point into the past.
next_check_epoch=""
if [ "$awaiting_first_check" = true ]; then
    next_check_epoch=$(( boot_epoch + BOOT_SEC ))
elif [ -n "$last_check_epoch" ]; then
    next_check_epoch=$(( last_check_epoch + CHECK_INTERVAL_SECONDS ))
fi

last_check_rel="unknown"
next_check_rel="unknown"
[ -n "$last_check_epoch" ] && last_check_rel="$(minutes_label "$last_check_epoch" "$now_epoch")"
[ -n "$next_check_epoch" ] && next_check_rel="$(minutes_label "$next_check_epoch" "$now_epoch")"

phase=""
reboot_pending=false
overdue=false

if systemctl is-active --quiet security-update-check.service; then
    phase="$(cat "$PHASE_FILE" 2>/dev/null)"
    [ -n "$phase" ] || phase="checking"
elif [ "$awaiting_first_check" = true ]; then
    phase="checking"
elif [ -n "$last_check_epoch" ] && [ $(( now_epoch - last_check_epoch )) -gt $(( CHECK_INTERVAL_SECONDS * 2 )) ]; then
    # A run should have happened by now (timer missed, disabled, or the
    # machine was asleep well past its catch-up window) -- flag it rather
    # than silently keep showing a stale "all good".
    overdue=true
fi

# /var/run/reboot-required is the standard Debian marker: written whenever
# any just-upgraded package (kernel, glibc, systemd, openssl, ...) flags
# itself as needing a reboot, not just kernel bumps.
if [ -f /var/run/reboot-required ]; then
    reboot_pending=true
fi

# Belt-and-suspenders: also catch a newer installed kernel than the one
# running, in case the marker file was cleared without an actual reboot.
running_kernel="$(uname -r)"
latest_kernel="$(dpkg -l 'linux-image-[0-9]*' 2>/dev/null | awk '/^ii/{print $2}' | sed 's/^linux-image-//' | sort -V | tail -1)"
if [ -n "$latest_kernel" ] && [ "$latest_kernel" != "$running_kernel" ]; then
    reboot_pending=true
fi

# Most recent real (non dry-run) unattended-upgrades transaction: how many
# packages it touched and how long it took, from the world-readable apt history log.
last_run="$(awk -v RS="" '/^Commandline: .*unattended-upgrades/ && !/--dry-run/ {rec=$0} END{print rec}' "$HISTORY_LOG" 2>/dev/null)"
last_run_count=0
if [ -n "$last_run" ]; then
    pkg_line="$(echo "$last_run" | sed -n 's/^\(Upgrade\|Install\): //p')"
    if [ -n "$pkg_line" ]; then
        last_run_count="$(echo "$pkg_line" | awk -F'), ' '{print NF}')"
    fi
fi

# Duration of the last check comes from our own timer's status file, not the
# apt history log, since that log only gets an entry when packages actually
# changed -- a 0-update run would otherwise show no duration at all.
last_run_duration=""
[ -n "$last_check_duration" ] && last_run_duration="${last_check_duration}s"

ICON_CHECKING=/usr/share/icons/Tango/24x24/actions/view-refresh.png
ICON_INSTALLING=/usr/share/icons/Tango/24x24/apps/system-software-update.png
ICON_REBOOT=/usr/share/icons/hicolor/24x24/actions/xfsm-reboot.png
ICON_OVERDUE=/usr/share/icons/Tango/24x24/status/dialog-warning.png
ICON_NETWORK_ERROR=/usr/share/icons/Tango/24x24/status/network-error.png
ICON_UPGRADE_ERROR=/usr/share/icons/Tango/24x24/status/dialog-error.png
ICON_OK="$HOME/.local/share/update-genmon-icons/ok-check.png"

if [ "$phase" = installing ]; then
    img="$ICON_INSTALLING"
    tool="Installing security updates now..."
elif [ "$phase" = checking ]; then
    img="$ICON_CHECKING"
    if [ "$awaiting_first_check" = true ]; then
        tool="Waiting for the first security check since boot..."
    else
        tool="Checking for security updates now..."
    fi
elif [ "$reboot_pending" = true ]; then
    img="$ICON_REBOOT"
    reboot_pkgs=""
    [ -r /var/run/reboot-required.pkgs ] && reboot_pkgs="$(paste -sd, /var/run/reboot-required.pkgs)"
    tool="A security update was installed and needs a restart to take effect."
    [ -n "$reboot_pkgs" ] && tool="${tool}&#10;Triggered by: ${reboot_pkgs}"
    tool="${tool}&#10;Please reboot when you get a chance."
elif [ "$last_check_result" = network-error ]; then
    img="$ICON_NETWORK_ERROR"
    tool="Last security check failed: no network connection."
    [ -n "$last_check_reason" ] && tool="${tool}&#10;${last_check_reason}"
elif [ "$last_check_result" = upgrade-error ]; then
    img="$ICON_UPGRADE_ERROR"
    tool="Last security update failed to install."
    [ -n "$last_check_reason" ] && tool="${tool}&#10;${last_check_reason}"
elif [ "$overdue" = true ]; then
    img="$ICON_OVERDUE"
    tool="Security check is overdue -- it should have run by now."
else
    img="$ICON_OK"
    tool="All security updates are installed, your system is safe."
fi

if [ -n "$last_run_duration" ]; then
    tool="${tool}&#10;Last check: ${last_check_rel} (${last_run_count} updates, took ${last_run_duration})"
else
    tool="${tool}&#10;Last check: ${last_check_rel} (${last_run_count} updates)"
fi
tool="${tool}&#10;Next check: ${next_check_rel}"

echo "<img>${img}</img>"
echo "<tool>${tool}</tool>"
