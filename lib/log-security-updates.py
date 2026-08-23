#!/usr/bin/env python3
"""Permanent, never-rotated record of every apt/dpkg package upgrade.

/var/log/apt/history.log and /var/log/dpkg.log get logrotated away after
12 months (see /etc/logrotate.d/apt, /etc/logrotate.d/dpkg) -- this reads
those logs (current + any still-present .gz backlog) and appends one JSON
record per upgrade to ~/.config/cyberbeest/security-update-history.jsonl,
which this script never rotates or truncates. For each package it also pulls the
matching entries out of the package's own local Debian changelog
(/usr/share/doc/<pkg>/changelog.Debian.gz) so the record carries the actual
description of what changed, not just a version-number diff, and flags the
upgrade as security-relevant if a changelog entry mentions a CVE or has
urgency=high/critical.

Reads only world-readable logs (history.log, not the root:adm term.log), so
this runs as the normal user on a schedule -- no sudo, no apt hook needed.
Safe to re-run any time; output is deduped by (date, package, old, new).
"""

import gzip
import json
import os
import re
import subprocess

HISTORY_LOG_DIR = "/var/log/apt"
OUTPUT_PATH = os.path.expanduser("~/.config/cyberbeest/security-update-history.jsonl")

UPGRADE_RE = re.compile(r"^(Upgrade|Install):\s*(.+)$")
PKG_RE = re.compile(r"^([^\s:]+):(\S+)\s+\(([^,)]+)(?:,\s*([^,)]+))?\)")
CVE_RE = re.compile(r"CVE-\d{4}-\d{4,}")


def read_text_maybe_gz(path):
    try:
        if path.endswith(".gz"):
            with gzip.open(path, "rt", errors="replace") as f:
                return f.read()
        with open(path, "rt", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def history_log_files():
    files = []
    for name in os.listdir(HISTORY_LOG_DIR):
        if name.startswith("history.log"):
            files.append(os.path.join(HISTORY_LOG_DIR, name))
    return sorted(files)


def parse_history_logs():
    """Yield (start_date, commandline, [(pkg, arch, old, new), ...])."""
    for path in history_log_files():
        text = read_text_maybe_gz(path)
        for block in text.split("\n\n"):
            lines = block.strip().splitlines()
            if not lines:
                continue
            fields = {}
            for line in lines:
                if ": " in line:
                    key, _, val = line.partition(": ")
                    fields[key] = val
            start = fields.get("Start-Date")
            cmd = fields.get("Commandline", "")
            action_line = fields.get("Upgrade") or fields.get("Install")
            if not start or not action_line:
                continue
            pkgs = []
            for entry in split_pkg_entries(action_line):
                m = PKG_RE.match(entry)
                if not m:
                    continue
                pkg, arch, first, second = m.groups()
                if second is None or second == "automatic":
                    # fresh install: "(version)" or "(version, automatic)"
                    old, new = None, first
                else:
                    old, new = first, second
                pkgs.append((pkg, arch, old, new))
            if pkgs:
                yield start, cmd, pkgs


def split_pkg_entries(action_line):
    # "pkg:arch (old, new), pkg2:arch (old2, new2)" -- split on "), "
    parts = action_line.split("), ")
    return [p if p.endswith(")") else p + ")" for p in parts]


def changelog_excerpt(pkg, old_version, new_version):
    """Local changelog entries with old_version < version <= new_version."""
    path = f"/usr/share/doc/{pkg}/changelog.Debian.gz"
    if not os.path.exists(path):
        path = f"/usr/share/doc/{pkg}/changelog.gz"
    if not os.path.exists(path):
        return None
    text = read_text_maybe_gz(path)
    entries = re.split(r"\n(?=\S+ \([^)]+\))", text)
    matched = []
    header_re = re.compile(r"^(\S+) \(([^)]+)\)")
    for entry in entries:
        m = header_re.match(entry)
        if not m:
            continue
        version = m.group(2)
        if old_version and version == old_version:
            break  # reached the version we already had, stop
        if in_range(version, old_version, new_version):
            matched.append(entry.strip())
    return "\n\n".join(matched) if matched else None


def in_range(version, old, new):
    if old is None:
        return version == new
    try:
        newer_than_old = subprocess.run(
            ["dpkg", "--compare-versions", version, "gt", old],
            check=False, stderr=subprocess.DEVNULL,
        ).returncode == 0
        not_newer_than_new = subprocess.run(
            ["dpkg", "--compare-versions", version, "le", new],
            check=False, stderr=subprocess.DEVNULL,
        ).returncode == 0
        return newer_than_old and not_newer_than_new
    except FileNotFoundError:
        return True


def is_security(changelog_text):
    if not changelog_text:
        return False
    if CVE_RE.search(changelog_text):
        return True
    if re.search(r"urgency=(high|critical)", changelog_text, re.IGNORECASE):
        return True
    return False


def load_existing_keys():
    keys = set()
    if os.path.exists(OUTPUT_PATH):
        with open(OUTPUT_PATH, "rt") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                keys.add((rec["start_date"], rec["package"], rec["old_version"], rec["new_version"]))
    return keys


def main():
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    existing = load_existing_keys()
    new_records = []
    for start_date, cmd, pkgs in parse_history_logs():
        for pkg, arch, old, new in pkgs:
            key = (start_date, pkg, old, new)
            if key in existing:
                continue
            changelog = changelog_excerpt(pkg, old, new)
            new_records.append({
                "start_date": start_date,
                "package": pkg,
                "arch": arch,
                "old_version": old,
                "new_version": new,
                "unattended": "unattended-upgrades" in cmd,
                "security": is_security(changelog),
                "changelog": changelog,
            })
            existing.add(key)

    if not new_records:
        return

    new_records.sort(key=lambda r: r["start_date"])
    with open(OUTPUT_PATH, "at") as f:
        for rec in new_records:
            f.write(json.dumps(rec) + "\n")
    print(f"Logged {len(new_records)} new package update record(s) to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
