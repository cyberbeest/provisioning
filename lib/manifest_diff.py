#!/usr/bin/env python3
"""
Builds/diffs a lightweight per-file fingerprint (size + mtime + first-4KB
hash) so the scan script can skip clamscan-ing files that haven't changed
since the last run. clamscan itself has no cross-run cache; this is that
cache. Size+mtime alone can be spoofed by touch -d; a full-content hash
would cost as much I/O as just scanning the file (you have to read it to
hash it, and clamscan has to read it anyway). The 4KB header hash is a
cheap middle ground, not a guarantee - a same-size, same-mtime edit that
avoids the first 4KB would slip through. Periodic full scans (no prior
manifest) are still the real backstop.

Usage:
  manifest_diff.py build <root> <exclude_regex> <out_manifest>
  manifest_diff.py diff <old_manifest> <new_manifest> <out_changed_filelist>
  manifest_diff.py merge <old_manifest> <new_manifest> <changed_filelist> <confirmed_filelist> <out_manifest>

merge is for a scan that got interrupted partway through clamdscan (e.g. the
user closed the GUI mid-scan): it carries forward (a) every file that
wasn't in this run's changed-list at all (untouched, still valid from
before) and (b) only the changed files clamdscan actually finished and
reported on (confirmed_filelist) before the interrupt. Anything queued to
be scanned but not yet confirmed is left OUT of the result on purpose --
it'll show up as "changed" again next run and get (re-)scanned, which is
the safe default over guessing it was fine.
"""
import hashlib
import os
import re
import sys

HEADER_BYTES = 4096


def header_hash(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read(HEADER_BYTES)).hexdigest()
    except OSError:
        return ""


def build(root, exclude_regex, out_path):
    exclude_re = re.compile(exclude_regex) if exclude_regex else None
    skip_dirs = {"/proc", "/sys", "/dev", "/run"}
    with open(out_path, "w") as out:
        for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
            if dirpath in skip_dirs or any(dirpath.startswith(d + "/") for d in skip_dirs):
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if not (exclude_re and exclude_re.search(os.path.join(dirpath, d)))]
            for name in filenames:
                path = os.path.join(dirpath, name)
                if exclude_re and exclude_re.search(path):
                    continue
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                if not os.path.isfile(path):
                    continue
                out.write(f"{path}\t{st.st_size}\t{int(st.st_mtime)}\t{header_hash(path)}\n")


def load(path):
    entries = {}
    try:
        with open(path) as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) != 4:
                    continue
                p, size, mtime, hh = parts
                entries[p] = (size, mtime, hh)
    except FileNotFoundError:
        pass
    return entries


def diff(old_path, new_path, out_path):
    old = load(old_path)
    changed = []
    with open(new_path) as f, open(out_path, "w") as out:
        for line in f:
            p, size, mtime, hh = line.rstrip("\n").split("\t")
            if old.get(p) != (size, mtime, hh):
                out.write(p + "\n")
                changed.append(p)
    print(f"{len(changed)} changed/new files since last manifest", file=sys.stderr)


def _read_lines(path):
    try:
        with open(path) as f:
            return set(line.rstrip("\n") for line in f)
    except FileNotFoundError:
        return set()


def merge(old_path, new_path, changed_path, confirmed_path, out_path):
    changed = _read_lines(changed_path)
    confirmed = _read_lines(confirmed_path)
    kept = 0
    dropped = 0
    with open(new_path) as f, open(out_path, "w") as out:
        for line in f:
            p = line.split("\t", 1)[0]
            if p not in changed or p in confirmed:
                out.write(line)
                kept += 1
            else:
                dropped += 1
    print(f"partial manifest: kept {kept} entries (unchanged + confirmed), "
          f"dropped {dropped} not-yet-confirmed", file=sys.stderr)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "build":
        build(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "diff":
        diff(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "merge":
        merge(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6])
    else:
        sys.exit(f"unknown command: {cmd}")
