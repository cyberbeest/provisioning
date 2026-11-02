#!/bin/bash
# Swap indicator panel item (genmon plugin-231, added by enable-swap-indicator.sh).
# A red square that lights up whenever anything is swapped in or out (the
# pswpin/pswpout counters in /proc/vmstat moved since the last run), then
# shrinks and fades until it disappears about FADE seconds after the last
# swap activity. Invisible (empty output) while the level is 0.
# Level is kept in $XDG_RUNTIME_DIR/swap-indicator.state as
# "<level> <epoch-microseconds> <pswpin+pswpout> <last-swap-event-microseconds>"; decay uses elapsed wall time,
# so the genmon refresh jitter doesn't change the fade speed.
FADE=20
LEVELS=24
ICON_DIR="$HOME/.local/share/cyberbeest-swap-indicator"
STATE="${XDG_RUNTIME_DIR:-/tmp}/swap-indicator.state"

pin=0 pout=0
while read -r k v; do
	case $k in pswpin) pin=$v ;; pswpout) pout=$v; break ;; esac
done < /proc/vmstat
total=$((pin + pout))
now=${EPOCHREALTIME/[.,]/}   # microseconds

level=0 last=$now prev=$total event=$now
[ -r "$STATE" ] && read -r level last prev event < "$STATE"
[[ $level =~ ^[0-9]+$ && $last =~ ^[0-9]+$ && $prev =~ ^[0-9]+$ && $event =~ ^[0-9]+$ ]] || { level=0; last=$now; prev=$total; event=$now; }

# level is in millionths (0..1000000)
level=$((level - (now - last) / FADE))
[ "$level" -lt 0 ] && level=0
delta=$((total - prev))
# A long gap means we were not running (screen locked): that swapping is not news.
[ $((now - last)) -gt 5000000 ] && delta=0
if [ "$delta" -gt 0 ]; then
	event=$now
	# Any swap activity gives at least 60%; heavy activity (>=2000 pages per
	# refresh) goes to full.
	boost=$((600000 + 400000 * (delta > 2000 ? 2000 : delta) / 2000))
	[ "$boost" -gt "$level" ] && level=$boost
fi
echo "$level $now $total $event" > "$STATE"

[ "$level" -gt 0 ] || exit 0
n=$(( (level * LEVELS + 999999) / 1000000 ))
[ "$n" -lt 1 ] && n=1
printf '<img>%s/swap-%02d.png</img>\n' "$ICON_DIR" "$n"

# RAM and swap lines as in mem-liquid's tooltip. RAM shows both readings of
# "used": excluding mmapped file cache (total - available) and including it
# (total - free - buffers - passive cache), as "low-high".
declare -A m
while read -r k v _; do m[${k%:}]=$v; done < /proc/meminfo
passive=$(( ${m[Cached]:-0} - ${m[Mapped]:-0} - ${m[Shmem]:-0} ))
[ "$passive" -lt 0 ] && passive=0
ram_used=$(( ${m[MemTotal]:-0} - ${m[MemFree]:-0} - ${m[Buffers]:-0} - passive ))
[ "$ram_used" -lt 0 ] && ram_used=0
ram_used2=$(( ${m[MemTotal]:-0} - ${m[MemAvailable]:-0} ))
[ "$ram_used2" -lt 0 ] && ram_used2=0
if [ "$ram_used2" -le "$ram_used" ]; then lo=$ram_used2 hi=$ram_used; else lo=$ram_used hi=$ram_used2; fi
swap_total=${m[SwapTotal]:-0}
swap_used=$(( swap_total - ${m[SwapFree]:-0} ))
gib() { local t=$(( ($1 * 10 + 524288) / 1048576 )); echo "$((t / 10)).$((t % 10))"; }
pct() { echo $(( ($1 * 100 + $2 / 2) / $2 )); }
range() { if [ "$1" = "$2" ]; then echo "$1"; else echo "$1-$2"; fi; }
tip="Swap Indicator&#10;RAM: $(range "$(pct "$lo" "${m[MemTotal]:-1}")" "$(pct "$hi" "${m[MemTotal]:-1}")")% used ($(range "$(gib "$lo")" "$(gib "$hi")") / $(gib "${m[MemTotal]:-0}") GiB)"
if [ "$swap_total" -gt 0 ]; then
	tip+="&#10;Swap: $(pct "$swap_used" "$swap_total")% used ($(gib "$swap_used") / $(gib "$swap_total") GiB)"
fi
ago() {
	local n=$1 unit=second
	if [ "$n" -ge 86400 ]; then n=$((n / 86400)); unit=day
	elif [ "$n" -ge 3600 ]; then n=$((n / 3600)); unit=hour
	elif [ "$n" -ge 60 ]; then n=$((n / 60)); unit=minute
	fi
	[ "$n" -eq 1 ] && echo "1 $unit ago" || echo "$n ${unit}s ago"
}
tip+="&#10;Last swap event: $(ago $(( (now - event) / 1000000 )))"
echo "<tool>$tip</tool>"
