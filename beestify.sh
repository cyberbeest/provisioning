#!/bin/bash
set -euo pipefail

REPO_URL="https://github.com/cyberbeest/provisioning.git"
CLONE_DIR="$HOME/provisioning"
BRANCH="stable"

# The NN-*.sh scripts that used to hardcode /home/cyberbeest instead of
# $HOME (00-locale-keyboard-timezone.sh, 18-desktop-background.sh,
# 21-default-password-nag.sh, 90-vm-mode-overrides.sh) have since been
# fixed to substitute $TARGET_HOME dynamically -- confirmed 2026-09-10, see
# memory: cyberbeest_kvm_provisioning_track. Provisioning now runs under
# whatever username invokes it; this used to be a hard `exit 1` gate
# requiring the account be named "cyberbeest" specifically, back when that
# assumption was still true.
#
# Not an exhaustive guarantee across all NN-*.sh scripts (164 of them,
# not all individually re-audited for this) -- if something still
# misbehaves under a non-"cyberbeest" username, it's a bug in that specific
# script, not something this chokepoint should paper over by blocking a
# legitimate different-username install.
if [ "$(whoami)" != "cyberbeest" ]; then
  echo "Note: running as '$(whoami)', not 'cyberbeest'. Most scripts adapt to" >&2
  echo "whatever user invokes them; if something misbehaves specifically" >&2
  echo "because of the username, please report it." >&2
fi

# Fresh installs from DVD media leave a cdrom:// source in sources.list,
# which apt then blocks on (prompting to insert the disc) instead of just
# skipping. Unconditional and up front, not just inside the "installing
# git" block below: git may already be present (e.g. pulled in by
# cyberbeest-bootstrap.sh's own curl install) while zenity, installed later
# by run-gui.py, still isn't -- that apt-get call has no cdrom handling of
# its own and was hanging on the disc prompt with the old gated version of
# this fix.
sudo sed -i '/^deb cdrom:/ s/^/# /' /etc/apt/sources.list

if ! command -v git >/dev/null 2>&1; then
  echo "Installing git..."
  sudo apt-get -o DPkg::Lock::Timeout=60 update
  sudo apt-get -o DPkg::Lock::Timeout=60 install -y git
fi

# Tracks "stable" rather than "main": main is where every fix lands the
# moment it's made (see beestify-bleeding.sh for that), stable only gets
# fast-forwarded to a main commit once it's actually been validated
# end-to-end on a fresh install. This is our own repo, not a third-party
# dependency, so the trust boundary is "do you trust cyberbeest.com/this
# GitHub account" either way -- the stable/bleeding split is about install
# reliability, not about pinning against a supply-chain risk.
if [ -d "$CLONE_DIR/.git" ]; then
  echo "Repo already exists at $CLONE_DIR, pulling latest $BRANCH..."
  git -C "$CLONE_DIR" fetch origin "$BRANCH"
  git -C "$CLONE_DIR" checkout "$BRANCH"
  git -C "$CLONE_DIR" merge --ff-only "origin/$BRANCH"
else
  echo "Cloning $REPO_URL ($BRANCH) into $CLONE_DIR..."
  git clone -b "$BRANCH" "$REPO_URL" "$CLONE_DIR"
fi

cd "$CLONE_DIR"
exec python3 ./run-gui.py
