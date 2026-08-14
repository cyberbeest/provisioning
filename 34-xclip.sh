#!/bin/bash
# Installs xclip -- Claude Code's Linux clipboard-image paste shells out to
# xclip/xsel to read image bytes off the X clipboard. Without it, pasting an
# image into the terminal silently does nothing.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/34-xclip.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing xclip ==="
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y xclip

echo "=== done ==="
