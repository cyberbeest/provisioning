#!/bin/bash
# Root helper for the "Run feature updates..." dialog (lib/cyberbeest-feature-upgrade.py),
# run via pkexec -- see lib/com.cyberbeest.featureupgrade.policy. Installed to
# /usr/local/lib/cyberbeest/ by 12-xfce-panel-layout.sh.
#
# Usage: cyberbeest-feature-upgrade-helper.sh install   (package names on stdin, one per line)
#
# The caller is an unprivileged GUI, so every name is validated here: it has to look
# like a Debian package name AND be in apt's current list of upgradable
# packages that don't come from a security suite (the security pass owns those).
# Only already-installed packages are upgraded (--only-upgrade) -- nothing new is
# ever installed, and apt update is not run, so what the dialog showed is what happens.
# Output goes to stdout (the dialog follows it live) and to the log below.
set -euo pipefail
export LC_ALL=C PATH=/usr/sbin:/usr/bin:/sbin:/bin DEBIAN_FRONTEND=noninteractive

LOG=/var/log/cyberbeest-feature-upgrade.log
MAX_PACKAGES=500

[ "${1:-}" = install ] || { echo "usage: $0 install  (package names on stdin)" >&2; exit 2; }

declare -A allowed=()
while IFS= read -r line; do
	case "$line" in */*) ;; *) continue ;; esac
	case "${line%% *}" in *-security*) continue ;; esac
	suites="${line#*/}"; suites="${suites%% *}"
	case "$suites" in *-security*) continue ;; esac
	allowed["${line%%/*}"]=1
done < <(apt list --upgradable 2>/dev/null)

pkgs=()
while IFS= read -r name; do
	[ -n "$name" ] || continue
	[[ "$name" =~ ^[a-z0-9][a-z0-9+.-]*$ ]] || { echo "refusing invalid package name" >&2; exit 2; }
	[ -n "${allowed[$name]+x}" ] || { echo "not a pending feature update: $name" >&2; exit 3; }
	pkgs+=("$name")
	[ "${#pkgs[@]}" -le "$MAX_PACKAGES" ] || { echo "too many packages" >&2; exit 2; }
done
[ "${#pkgs[@]}" -gt 0 ] || { echo "no packages given" >&2; exit 2; }

{
	echo "=== $(date) : feature updates: ${pkgs[*]} ==="
	apt-get -o DPkg::Lock::Timeout=120 install -y --only-upgrade \
		-o Dpkg::Options::=--force-confold -o Dpkg::Options::=--force-confdef "${pkgs[@]}"
	echo "=== $(date) : done ==="
} 2>&1 | tee -a "$LOG"
exit "${PIPESTATUS[0]}"
