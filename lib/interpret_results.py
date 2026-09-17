#!/usr/bin/env python3
"""
Turns a raw scan report (debsums + clamscan + rkhunter + chkrootkit output)
into a plain verdict, without an AI reading the log.

Why rule-based, not AI: "is this line dangerous" is exactly the kind of
semantic judgment call an LLM could get subtly wrong on security-critical
output, with no way for a non-technical user to catch the mistake, and no
guarantee an offline boot stick would even have a model to call. What IS
decidable is much narrower: "does this line match one of a curated set of
known-explained patterns" -- so that's what this does. Every debsums
deviation is compared against the actual pristine package (not guessed at),
every rkhunter/chkrootkit warning is checked against a short, human-curated
list of known false-positive shapes, and anything left over is surfaced
plainly as "needs your review" rather than silently cleared. Nothing here
claims to prove a system is clean -- it only tries to not waste the user's
attention on noise it can fully explain.

Known limitation: the debsums pristine-package diff needs network access
(apt-get download) and is best-effort. On the eventual offline boot stick
this should be replaced by a signed manifest of expected deviations built
at provisioning time (see leg 3 in the offline-scanner-stick-plan memory)
instead of a live download.
"""
import re
import subprocess
import sys
import tempfile
import os

RKHUNTER_KNOWN_BENIGN = [
    (re.compile(r"Checking for passwd file changes\s+\[ Warning \]"),
     "expected on a first run before rkhunter has a baseline to compare against"),
    (re.compile(r"Checking for group file changes\s+\[ Warning \]"),
     "expected on a first run before rkhunter has a baseline to compare against"),
]

CHKROOTKIT_KNOWN_BENIGN = [
    (re.compile(r"PACKET SNIFFER\(/usr/sbin/(NetworkManager|wpa_supplicant)"),
     "NetworkManager/wpa_supplicant legitimately use raw packet sockets for DHCP/EAPOL, not sniffing"),
]

# chkrootkit already tells us which Debian package owns a flagged dotfile;
# these are packages whose test-fixture/registry dotfiles are known-benign.
CHKROOTKIT_TRUSTED_OWNERS = {
    "libreoffice-common", "ruby-rubygems", "fail2ban", "virtualbox-7.2",
}

# Pure announcement lines chkrootkit prints before the actual finding (which
# is checked separately, above, or broken out into its own dotfiles list
# below) -- keeping these would double-count the same finding.
CHKROOTKIT_STRUCTURAL_HEADERS = [
    re.compile(r"^Searching for suspicious files and dirs\.\.\.\s+WARNING$"),
    re.compile(r"^WARNING: The following suspicious files and directories were found:$"),
    re.compile(r"^Checking `sniffer'\.\.\.\s+WARNING$"),
    re.compile(r"^WARNING: Output from ifpromisc:$"),
]


def split_sections(report_text):
    sections = {}
    current = None
    for line in report_text.splitlines():
        m = re.match(r"^===(\w+)===$", line)
        if m:
            current = m.group(1)
            sections[current] = []
        elif current:
            sections[current].append(line)
    return sections


def diff_against_package(path):
    """Best-effort: download the owning package and diff the live file
    against what it shipped. Returns (owner_pkg, diff_lines) or
    (owner_pkg, None) if the comparison couldn't be made."""
    try:
        owner = subprocess.run(["dpkg", "-S", path], capture_output=True, text=True, timeout=10)
        if owner.returncode != 0:
            return None, None
        pkg = owner.stdout.split(":")[0].strip()
        with tempfile.TemporaryDirectory() as tmp:
            dl = subprocess.run(["apt-get", "download", "-o", f"Dir::Cache::archives={tmp}", pkg],
                                 cwd=tmp, capture_output=True, text=True, timeout=30)
            if dl.returncode != 0:
                return pkg, None
            debs = [f for f in os.listdir(tmp) if f.endswith(".deb")]
            if not debs:
                return pkg, None
            extract_dir = os.path.join(tmp, "x")
            subprocess.run(["dpkg-deb", "-x", os.path.join(tmp, debs[0]), extract_dir],
                            capture_output=True, timeout=30)
            pristine_path = os.path.join(extract_dir, path.lstrip("/"))
            if not os.path.exists(pristine_path):
                return pkg, None
            diff = subprocess.run(["diff", pristine_path, path], capture_output=True, text=True, timeout=10)
            return pkg, diff.stdout.splitlines()
    except Exception:
        return None, None


def classify_debsums(lines, do_diff=True):
    # the helper's human-readable "=== <label> ===" stage header (distinct
    # from the machine "===<key>===" marker split_sections keys off of) is
    # tee'd into the same report file the debsums section pulls its lines
    # from -- filter it back out so it isn't mistaken for a flagged path.
    flagged = [l for l in lines if l.strip() and not l.startswith("debsums:")
               and not re.match(r"^=== .* ===$", l)]
    items = []
    for path in flagged:
        if do_diff:
            pkg, diff = diff_against_package(path)
        else:
            pkg, diff = None, None
        items.append({"path": path, "package": pkg, "diff": diff})
    return items


def classify_clamscan(lines):
    # clamscan's summary reports "Scanned files:"; clamdscan's doesn't (it
    # only reports infected count), so treat that field as best-effort.
    infected = 0
    scanned = None
    hits = []
    for l in lines:
        m = re.match(r"Infected files:\s*(\d+)", l)
        if m:
            infected = int(m.group(1))
        m = re.match(r"Scanned files:\s*(\d+)", l)
        if m:
            scanned = int(m.group(1))
        if ": " in l and l.rstrip().endswith("FOUND"):
            hits.append(l.strip())
    return {"infected": infected, "scanned": scanned, "hits": hits}


