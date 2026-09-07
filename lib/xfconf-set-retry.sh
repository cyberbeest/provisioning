# Shared helper: retries an xfconf-query write with read-back verification.
#
# Why this exists: on the VM (1.9GB RAM, xfconfd still settling right after
# a fresh login or a kill+relaunch), a handful of `xfconf-query -s` calls
# issued back-to-back have been observed to silently no-op -- the command
# exits 0, but the property is left unset or at its prior stale value.
# Confirmed 2026-09-07 while building 90-vm-mode-overrides.sh: an
# immediately-following read-back of the same property came back missing
# or unchanged for some (not all) of a batch of writes, on a session that
# had just started. Re-issuing the same write shortly after has always
# succeeded, so this just retries with verification rather than trusting a
# single call's exit code.
#
# Usage: xfconf_set_retry <channel> <property> <expected-readback-or-empty> -- <xfconf-query -s args...>
# Pass "" for <expected-readback> to skip value verification (e.g. for a
# multi-value double array, where xfconf-query's LC_NUMERIC-formatted
# read-back isn't a reliable string match) -- the write is still retried a
# few times as insurance, just without a pass/fail check in between.
xfconf_set_retry() {
	local channel="$1" prop="$2" expected="$3"
	shift 3
	[ "$1" = "--" ] && shift
	local attempt got
	for attempt in 1 2 3 4 5; do
		xfconf-query -c "$channel" -p "$prop" "$@"
		if [ -z "$expected" ]; then
			return 0
		fi
		got="$(xfconf-query -c "$channel" -p "$prop" 2>/dev/null)"
		if [ "$got" = "$expected" ]; then
			return 0
		fi
		sleep 1
	done
	echo "WARNING: $channel $prop did not stick after retries (wanted '$expected', got '$got')" >&2
	return 1
}
