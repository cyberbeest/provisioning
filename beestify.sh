#!/bin/bash
set -euo pipefail

REPO_URL="https://github.com/cyberbeest/provisioning.git"
CLONE_DIR="$HOME/provisioning"
BRANCH="stable"

if ! command -v git >/dev/null 2>&1; then
  echo "Installing git..."
  # Fresh installs from DVD media leave a cdrom:// source in sources.list,
  # which has no Release file and makes apt-get update fail outright.
  sudo sed -i '/^deb cdrom:/ s/^/# /' /etc/apt/sources.list
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
