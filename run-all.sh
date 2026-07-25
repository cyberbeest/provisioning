#!/bin/bash
# Runs every provisioning script in this directory in numeric order.
# Each NN-*.sh script is expected to be idempotent and self-logging.
set -euo pipefail
cd "$(dirname "$0")"

for script in [0-9][0-9]-*.sh; do
	echo "=== running $script ==="
	bash "$script"
done

# Best-effort: run-all.sh may be invoked headlessly (no X session), so a
# missing/failing panel reload here is not an error.
if command -v xfce4-panel >/dev/null 2>&1; then
	echo "Reloading xfce4-panel to pick up new/changed desktop entries..."
	xfce4-panel -r || true
fi
