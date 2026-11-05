#!/bin/bash
# Blocks onnxruntime's built-in telemetry. The prebuilt wheels (since about
# 1.31) carry Microsoft's 1DS/OneCollector client, which a few seconds after
# start sends events to mobile.events.data.microsoft.com. ort.disable_telemetry_events()
# does not cover it. Butler (69a-butler.sh) and the TTS experiment use
# onnxruntime, so without this a menu search shows "Butler is communicating
# with the United States" and data really goes to Microsoft.
#
# Pointing the host name at loopback makes the connection fail locally and
# keeps it out of the network icon (loopback is skipped). The name is only
# used by this telemetry client.
# Must be run as root. Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/69b-block-onnxruntime-telemetry.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : blocking onnxruntime telemetry ==="
HOST=mobile.events.data.microsoft.com
if grep -qw "$HOST" /etc/hosts; then
	echo "already in /etc/hosts"
else
	printf '\n# Cyberbeest: onnxruntime telemetry (69b-block-onnxruntime-telemetry.sh)\n127.0.0.1 %s\n::1 %s\n' "$HOST" "$HOST" >> /etc/hosts
fi
getent ahosts "$HOST"
echo "=== done ==="
