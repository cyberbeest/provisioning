#!/usr/bin/env bash
# Stops the daemon FIRST via its own `stop` command -- per its docs this
# gracefully terminates background sessions, so workers exit cleanly rather
# than looking like a crash. (Killing worker processes directly while the
# daemon is still alive doesn't work: the daemon's job is to keep workers
# alive, so it just respawns anything that dies unexpectedly.)
#
# Only after the daemon is gone do we clean up any leftover claude processes
# -- with no daemon left to resurrect them, that's now safe.
#
# Matches only the actual claude binaries (not terminal emulators or this
# script's own path, which happens to contain "claude" too) -- terminal
# windows running `bash -ic claude` close on their own once the inner
# claude process they were wrapping exits, no need to kill them directly.
set -uo pipefail

MATCH='\.local/bin/claude|\.local/share/claude/versions/'

echo "Stopping claude daemon..."
claude daemon stop --any
sleep 2

echo "Verifying nothing claude-related is left..."
remaining=$(pgrep -f "$MATCH" | grep -v -w "$$")
if [ -n "$remaining" ]; then
    echo "Still running, sending SIGKILL: $remaining"
    kill -9 $remaining 2>/dev/null
    sleep 1
    remaining=$(pgrep -f "$MATCH" | grep -v -w "$$")
fi

if [ -z "$remaining" ]; then
    echo "Confirmed: no claude processes running."
else
    echo "WARNING: still running: $remaining"
fi
