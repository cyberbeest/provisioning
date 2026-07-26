#!/bin/bash
# Checks that the en/de i18n catalogs (lib/i18n/) define exactly the same
# set of keys, in both the bash and the Python catalog pairs. Run this from
# run-all.sh/run-changed.sh or by hand after editing a catalog -- a missing
# key silently falls back to English at runtime, which is easy to miss
# without this check.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)/i18n"
status=0

check_bash_pair() {
	local en_file="$1" l10n_file="$2" label="$3"
	local en_keys l10n_keys
	en_keys="$(bash -c "declare -gA STRINGS_EN=(); . '$en_file'; printf '%s\n' \"\${!STRINGS_EN[@]}\"" | sort)"
	l10n_keys="$(bash -c "declare -gA STRINGS_L10N=(); . '$l10n_file'; printf '%s\n' \"\${!STRINGS_L10N[@]}\"" | sort)"
	local diff
	diff="$(diff <(echo "$en_keys") <(echo "$l10n_keys") || true)"
	if [ -n "$diff" ]; then
		echo "i18n mismatch [$label]: keys differ between $(basename "$en_file") and $(basename "$l10n_file")"
		echo "$diff"
		status=1
	fi
}

check_python_pair() {
	local en_file="$1" l10n_file="$2" label="$3"
	local diff
	diff="$(python3 - "$en_file" "$l10n_file" <<-'EOF'
		import importlib.util, sys
		def load(path):
		    spec = importlib.util.spec_from_file_location("cat", path)
		    m = importlib.util.module_from_spec(spec)
		    spec.loader.exec_module(m)
		    return set(m.STRINGS.keys())
		en, l10n = load(sys.argv[1]), load(sys.argv[2])
		for k in sorted(en - l10n):
		    print(f"  only in {sys.argv[1]}: {k}")
		for k in sorted(l10n - en):
		    print(f"  only in {sys.argv[2]}: {k}")
		EOF
	)"
	if [ -n "$diff" ]; then
		echo "i18n mismatch [$label]:"
		echo "$diff"
		status=1
	fi
}

check_bash_pair "$DIR/strings.en.sh" "$DIR/strings.de.sh" "shell catalog"
check_python_pair "$DIR/strings_en.py" "$DIR/strings_de.py" "python catalog"

if [ "$status" -eq 0 ]; then
	echo "i18n catalogs in sync."
fi
exit "$status"