def classify_warnings(lines, known_benign, warning_re, ignore=()):
    explained, unexplained = [], []
    for l in lines:
        if not warning_re.search(l):
            continue
        if any(pat.search(l) for pat in ignore):
            continue
        match = next((why for pat, why in known_benign if pat.search(l)), None)
        if match:
            explained.append((l.strip(), match))
        else:
            unexplained.append(l.strip())
    return explained, unexplained


def classify_chkrootkit(lines):
    hits = [l.strip() for l in lines if re.search(r"\bINFECTED\b", l) and "not infected" not in l.lower()]
    explained, unexplained = classify_warnings(
        lines, CHKROOTKIT_KNOWN_BENIGN, re.compile(r"WARNING"), ignore=CHKROOTKIT_STRUCTURAL_HEADERS)
    # the actual finding behind a suppressed header (e.g. the packet-sniffer
    # line itself) doesn't contain "WARNING", so it's surfaced separately
    # here for transparency instead of silently vanishing with its header.
    for l in lines:
        match = next((why for pat, why in CHKROOTKIT_KNOWN_BENIGN if pat.search(l)), None)
        if match and not re.search(r"WARNING", l):
            explained.append((l.strip(), match))
    # the "suspicious files and directories" block: each line is annotated
    # with its owning package by chkrootkit itself.
    owned_dotfiles, unowned_dotfiles = [], []
    for l in lines:
        m = re.search(r"\[From Debian package: ([\w.+-]+)\]", l)
        if m:
            (owned_dotfiles if m.group(1) in CHKROOTKIT_TRUSTED_OWNERS else unowned_dotfiles).append(l.strip())
    return {
        "hits": hits,
        "explained_warnings": explained,
        "unexplained_warnings": unexplained,
        "owned_dotfiles": owned_dotfiles,
        "unowned_dotfiles": unowned_dotfiles,
    }


def classify_rkhunter(lines):
    explained, unexplained = classify_warnings(lines, RKHUNTER_KNOWN_BENIGN, re.compile(r"\[ Warning \]"))
    return {"explained_warnings": explained, "unexplained_warnings": unexplained}


def build_verdict(report_text, do_debsums_diff=True):
    sections = split_sections(report_text)
    debsums = classify_debsums(sections.get("debsums", []), do_diff=do_debsums_diff)
    clam = classify_clamscan(sections.get("clamscan", []))
    rk = classify_rkhunter(sections.get("rkhunter", []))
    ck = classify_chkrootkit(sections.get("chkrootkit", []))

    hard_hits = clam["hits"] or ck["hits"]
    needs_review = (
        rk["unexplained_warnings"] or ck["unexplained_warnings"] or
        ck["unowned_dotfiles"] or debsums
    )

    if hard_hits:
        level = "RED"
        headline = "Possible compromise found — do not ignore"
    elif needs_review:
        level = "YELLOW"
        n = len(rk["unexplained_warnings"]) + len(ck["unexplained_warnings"]) + len(ck["unowned_dotfiles"]) + len(debsums)
        headline = f"{n} item(s) need your review"
    else:
        level = "GREEN"
        headline = "No issues found"

    return {
        "level": level,
        "headline": headline,
        "clamscan": clam,
        "rkhunter": rk,
        "chkrootkit": ck,
        "debsums": debsums,
        "hard_hits": hard_hits,
    }


def render_text(verdict):
    out = [f"{verdict['level']}: {verdict['headline']}", ""]
    c = verdict["clamscan"]
    if c["scanned"] is not None:
        out.append(f"ClamAV: {c['infected']} infected out of {c['scanned']} files scanned")
    else:
        out.append(f"ClamAV: {c['infected']} infected (file count not reported by clamdscan)")
    for h in c["hits"]:
        out.append(f"  ! {h}")
    ck = verdict["chkrootkit"]
    out.append(f"chkrootkit: {'clean' if not ck['hits'] else str(len(ck['hits'])) + ' hit(s)'}")
    for h in ck["hits"]:
        out.append(f"  ! {h}")
    for l, why in ck["explained_warnings"]:
        out.append(f"  (explained) {l} -- {why}")
    for l in ck["unexplained_warnings"]:
        out.append(f"  (needs review) {l}")
    for l in ck["unowned_dotfiles"]:
        out.append(f"  (needs review) {l}")
    rk = verdict["rkhunter"]
    out.append("rkhunter:")
    for l, why in rk["explained_warnings"]:
        out.append(f"  (explained) {l} -- {why}")
    for l in rk["unexplained_warnings"]:
        out.append(f"  (needs review) {l}")
    out.append("debsums (files differing from their shipped package):")
    if not verdict["debsums"]:
        out.append("  none")
    for item in verdict["debsums"]:
        out.append(f"  {item['path']} (package: {item['package'] or 'unknown'})")
        if item["diff"] is None:
            out.append("    could not automatically diff against the pristine package -- review manually")
        else:
            for dl in item["diff"]:
                out.append(f"    {dl}")
    return "\n".join(out)


if __name__ == "__main__":
    with open(sys.argv[1]) as f:
        text = f.read()
    print(render_text(build_verdict(text)))
