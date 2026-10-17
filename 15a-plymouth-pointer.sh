#!/bin/bash
# Mouse pointer on the boot screen / LUKS password prompt: installs the patched
# Plymouth build (experimental/enable-plymouth-pointer.sh, see
# experimental/lib/plymouth-pointer/README.md).
#
# On by default. The profile dialog's "Boot screen" checkbox
# (PROVISIONING_PLYMOUTH_POINTER) turns it off; unticked on a machine that
# already has the pointer build puts stock Plymouth back. A missing profile
# file or variable means "on", the behavior of a standalone run.
#
# The patched files are built for exactly one Plymouth version. On any other
# version this script skips with a message instead of failing the run.
# Idempotent: safe to re-run (also after an 'apt upgrade' of plymouth).
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/15a-plymouth-pointer.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : Plymouth mouse pointer ==="

PROVISIONING_PLYMOUTH_POINTER="yes"
if [ -f "$DIR/.provisioning-profile.env" ]; then
    # shellcheck disable=SC1091
    . "$DIR/.provisioning-profile.env"
fi

LIB=/usr/lib/x86_64-linux-gnu
installed=no
grep -aq ply_pointer_new "$LIB/libply-splash-core.so.5.0.0" 2>/dev/null && installed=yes

if [ "$PROVISIONING_PLYMOUTH_POINTER" = "no" ]; then
    if [ "$installed" = yes ]; then
        echo "--- Pointer turned off in the provisioning profile -- restoring stock Plymouth ---"
        bash "$DIR/experimental/disable-plymouth-pointer.sh"
    else
        echo "--- Pointer turned off in the provisioning profile -- nothing to do ---"
    fi
    exit 0
fi

ver="$(dpkg-query -W -f='${Version}' plymouth 2>/dev/null)"
if [ "$ver" != "24.004.60-5" ]; then
    echo "--- plymouth is '$ver', the pointer build is for 24.004.60-5 -- skipping ---"
    exit 0
fi

bash "$DIR/experimental/enable-plymouth-pointer.sh" || echo "WARNING: pointer install failed (stock Plymouth was restored); boot works without it"
exit 0
