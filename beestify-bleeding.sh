#!/bin/bash
set -euo pipefail

REPO_URL="https://github.com/cyberbeest/provisioning.git"
CLONE_DIR="$HOME/provisioning-bleeding"
BRANCH="main"

if ! command -v git >/dev/null 2>&1; then
  echo "Installing git..."
  # Fresh installs from DVD media leave a cdrom:// source in sources.list,
  # which has no Release file and makes apt-get update fail outright.
  sudo sed -i '/^deb cdrom:/ s/^/# /' /etc/apt/sources.list
  sudo apt-get -o DPkg::Lock::Timeout=60 update
  sudo apt-get -o DPkg::Lock::Timeout=60 install -y git
fi

# Bleeding-edge counterpart to beestify.sh: tracks main, where every fix
# lands the moment it's made, instead of stable (only fast-forwarded to a
# validated main commit). Cloned into a separate directory so both can
# coexist on the same machine without fighting over which branch is checked
# out. This is our own repo, not a third-party dependency, so the trust
# boundary is "do you trust cyberbeest.com/this GitHub account" either way --
# the stable/bleeding split is about install reliability, not about pinning
# against a supply-chain risk.
if [ -d "$CLONE_DIR/.git" ]; then
  echo "Repo already exists at $CLONE_DIR, pulling latest $BRANCH..."
  git -C "$CLONE_DIR" checkout "$BRANCH"
  git -C "$CLONE_DIR" pull
else
  echo "Cloning $REPO_URL ($BRANCH) into $CLONE_DIR..."
  git clone -b "$BRANCH" "$REPO_URL" "$CLONE_DIR"
fi

cd "$CLONE_DIR"
exec ./menu.sh
