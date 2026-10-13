#!/bin/bash
# Builds gopanel + helpers and (with --publish) uploads them as a pinned release artifact.
#   release.sh              build the tarball, print its hash (nothing leaves this machine)
#   release.sh --publish    also upload to cyberbeest.com/gopanel/ and update the pins in
#                           ../../69-cyberbeest-panel.sh (commit that change to roll it out)
# The tarball is reproducible for the same binaries (sorted, fixed mtime/owner, gzip -n) and
# named after its own hash: machines fetch gopanel-<first 12 hex of sha256>.tar.gz and verify
# the full SHA-256 pinned in 69-cyberbeest-panel.sh, so a changed download host cannot swap it.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
INSTALLER="$(cd ../.. && pwd)/69-cyberbeest-panel.sh"
HOST="hosting244871@hosting244871.a4415.netcup.net"
REMOTE_DIR="cyberbeest.com/httpdocs/gopanel"
BASE_URL="https://cyberbeest.com/gopanel"

./build.sh
VERSION="$(./gopanel version | awk '{print $2}')"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/gopanel/helpers"
install -m 755 gopanel "$STAGE/gopanel/gopanel"
for d in helpers/*/; do
	n="$(basename "$d")"
	install -D -m 755 "helpers/$n/$n" "$STAGE/gopanel/helpers/$n/$n"
done
echo "$VERSION" > "$STAGE/gopanel/VERSION"
# the binaries embed third-party Go modules (BSD/MIT/Apache): ship their licence texts, and ours
{
	echo "gopanel is part of Cyberbeest (see LICENSE). It is built with these Go modules:"
	go list -deps -f '{{with .Module}}{{.Path}} {{.Version}} {{.Dir}}{{end}}' ./... 2>/dev/null | sort -u | while read -r path ver dir; do
		[ -n "$dir" ] && [ "$path" != "gopanel" ] || continue
		for f in "$dir"/LICENSE* "$dir"/COPYING*; do
			[ -f "$f" ] || continue
			printf '\n================ %s %s ================\n' "$path" "$ver"
			cat "$f"
			break
		done
	done
} > "$STAGE/gopanel/THIRD_PARTY_LICENSES.txt"
cp ../../LICENSE "$STAGE/gopanel/LICENSE"
chmod 644 "$STAGE/gopanel/VERSION" "$STAGE/gopanel/THIRD_PARTY_LICENSES.txt" "$STAGE/gopanel/LICENSE"

TARBALL="$STAGE/gopanel.tar.gz"
tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner -C "$STAGE" -cf - gopanel | gzip -9n > "$TARBALL"
SHA="$(sha256sum "$TARBALL" | cut -d' ' -f1)"
BYTES="$(stat -c %s "$TARBALL")"
NAME="gopanel-${SHA:0:12}.tar.gz"
echo "version $VERSION  $NAME  $BYTES bytes  sha256 $SHA"

[ "${1:-}" = "--publish" ] || { echo "(not published; run with --publish)"; exit 0; }

ssh "$HOST" "mkdir -p $REMOTE_DIR"
scp -q "$TARBALL" "$HOST:$REMOTE_DIR/$NAME.part"
ssh "$HOST" "chmod 644 $REMOTE_DIR/$NAME.part && mv $REMOTE_DIR/$NAME.part $REMOTE_DIR/$NAME"
GOT="$(curl -fsSL "$BASE_URL/$NAME" | sha256sum | cut -d' ' -f1)"
[ "$GOT" = "$SHA" ] || { echo "uploaded file does not hash to $SHA (got $GOT)" >&2; exit 1; }
echo "published and verified: $BASE_URL/$NAME"

sed -i -e "s|^GOPANEL_VERSION=.*|GOPANEL_VERSION=\"$VERSION\"|" \
	-e "s|^GOPANEL_SHA256=.*|GOPANEL_SHA256=\"$SHA\"|" \
	-e "s|^GOPANEL_BYTES=.*|GOPANEL_BYTES=$BYTES|" "$INSTALLER"
echo "pins updated in $INSTALLER"
