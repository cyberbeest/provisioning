#!/bin/bash
# Panel item: security-update status for xfce4-genmon-plugin.

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# i18n.sh (and its i18n/ catalog dir) is installed next to this script -- see
# lib/i18n.sh's own comment about resolving relative to BASH_SOURCE.
# shellcheck disable=SC1091
. "$SELF_DIR/i18n.sh"

HISTORY_LOG=/var/log/apt/history.log
STATUS_FILE=/var/lib/security-update-status
APPS_STATUS_FILE=/var/lib/security-update-apps-status
PHASE_FILE=/run/security-update-check.phase

# Renders as "N min ago" / "in N min" of now, in whole minutes.
minutes_label() {
    local target_epoch="$1" now_epoch="$2" diff mins
    diff=$(( now_epoch - target_epoch ))
    if [ "$diff" -ge 0 ]; then
        mins=$(( diff / 60 ))
        if [ "$mins" -eq 0 ]; then
            t update_genmon.right_now
        else
            local label; label="$(t update_genmon.min_ago)"
            echo "${label//N/$mins}"
        fi
    else
        mins=$(( (-diff) / 60 ))
        if [ "$mins" -eq 0 ]; then
            t update_genmon.right_now
        else
            local label; label="$(t update_genmon.in_min)"
            echo "${label//N/$mins}"
        fi
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

# Messenger apps (Signal/Element) are updated by their own separate
# unattended-upgrades pass -- see lib/setup-security-update-timer.sh -- so
# they get their own status line rather than being folded into the Debian
# security state that drives the icon above.
apps_check_epoch=""
apps_check_result=""
if [ -r "$APPS_STATUS_FILE" ]; then
    # shellcheck disable=SC1090
    . "$APPS_STATUS_FILE"
    apps_check_epoch="${LAST_CHECK_EPOCH:-}"
    apps_check_result="${LAST_CHECK_RESULT:-}"
fi

CHECK_INTERVAL_SECONDS=$(( 120 * 60 ))
SLOT_SECONDS=$(( 15 * 60 ))  # matches OnCalendar=*:0/15 in security-update-check.timer
THROTTLE_SLACK_SECONDS=$(( 5 * 60 ))  # matches security-update-check.sh

# security-update-check.timer fires on the wall clock every 15 minutes
# (plus a Persistent= catch-up run right after boot if a slot was missed),
# and security-update-check.sh skips without touching the network unless
# the last real check is at least 115 minutes old (120 minus 5 of slack for
# timer jitter). So the next real check is the first quarter-hour slot at
# or after last check + 115 min, never
# earlier than now. A skipped activation doesn't shift that, unlike the
# old monotonic OnUnitActiveSec schedule.
next_check_epoch=""
due_epoch="$now_epoch"
min_gap=$(( CHECK_INTERVAL_SECONDS - THROTTLE_SLACK_SECONDS ))
if [ -n "$last_check_epoch" ] && [ $(( last_check_epoch + min_gap )) -gt "$now_epoch" ]; then
    due_epoch=$(( last_check_epoch + min_gap ))
fi
next_check_epoch=$(( (due_epoch + SLOT_SECONDS - 1) / SLOT_SECONDS * SLOT_SECONDS ))

# Right after boot a check is often already due (machine was off) and the
# timer will pick it up within one slot -- show that as "checking" rather
# than "overdue". Measured from when the timer unit started, not kernel
# boot: a LUKS prompt can sit for minutes before timers start.
timer_start_epoch=""
timer_start_ts="$(systemctl show -p ActiveEnterTimestamp --value security-update-check.timer 2>/dev/null)"
if [ -n "$timer_start_ts" ] && [ "$timer_start_ts" != "n/a" ]; then
    timer_start_epoch="$(date -d "$timer_start_ts" +%s 2>/dev/null)"
fi
awaiting_first_check=false
if [ -n "$timer_start_epoch" ] \
   && [ $(( now_epoch - timer_start_epoch )) -lt $(( SLOT_SECONDS + 60 )) ] \
   && { [ -z "$last_check_epoch" ] || [ "$last_check_epoch" -lt "$timer_start_epoch" ]; } \
   && [ "$due_epoch" -le "$now_epoch" ]; then
    awaiting_first_check=true
fi

last_check_rel="$(t update_genmon.unknown)"
next_check_rel="$(t update_genmon.unknown)"
[ -n "$last_check_epoch" ] && last_check_rel="$(minutes_label "$last_check_epoch" "$now_epoch")"
[ -n "$next_check_epoch" ] && next_check_rel="$(minutes_label "$next_check_epoch" "$now_epoch")"

phase=""
reboot_pending=false
overdue=false

unit_state="$(systemctl show -p ActiveState --value security-update-check.service 2>/dev/null)"
if [ "$unit_state" != active ] && [ "$unit_state" != activating ]; then
    # Also covers a user-triggered "Run updates now" run, which goes through
    # the separate security-update-check-force.service unit (see the log
    # dialog's button) rather than this timer-driven one.
    unit_state="$(systemctl show -p ActiveState --value security-update-check-force.service 2>/dev/null)"
fi
if [ "$unit_state" = active ] || [ "$unit_state" = activating ]; then
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
ICON_METERED=/usr/share/icons/Tango/24x24/status/network-idle.png
ICON_OK="$HOME/.local/share/update-genmon-icons/ok-check.png"

if [ "$phase" = installing ]; then
    img="$ICON_INSTALLING"
    tool="$(t update_genmon.installing)"
elif [ "$phase" = checking ]; then
    img="$ICON_CHECKING"
    if [ "$awaiting_first_check" = true ]; then
        tool="$(t update_genmon.waiting_first_check)"
    else
        tool="$(t update_genmon.checking)"
    fi
elif [ "$reboot_pending" = true ]; then
    img="$ICON_REBOOT"
    reboot_pkgs=""
    [ -r /var/run/reboot-required.pkgs ] && reboot_pkgs="$(paste -sd, /var/run/reboot-required.pkgs)"
    tool="$(t update_genmon.reboot_needed)"
    if [ -n "$reboot_pkgs" ]; then
        triggered_by="$(t update_genmon.reboot_triggered_by)"
        tool="${tool}&#10;${triggered_by//PKGS/$reboot_pkgs}"
    fi
    tool="${tool}&#10;$(t update_genmon.reboot_please)"
elif [ "$last_check_result" = network-error ]; then
    img="$ICON_NETWORK_ERROR"
    tool="$(t update_genmon.network_error)"
    [ -n "$last_check_reason" ] && tool="${tool}&#10;${last_check_reason}"
elif [ "$last_check_result" = interrupted ]; then
    # A milder icon than a real upgrade-error -- this is a transient,
    # self-healing event (the run got killed mid-way, almost always by a
    # shutdown/reboot), not an actual apt/dependency problem.
    img="$ICON_OVERDUE"
    tool="$(t update_genmon.interrupted)"
elif [ "$last_check_result" = upgrade-error ]; then
    img="$ICON_UPGRADE_ERROR"
    tool="$(t update_genmon.upgrade_error)"
    [ -n "$last_check_reason" ] && tool="${tool}&#10;${last_check_reason}"
elif [ "$last_check_result" = skipped-metered ]; then
    img="$ICON_METERED"
    tool="$(t update_genmon.skipped_metered)&#10;$(t update_genmon.skipped_metered_retry)"
elif [ "$overdue" = true ]; then
    img="$ICON_OVERDUE"
    tool="$(t update_genmon.overdue)"
else
    img="$ICON_OK"
    tool="$(t update_genmon.all_good)"
fi

if [ -n "$last_run_duration" ]; then
    last_check_line="$(t update_genmon.last_check_with_duration)"
    last_check_line="${last_check_line//REL/$last_check_rel}"
    last_check_line="${last_check_line//COUNT/$last_run_count}"
    last_check_line="${last_check_line//DURATION/$last_run_duration}"
else
    last_check_line="$(t update_genmon.last_check_no_duration)"
    last_check_line="${last_check_line//REL/$last_check_rel}"
    last_check_line="${last_check_line//COUNT/$last_run_count}"
fi
tool="${tool}&#10;${last_check_line}"
next_check_line="$(t update_genmon.next_check)"
tool="${tool}&#10;${next_check_line//REL/$next_check_rel}"

if [ -n "$apps_check_epoch" ]; then
    apps_check_rel="$(minutes_label "$apps_check_epoch" "$now_epoch")"
    case "$apps_check_result" in
        ok)
            apps_line="$(t update_genmon.apps_up_to_date)"
            apps_line="${apps_line//REL/$apps_check_rel}"
            ;;
        skipped-metered)
            apps_line="$(t update_genmon.apps_deferred_metered)"
            ;;
        *)
            apps_line="$(t update_genmon.apps_error)"
            ;;
    esac
    tool="${tool}&#10;${apps_line}"
fi

SECURITY_STATUS_IMG="$img"
SECURITY_STATUS_TOOL="$tool"
SECURITY_STATUS_CLICK="${SELF_DIR}/update-genmon-view-log.py"

# panel-status-genmon.sh sources this script to combine it with
# shutdown-timer-genmon.sh into one genmon plugin instance -- only emit
# standalone genmon output when run directly, not when sourced.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    echo "<img>${SECURITY_STATUS_IMG}</img>"
    echo "<tool>${SECURITY_STATUS_TOOL}</tool>"
    echo "<click>${SECURITY_STATUS_CLICK}</click>"
fi
