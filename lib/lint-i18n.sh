#!/bin/bash
# Checks that every non-English i18n catalog (lib/i18n/) defines exactly the
# same set of keys as the English one, for both the bash and the Python
# catalogs. Run this by hand after editing a catalog -- a missing key
# silently falls back to English at runtime, which is easy to miss without
# this check. Locales are discovered from whatever strings.<locale>.sh /
# strings_<locale>.py files exist, so adding a new language needs no edit
# here.
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

for l10n_file in "$DIR"/strings.*.sh; do
	[ -e "$l10n_file" ] || continue
	locale="$(basename "$l10n_file" .sh)"
	locale="${locale#strings.}"
	[ "$locale" = "en" ] && continue
	check_bash_pair "$DIR/strings.en.sh" "$l10n_file" "shell catalog: $locale"
done

for l10n_file in "$DIR"/strings_*.py; do
	[ -e "$l10n_file" ] || continue
	locale="$(basename "$l10n_file" .py)"
	locale="${locale#strings_}"
	[ "$locale" = "en" ] && continue
	check_python_pair "$DIR/strings_en.py" "$l10n_file" "python catalog: $locale"
done

if [ "$status" -eq 0 ]; then
	echo "i18n catalogs in sync."
fi
exit "$status"
