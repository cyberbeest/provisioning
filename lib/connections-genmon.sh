#!/bin/bash
# xfce4-genmon-plugin script: icon whose tooltip lists which apps currently
# hold established TCP connections and how many each, incoming and outgoing
# listed separately. A connection is incoming when its local port is one a
# local socket is listening on. Loopback connections are skipped (local IPC,
# not network traffic). Incoming should normally be zero (the firewall blocks
# it), so any incoming connection puts a red marker next to the icon.
# Sandboxed apps (firejail) are hidden from ss; the click-through window
# identifies them, this icon only says "unknown".
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

in_total=0
out_total=0
in_list=""
out_list=""
for line in "${rows[@]}"; do
    line=${line#"${line%%[![:space:]]*}"}
    count=${line%% *}
    rest=${line#* }
    dir=${rest%% *}
    name=${rest#* }
    if [[ $name == "uid "* ]]; then
        uid=${name#uid }
        if [ "$uid" -ge 1000 ]; then
            name="$(t connections_genmon.unknown)"
        else
            name="$(getent passwd "$uid" | cut -d: -f1) ($(t connections_genmon.system_service))"
        fi
    fi
    if [ "$dir" = in ]; then
        in_total=$(( in_total + count ))
        in_list+="${name}: ${count}"$'\n'
    else
        out_total=$(( out_total + count ))
        out_list+="${name}: ${count}"$'\n'
    fi
done

total=$(( in_total + out_total ))
if [ "$total" -eq 0 ]; then
    tooltip="$(t connections_genmon.none)"
else
    tooltip=""
    if [ "$in_total" -gt 0 ]; then
        tooltip+="⬇ $(t connections_genmon.incoming) ($in_total)"$'\n'"${in_list}"$'\n'
    fi
    tooltip+="$(t connections_genmon.outgoing) ($out_total)"
    [ -n "$out_list" ] && tooltip+=$'\n'"${out_list%$'\n'}"
fi

marker=""
[ "$in_total" -gt 0 ] && marker="<span foreground='red' weight='bold'>⬇</span>"
echo "<txt><span size='small'>&#8202;</span>${marker}<span size='x-large'>🌐</span><span size='small'>&#8202;</span></txt>"
echo "<tool>${tooltip}</tool>"
echo "<txtclick>$HOME/.local/bin/connections-window.py</txtclick>"
