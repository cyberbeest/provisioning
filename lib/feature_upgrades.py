"""Pending non-security package upgrades, shared by shutdown-timer-menu.py (decides whether
to show "Run feature updates...") and cyberbeest-feature-upgrade.py (the dialog).

The security pass (security-update-check.sh) installs everything from a *-security suite
on its own, so these are the upgrades it deliberately leaves alone."""

import subprocess


def pending_feature_upgrades():
    """[(name, installed_version, new_version)] sorted by name, security suites excluded."""
    try:
        out = subprocess.run(
            ["apt", "list", "--upgradable"],
            capture_output=True, text=True, timeout=30, env={"LC_ALL": "C", "PATH": "/usr/sbin:/usr/bin:/sbin:/bin"},
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    result = []
    for line in out.splitlines():
        if "/" not in line:
            continue
        name, rest = line.split("/", 1)
        fields = rest.split()
        if len(fields) < 2 or "-security" in fields[0]:
            continue
        old = line.rsplit("upgradable from: ", 1)[-1].rstrip("]") if "upgradable from: " in line else ""
        result.append((name, old, fields[1]))
    return sorted(result)
