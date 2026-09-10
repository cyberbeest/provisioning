#!/bin/bash
set -euo pipefail

REPO_URL="https://github.com/cyberbeest/provisioning.git"
CLONE_DIR="$HOME/provisioning-bleeding"
BRANCH="main"

# See beestify.sh for why -- same hardcoded-/home/cyberbeest risk applies here.
if [ "$(whoami)" != "cyberbeest" ]; then
  echo "Provisioning must run as the 'cyberbeest' user (currently: $(whoami))." >&2
  echo "Several scripts hardcode /home/cyberbeest and will misbehave under a" >&2
  echo "different username instead of failing cleanly. If this was a manual" >&2
  echo "install where you picked a different username, create/rename to a" >&2
  echo "'cyberbeest' account first." >&2
  exit 1
fi

# Fresh installs from DVD media leave a cdrom:// source in sources.list,
# which apt then blocks on (prompting to insert the disc) instead of just
# skipping. Unconditional and up front, not just inside the "installing
# git" block below -- see beestify.sh for why.
sudo sed -i '/^deb cdrom:/ s/^/# /' /etc/apt/sources.list

if ! command -v git >/dev/null 2>&1; then
  echo "Installing git..."
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
exec python3 ./run-gui.py
