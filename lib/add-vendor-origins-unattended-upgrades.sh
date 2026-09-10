#!/bin/bash
# Adds the Signal, Element, and VirtualBox vendor apt repos to
# unattended-upgrades' allowlist, so their updates install automatically
# like Debian's own instead of sitting there until manually clicked in
# GNOME Software/Cyberbeest Package Manager.
#
# unattended-upgrades only auto-applies packages whose repo Origin/Codename
# match Unattended-Upgrade::Origins-Pattern. Signal, Element, and VirtualBox
# ship their own vendor repos (added by cyberbeest-pkg-helper.sh setup-repo),
# which were never in that allowlist -- that's why their updates showed up
# as manual-only in GNOME Software, regardless of whether they were security
# fixes or not. VirtualBox was added to provisioning later than
# Signal/Element and got missed here initially -- confirmed via
# download.virtualbox.org/virtualbox/debian/dists/trixie/Release:
# "Origin: Oracle Corporation", "Codename: trixie".
#
# Written as its own fragment file rather than editing
# /etc/apt/apt.conf.d/50unattended-upgrades directly, since that file
# already has local customizations (broadened beyond security-only) that
# this script shouldn't disturb or fight with.
#
# Run with sudo:
#   sudo bash ~/provisioning/lib/add-vendor-origins-unattended-upgrades.sh (normally invoked via ../06-vendor-origins-unattended-upgrades.sh)

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/add-vendor-origins-unattended-upgrades.log"
exec > >(tee -a "$LOG") 2>&1
echo "=== $(date '+%Y-%m-%d %H:%M:%S') add-vendor-origins-unattended-upgrades.sh ==="

# Signal's Release file has a genuinely odd (but real) Origin field: ". xenial"
# -- a quirk in Signal's own repo metadata, not a typo introduced here.
cat >/etc/apt/apt.conf.d/52unattended-upgrades-vendor-messengers <<'EOF'
// Managed by provisioning/lib/add-vendor-origins-unattended-upgrades.sh
// Lets Signal Desktop and Element updates apply automatically, same as
// Debian's own packages.
Unattended-Upgrade::Origins-Pattern {
    "origin=. xenial,codename=xenial";      // Signal Desktop (their Release file really does say "Origin: . xenial")
    "origin=riot.im,codename=default";      // Element Desktop
};
EOF

echo "Wrote /etc/apt/apt.conf.d/52unattended-upgrades-vendor-messengers"

cat >/etc/apt/apt.conf.d/53unattended-upgrades-vendor-virtualbox <<'EOF'
// Managed by provisioning/lib/add-vendor-origins-unattended-upgrades.sh
// Lets VirtualBox updates apply automatically, same as Debian's own
// packages -- Oracle's repo isn't Debian's, so without this its updates
// sit as manual-only, which matters for timely security patches.
Unattended-Upgrade::Origins-Pattern {
    "origin=Oracle Corporation,codename=trixie";   // VirtualBox (download.virtualbox.org)
};
EOF

echo "Wrote /etc/apt/apt.conf.d/53unattended-upgrades-vendor-virtualbox"

echo "--- Dry-run test ---"
unattended-upgrades --dry-run --debug 2>&1 | grep -iE 'signal|element|virtualbox|oracle|Origins-Pattern|Allowed origins' || true

echo "=== done ==="
