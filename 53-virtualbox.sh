#!/bin/bash
# Installs VirtualBox on the host, so every machine can run a same-OS
# sandbox VM for extra isolation when running an untrusted app (the guest
# VM itself -- what actually gets installed inside it, and when -- is a
# separate, later step; this script only gets the hypervisor itself onto
# the machine).
#
# Uses Oracle's own apt repository, not a Debian package: Debian dropped
# its own "virtualbox" package years ago (licensing/maintenance friction --
# confirmed absent from trixie's main/contrib/non-free-firmware via
# `apt-cache search virtualbox`), so Oracle's repo is the only source left
# for a real build on Debian 13. This pulls in Oracle's PUEL license
# (accepted non-interactively via apt) rather than a fully open-source
# package -- a real tradeoff, but there's no alternative for VirtualBox
# specifically on trixie.
# See lib/cyberbeest-pkg-helper.sh's `virtualbox` case for the repo setup.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/53-virtualbox.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing VirtualBox ==="

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"

echo "--- Setting up the Oracle VirtualBox apt repo ---"
"$DIR/lib/cyberbeest-pkg-helper.sh" setup-repo virtualbox

echo "--- apt-get update ---"
apt-get -o DPkg::Lock::Timeout=60 update

echo "--- Installing virtualbox-7.2 ---"
# Recommends left on (no --no-install-recommends): virtualbox-7.2 only
# Recommends, rather than Depends, the DKMS build chain it actually needs
# on first install (gcc/make/build-essential, linux-headers-amd64) --
# without them apt would happily "succeed" while vboxdrv silently fails to
# build.
apt-get -o DPkg::Lock::Timeout=60 install -y virtualbox-7.2

echo "--- Adding $TARGET_USER to the vboxusers group ---"
usermod -aG vboxusers "$TARGET_USER"

echo "--- Blacklisting KVM (conflicts with VirtualBox's use of VT-x/AMD-V) ---"
# KVM and VirtualBox can't both hold hardware virtualization at once -- if
# kvm_intel/kvm_amd/kvm are loaded (common: many kernels auto-load them on
# any VT-x/AMD-V-capable CPU regardless of whether anything's actually
# using KVM), VirtualBox's own VMs fail to start with
# VERR_VMX_IN_VMX_ROOT_MODE. Confirmed hitting this on the dev machine and
# on a real test machine after this exact provisioning step. Unloaded
# immediately below, and blacklisted so it doesn't come back on the next
# boot (or after a kernel update re-triggers the autoload).
for mod in kvm_intel kvm_amd kvm; do
	modprobe -r "$mod" 2>/dev/null || true
done
cat > /etc/modprobe.d/blacklist-kvm.conf <<'EOF'
# Disabled permanently: conflicts with VirtualBox's use of VT-x/AMD-V
# (VirtualBox can't run VMX/SVM root mode while KVM holds it).
blacklist kvm_intel
blacklist kvm_amd
blacklist kvm
EOF
update-initramfs -u

echo "=== $(date) : done ==="
