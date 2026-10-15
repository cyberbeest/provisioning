#!/bin/bash
# Installs Butler (experimental/butler): the local command matcher behind the Commands list and
# the command hits in the Cyberbeest panel's menu search ("make the display a bit brighter",
# "set the volume to 40"). A small multilingual sentence-embedding model (MiniLM) picks one
# command from a fixed catalog; there is no text generation and nothing leaves the machine.
#
# On by default: gopanel starts `butler-server` (~/.local/bin) when the menu is first used and
# unloads it again when memory is short. The Butler tab in Cyberbeest Settings (it appears once
# the catalog is installed here) switches it off.
#
# Installs to ~/.local/share/cyberbeest/butler: the code, the catalogs, the factbook answers
# (facts/), the shipped embedding cache (seed/) and the model (model/, 118 MB, downloaded once
# from Hugging Face at a pinned revision and verified by SHA-256). The Python packages
# (onnxruntime, tokenizers, numpy) go into a private venv in the same folder.
#
# Depends on: nothing at install time; it is only useful with the Cyberbeest panel
# (69-cyberbeest-panel.sh) and the Settings app. Needs network (apt, PyPI, Hugging Face); if the
# model download fails the script fails and the next run retries it.
# Idempotent: safe to re-run; the model and the venv are kept when they are already right.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/69a-butler.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing Butler ==="

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="${BUTLER_INSTALL_HOME:-$(getent passwd "$TARGET_USER" | cut -d: -f6)}" # the override is for testing only
SRC="$DIR/experimental/butler"
DEST="$TARGET_HOME/.local/share/cyberbeest/butler"
BINDIR="$TARGET_HOME/.local/bin"
run_as_user() {
	if [ "$(id -un)" = "$TARGET_USER" ]; then "$@"; else sudo -u "$TARGET_USER" -H "$@"; fi
}

MODEL_REPO="Xenova/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_REV="2c4055b12046f11709e9df2c122e59ffbdc2f900"
MODEL_FILES=(
	"tokenizer.json b60b6b43406a48bf3638526314f3d232d97058bc93472ff2de930d43686fa441"
	"config.json 05b570bff786faa5c4604152aa16f19f77ed6dfc31e47dd0f3dd987078693ac7"
	"onnx/model_quantized.onnx 66fc00f5f29afcaff34092e1bdd20008ca3918265a82fb9695a551e510cc4ebc"
)

[ -d "$SRC/butler/catalog" ] || { echo "missing $SRC/butler/catalog"; exit 1; }

echo "--- System packages ---"
if ! dpkg -s python3-venv curl >/dev/null 2>&1; then
	apt-get -o DPkg::Lock::Timeout=60 update -qq
	apt-get -o DPkg::Lock::Timeout=60 install -y python3-venv curl
fi

echo "--- Code, catalogs, factbook and embedding cache to $DEST ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" \
	"$TARGET_HOME/.local/share/cyberbeest" "$DEST" "$BINDIR"
rm -rf "$DEST/butler" "$DEST/seed" "$DEST/facts"
cp -r "$SRC/butler" "$SRC/seed" "$DEST/"
cp -r "$DIR/factbook/facts" "$DEST/facts"
install -m 644 "$SRC/butler_server.py" "$DEST/butler_server.py"
find "$DEST" -name __pycache__ -type d -prune -exec rm -rf {} +
chown -R "$TARGET_USER:$TARGET_USER" "$DEST/butler" "$DEST/seed" "$DEST/facts" "$DEST/butler_server.py"

echo "--- Python environment (onnxruntime, tokenizers, numpy) ---"
[ -x "$DEST/venv/bin/python" ] || run_as_user python3 -m venv "$DEST/venv"
run_as_user "$DEST/venv/bin/pip" install --quiet --disable-pip-version-check \
	numpy==2.5.2 onnxruntime==1.31.0 tokenizers==0.23.3

echo "--- Model ($MODEL_REPO) ---"
run_as_user install -d "$DEST/model/onnx"
for entry in "${MODEL_FILES[@]}"; do
	f="${entry%% *}"
	sum="${entry##* }"
	if [ -f "$DEST/model/$f" ] && [ "$(sha256sum "$DEST/model/$f" | cut -d' ' -f1)" = "$sum" ]; then
		echo "$f already there"
		continue
	fi
	echo "downloading $f"
	tmp="$DEST/model/$f.part"
	run_as_user curl -fL --retry 3 --silent --show-error -o "$tmp" \
		"https://huggingface.co/$MODEL_REPO/resolve/$MODEL_REV/$f"
	if [ "$(sha256sum "$tmp" | cut -d' ' -f1)" != "$sum" ]; then
		rm -f "$tmp"
		echo "checksum mismatch for $f"
		exit 1
	fi
	mv -f "$tmp" "$DEST/model/$f"
done

echo "--- butler-server launcher ---"
cat >"$BINDIR/butler-server" <<LAUNCH
#!/bin/sh
# Starts the Butler matcher for the Cyberbeest panel's menu (installed by 69a-butler.sh).
D="\$HOME/.local/share/cyberbeest/butler"
export BUTLER_FACTS="\$D/facts"
exec "\$D/venv/bin/python" "\$D/butler_server.py" "\$@"
LAUNCH
chown "$TARGET_USER:$TARGET_USER" "$BINDIR/butler-server"
chmod 755 "$BINDIR/butler-server"

# A running matcher keeps the old code and catalog until it exits. The panel starts a new one on
# the next menu search, so stopping it is all the reload needed.
echo "--- Reloading Butler if it is running ---"
if pkill -u "$TARGET_USER" -f '[b]utler_server\.py'; then
	echo "stopped the running matcher; the panel starts the new one on next use"
else
	echo "Butler not running -- nothing to reload"
fi

echo "--- Self-test (catalog check) ---"
run_as_user bash -c "cd '$DEST' && BUTLER_FACTS='$DEST/facts' venv/bin/python -m butler.loader" || echo "WARNING: catalog check failed"

echo "=== $(date) : done (the menu starts Butler on first use; Settings > Butler switches it off) ==="
