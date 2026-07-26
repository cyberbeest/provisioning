#!/bin/bash
set -euo pipefail

REPO_URL="https://github.com/cyberbeest/provisioning.git"
CLONE_DIR="$HOME/provisioning"

if ! command -v git >/dev/null 2>&1; then
  echo "Installing git..."
  # Fresh installs from DVD media leave a cdrom:// source in sources.list,
  # which has no Release file and makes apt-get update fail outright.
  sudo sed -i '/^deb cdrom:/ s/^/# /' /etc/apt/sources.list
  sudo apt-get -o DPkg::Lock::Timeout=60 update
  sudo apt-get -o DPkg::Lock::Timeout=60 install -y git
fi

if [ -d "$CLONE_DIR/.git" ]; then
  echo "Repo already exists at $CLONE_DIR, pulling latest..."
  git -C "$CLONE_DIR" pull
else
  echo "Cloning $REPO_URL into $CLONE_DIR..."
  git clone "$REPO_URL" "$CLONE_DIR"
fi

cd "$CLONE_DIR"
exec ./menu.sh
