#!/bin/bash
# Installs the Cyberbeest crypto wallet set: Sparrow (Bitcoin) and Feather
# (Monero). Deliberately no Ethereum/multi-coin wallet -- the only decent
# options are browser extensions (MetaMask/Rabby), which don't fit a
# desktop-native, curated lineup; see memory cyberbeest_crypto_wallet_lineup.
#
# - Sparrow: Bitcoin-only, no apt repo -- ships signed .deb releases on
#   GitHub. Downloaded and verified against Craig Raw's PGP key (detached
#   signature over a manifest.txt listing each release asset's SHA256) before
#   install, since nothing else vouches for this download.
# - Feather: Monero-only, packaged in Debian proper (Cryptocoin Team) but
#   only landed in trixie-backports so far, not trixie main. The .deb does
#   NOT bundle Tor (only the upstream AppImage does) -- it Recommends the
#   system `tor` package instead, which apt pulls in and enables by default,
#   giving Feather a SOCKS proxy at 127.0.0.1:9050. Optional I2P (Settings ->
#   Network -> Proxy -> i2p), so no extra config needed here for its privacy
#   properties -- apt/dpkg's own signature chain covers its authenticity.
#
# Depends on trixie-backports already being enabled (03-secure-messengers.sh
# / install-secure-messengers.sh does this for telegram-desktop; idempotent
# either way if this script runs first).
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/36-crypto-wallets.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing crypto wallets ==="

echo "--- Enabling trixie-backports (needed for feather-wallet) ---"
BACKPORTS_LIST=/etc/apt/sources.list.d/cyberbeest-backports.list
# Check all apt source files, not just our own -- registering the same
# Release target twice (e.g. it's already in sources.list from the Debian
# installer) makes apt log "configured multiple times" warnings and floods
# the security-update-check log with repeated "delayed item" retries.
if grep -rqs "^deb .*trixie-backports" /etc/apt/sources.list /etc/apt/sources.list.d/*.list 2>/dev/null; then
    echo "trixie-backports already enabled, skipping"
elif [ ! -e "$BACKPORTS_LIST" ]; then
    echo "deb http://deb.debian.org/debian trixie-backports main contrib non-free non-free-firmware" > "$BACKPORTS_LIST"
    echo "Enabled trixie-backports via $BACKPORTS_LIST"
else
    echo "trixie-backports already enabled, skipping"
fi

echo "--- apt-get update ---"
apt-get -o DPkg::Lock::Timeout=60 update

echo "--- Installing Feather (Monero) from trixie-backports ---"
apt-get -o DPkg::Lock::Timeout=60 install -y -t trixie-backports feather-wallet

echo "--- Installing Sparrow (Bitcoin) ---"
SPARROW_VERSION="2.5.3"
SPARROW_DEB="sparrowwallet_${SPARROW_VERSION}-1_amd64.deb"
SPARROW_BASE_URL="https://github.com/sparrowwallet/sparrow/releases/download/${SPARROW_VERSION}"
SPARROW_FINGERPRINT="D4D0D3202FC06849A257B38DE94618334C674B40"

if dpkg -s sparrowwallet >/dev/null 2>&1 && \
   dpkg -s sparrowwallet 2>/dev/null | grep -q "^Version: ${SPARROW_VERSION}"; then
    echo "Sparrow ${SPARROW_VERSION} already installed, skipping"
else
    WORKDIR="$(mktemp -d)"
    trap 'rm -rf "$WORKDIR"' EXIT

    echo "Downloading Sparrow ${SPARROW_VERSION} .deb, manifest, and signature..."
    curl -fsSL -o "$WORKDIR/$SPARROW_DEB" "$SPARROW_BASE_URL/$SPARROW_DEB"
    curl -fsSL -o "$WORKDIR/sparrow-${SPARROW_VERSION}-manifest.txt" \
        "$SPARROW_BASE_URL/sparrow-${SPARROW_VERSION}-manifest.txt"
    curl -fsSL -o "$WORKDIR/sparrow-${SPARROW_VERSION}-manifest.txt.asc" \
        "$SPARROW_BASE_URL/sparrow-${SPARROW_VERSION}-manifest.txt.asc"

    echo "Verifying manifest signature against Craig Raw's key ($SPARROW_FINGERPRINT)..."
    export GNUPGHOME="$WORKDIR/gnupg"
    mkdir -m 700 "$GNUPGHOME"
    curl -fsSL https://keybase.io/craigraw/pgp_keys.asc | gpg --batch --import
    FETCHED_FPR="$(gpg --batch --with-colons --fingerprint craig@sparrowwallet.com \
        | awk -F: '/^fpr:/ { print $10; exit }')"
    if [ "$FETCHED_FPR" != "$SPARROW_FINGERPRINT" ]; then
        echo "ERROR: fetched key fingerprint ($FETCHED_FPR) does not match pinned fingerprint ($SPARROW_FINGERPRINT) -- aborting" >&2
        exit 1
    fi
    gpg --batch --verify "$WORKDIR/sparrow-${SPARROW_VERSION}-manifest.txt.asc" \
        "$WORKDIR/sparrow-${SPARROW_VERSION}-manifest.txt"

    echo "Verifying .deb SHA256 against the signed manifest..."
    EXPECTED_SHA256="$(grep "\*$SPARROW_DEB\$" "$WORKDIR/sparrow-${SPARROW_VERSION}-manifest.txt" | awk '{print $1}')"
    if [ -z "$EXPECTED_SHA256" ]; then
        echo "ERROR: $SPARROW_DEB not found in signed manifest -- aborting" >&2
        exit 1
    fi
    ACTUAL_SHA256="$(sha256sum "$WORKDIR/$SPARROW_DEB" | awk '{print $1}')"
    if [ "$EXPECTED_SHA256" != "$ACTUAL_SHA256" ]; then
        echo "ERROR: $SPARROW_DEB SHA256 mismatch (expected $EXPECTED_SHA256, got $ACTUAL_SHA256) -- aborting" >&2
        exit 1
    fi
    echo "Signature and checksum verified."

    apt-get -o DPkg::Lock::Timeout=60 install -y "$WORKDIR/$SPARROW_DEB"
fi

echo "=== done ==="
