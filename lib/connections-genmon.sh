#!/bin/bash
# xfce4-genmon-plugin script: icon whose tooltip lists which apps currently
# hold established TCP connections and how many each, incoming and outgoing
# listed separately. A connection is incoming when its local port is one a
# local socket is listening on. Loopback connections are skipped (local IPC,
# not network traffic). Incoming should normally be zero (the firewall blocks
# it), so any incoming connection puts a red marker next to the icon.
# Sandboxed apps (firejail) are hidden from ss; connections_lookup.py
# identifies them via firejail --join, but only on a hover refresh (see
# below); the answers are cached per socket.
# Apps in a separate network namespace (firejail --net) are not visible here.

export LC_ALL=C

# i18n.sh (and its i18n/ catalog dir) is installed next to this script -- see
# lib/i18n.sh's own comment about resolving relative to BASH_SOURCE.
. "$(dirname "${BASH_SOURCE[0]}")/i18n.sh"

listen_ports=" $(ss -tlnH 2>/dev/null | awk '{n = split($4, a, ":"); print a[n]}' | sort -un | tr '\n' ' ')"

# One line per connection: "in|out <process name>", resolved via ss's users:()
# field, falling back to the owning uid for other users' sockets.
mapfile -t rows < <(
    ss -tnpeH state established 2>/dev/null |
    awk -v ports="$listen_ports" '
        $3 ~ /^(127\.|\[::1\])/ || $4 ~ /^(127\.|\[::1\])/ { next }
        {
            n = split($3, a, ":")
            dir = (index(ports, " " a[n] " ") > 0) ? "in" : "out"
            if (match($0, /\(\("[^"]+"/)) name = substr($0, RSTART + 3, RLENGTH - 4)
            else if (match($0, /uid:[0-9]+/)) name = "uid " substr($0, RSTART + 4, RLENGTH - 4)
            else name = "(unknown)"
            print dir " " name
        }' | sort | uniq -c | sort -rn
)

# Sandboxed apps show up as "uid <n>" here. connections_lookup.py names them
# from a per-socket cache. Filling the cache means joining every firejail
# sandbox, about a second of CPU, too much for every refresh on battery, so
# a scan only happens on gopanel's hover refresh (PANEL_HOVER=1, sent while
# the pointer is on the icon) or, if something is still unidentified, once a
# minute. Other refreshes just read what the cache has.
state_dir="${XDG_RUNTIME_DIR:-/tmp}"
if printf '%s\n' "${rows[@]}" | grep -qE ' (in|out) uid [0-9]{4,}$'; then
    scan_stamp="$state_dir/cyberbeest-connections-scan"
    last_scan=$(stat -c %Y "$scan_stamp" 2>/dev/null || echo 0)
    if [ -n "${PANEL_HOVER:-}" ] || [ $(( $(date +%s) - last_scan )) -ge 60 ]; then
        export CONNECTIONS_SCAN=1
        touch "$scan_stamp"
    fi
    if mapfile -t named < <(timeout 5 python3 "$(dirname "${BASH_SOURCE[0]}")/connections_lookup.py" 2>/dev/null |
        sort | uniq -c | sort -rn) && [ "${#named[@]}" -gt 0 ]; then
        rows=("${named[@]}")
    fi
fi

in_total=0
out_total=0
declare -A app_seen=()
unidentified=0
in_list=""
out_list=""
for line in "${rows[@]}"; do
    line=${line#"${line%%[![:space:]]*}"}
    count=${line%% *}
    rest=${line#* }
    dir=${rest%% *}
    name=${rest#* }
    [ "$name" = "(unknown)" ] && unidentified=1
    if [[ $name == "uid "* ]]; then
        uid=${name#uid }
        if [ "$uid" -ge 1000 ]; then
            unidentified=1
            name="$(t connections_genmon.unknown)"
        else
            name="$(getent passwd "$uid" | cut -d: -f1) ($(t connections_genmon.system_service))"
        fi
    fi
    app_seen[$name]=1
    if [ "$dir" = in ]; then
        in_total=$(( in_total + count ))
        in_list+="${count} ${name}"$'\n'
    else
        out_total=$(( out_total + count ))
        out_list+="${count} ${name}"$'\n'
    fi
done

# "15 outgoing connections:" / "1 incoming connection:"
count_header() {
    local key=connections_genmon.$1_n
    [ "$2" -eq 1 ] && key=connections_genmon.$1_1
    local msg
    msg="$(t "$key")"
    printf '%s' "${msg//%d/$2}"
}

total=$(( in_total + out_total ))
if [ "$total" -eq 0 ]; then
    tooltip="$(t connections_genmon.none)"
else
    tooltip=""
    if [ "$in_total" -gt 0 ]; then
        tooltip+="⬇ $(count_header in "$in_total")"$'\n'"${in_list}"$'\n'
    fi
    if [ "$out_total" -gt 0 ]; then
        tooltip+="$(count_header out "$out_total")"$'\n'"${out_list%$'\n'}"
    else
        tooltip+="$(count_header out 0)"
    fi
fi

# First time an app talks this session: connections_lookup.py --notify pops up
# "<App> is communicating with the Internet" (option in Settings, on by
# default) and leaves a stamp that makes the icon sparkle for a moment.
sparkle=""
settings_file="$HOME/.config/cyberbeest/connections/settings.json"
if ! grep -qs '"notify": *false' "$settings_file"; then
    if [ "$total" -gt 0 ]; then
        python3 "$(dirname "${BASH_SOURCE[0]}")/connections_lookup.py" --notify >/dev/null 2>&1 &
    fi
    sparkle_stamp="$state_dir/cyberbeest-connections-sparkle"
    sparkle_at=$(stat -c %Y "$sparkle_stamp" 2>/dev/null || echo 0)
    [ $(( $(date +%s) - sparkle_at )) -lt 25 ] && sparkle="<span size='large'>✨</span>"
fi

marker=""
[ "$in_total" -gt 0 ] && marker="<span foreground='red' weight='bold'>⬇</span>"
# Number of apps with connections as a small number beside the globe, like a
# messenger's unread badge; nothing when there are none. It only changes while
# every connection is identified (otherwise two sandboxed apps would count as
# one "unknown"), so it may lag a minute behind but is never wrong.
badge_file="$state_dir/cyberbeest-connections-badge"
if [ "$unidentified" -eq 0 ]; then
    apps=${#app_seen[@]}
    echo "$apps" > "$badge_file" 2>/dev/null
else
    apps=$(cat "$badge_file" 2>/dev/null)
fi
badge=""
[ "${apps:-0}" -gt 0 ] && badge="<span size='small' weight='bold'>${apps}</span>"
echo "<txt><span size='small'>&#8202;</span>${marker}<span size='x-large'>🌐</span>${sparkle}${badge}<span size='small'>&#8202;</span></txt>"
echo "<tool>${tooltip}</tool>"
echo "<txtclick>$HOME/.local/bin/connections-window.py</txtclick>"
