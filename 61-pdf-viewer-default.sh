#!/bin/bash
# Sets Atril (MATE's document viewer, an Evince fork) as the default PDF
# handler. Atril already ships as a base desktop dependency, but the
# distro default association routes application/pdf to LibreOffice Draw
# instead, which is slow to open and editor-oriented rather than a viewer.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/61-pdf-viewer-default.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : setting Atril as default PDF viewer ==="
TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"

su - "$TARGET_USER" -c "xdg-mime default atril.desktop application/pdf"

echo "=== done ==="
