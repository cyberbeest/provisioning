#!/bin/bash
# Runs every provisioning script in this directory in numeric order.
# Each NN-*.sh script is expected to be idempotent and self-logging.
set -euo pipefail
cd "$(dirname "$0")"

for script in [0-9][0-9]-*.sh; do
	echo "=== running $script ==="
	bash "$script"
done
