#!/usr/bin/env python3
"""Orders files for the malware scanner so the places malware most likely
lives (and does the most damage) are scanned first, and a hit is reported
long before a multi-hour full scan finishes.

Used by both scan paths: the in-machine scanner
(cyberbeest-scanner-helper.sh) and the boot-stick scan
(cyberbeest-stick-scan.sh). Paths are classified by where they sit on the
*target* system, so a mounted target at /mnt/scan/root is classified exactly
like the same file on a running system.

Usage:
  scan_priority.py order [--root DIR]
      Reads paths (one per line) on stdin, writes them to stdout sorted by
      tier, then by path (keeps reads of one directory together).
  scan_priority.py walk ROOT EXCLUDE_RE
      Walks ROOT (not crossing into other filesystems) and writes every
      regular file, tier-ordered. EXCLUDE_RE is matched against the path
      relative to ROOT (with a leading "/").
"""
import os
import re
import sys

# First matching tier wins. Tier 0 = code that runs with full privileges at
# boot or login; tier 1 = persistence spots and places users drop files;
# tier 2 = the rest of user data and add-on software; tier 3 = everything else.
TIERS = [
    re.compile(r"^/(boot|bin|sbin|lib|lib32|lib64|etc|root)/"),
    re.compile(r"^/usr/(bin|sbin|local|lib/systemd|lib/cron)/"),
    re.compile(r"^/(tmp|var/tmp|dev/shm|var/spool/cron|usr/lib|usr/libexec)/"),
    re.compile(r"^/home/[^/]+/(\.config/(autostart|systemd)|\.local/(bin|share/applications|share/systemd)|\.ssh|\.bash[^/]*|\.profile|\.zsh[^/]*|\.xprofile|\.xinitrc|\.xsessionrc|Downloads|Desktop)(/|$)"),
    re.compile(r"^/(home|opt|srv)/"),
    re.compile(r"^/var/(www|lib|opt|spool)/"),
]
# Index into TIERS -> tier number.
TIER_OF = [0, 0, 1, 1, 2, 2]
LAST_TIER = 3


def tier_of(rel_path):
    for pattern, tier in zip(TIERS, TIER_OF):
        if pattern.match(rel_path):
            return tier
    return LAST_TIER


def order(paths, root=""):
    keyed = []
    for p in paths:
        p = p.rstrip("\n")
        if not p:
            continue
        rel = p[len(root):] if root and p.startswith(root) else p
        keyed.append((tier_of(rel), p))
    keyed.sort()
    return [p for _, p in keyed]


def walk(root, exclude_re):
    exclude = re.compile(exclude_re) if exclude_re else None
    root = root.rstrip("/")
    files = []
    for dirpath, dirnames, filenames in os.walk(root or "/", followlinks=False):
        rel_dir = dirpath[len(root):] or "/"
        dirnames[:] = [
            d for d in dirnames
            if not (exclude and exclude.search(os.path.join(rel_dir, d) + "/"))
        ]
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.join(rel_dir, name)
            if exclude and exclude.search(rel):
                continue
            try:
                if os.path.islink(full) or not os.path.isfile(full):
                    continue
            except OSError:
                continue
            files.append(full)
    return order(files, root)


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "order":
        root = ""
        if len(sys.argv) >= 4 and sys.argv[2] == "--root":
            root = sys.argv[3].rstrip("/")
        for p in order(sys.stdin, root):
            print(p)
    elif len(sys.argv) >= 3 and sys.argv[1] == "walk":
        exclude = sys.argv[3] if len(sys.argv) > 3 else ""
        for p in walk(sys.argv[2], exclude):
            print(p)
    else:
        print(__doc__, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
