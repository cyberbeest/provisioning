#!/usr/bin/env python3
"""Build a curated AppStream catalog so GNOME Software can browse/search/install
a hand-picked set of secure messengers, even though Debian doesn't publish
archive-wide AppStream metadata the way Ubuntu/Fedora do.

For each app: apt-get download the .deb (adding its vendor repo first if
needed), pull the real upstream metainfo.xml the package already ships,
strip it down to English-only fields, tag it with <pkgname> so PackageKit
can resolve an install, and copy its real icon into the hicolor icon theme
under a name that can't collide with the file the real package will
eventually install (so nothing breaks when the user actually installs it).

Must be run as root (it writes to /usr/share/...). Intended to be invoked
from install-messenger-catalog.sh, which itself runs under sudo during
provisioning.
"""

import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

HELPER = str(Path(__file__).resolve().parent / "cyberbeest-pkg-helper.sh")
CATALOG_PATH = Path("/usr/share/swcatalog/xml/cyberbeest-messengers.xml")
ICON_THEME_DIR = Path("/usr/share/icons/hicolor")
ORIGIN = "cyberbeest-messengers"

# (apt package, metainfo relative glob, vendor repo needed for do_setup_repo)
APPS = [
    ("telegram-desktop", "org.telegram.desktop.metainfo.xml", None),
    ("signal-desktop", None, "signal"),  # no metainfo shipped, handled specially
    ("element-desktop", None, "element"),  # no metainfo shipped, handled specially
    ("dino-im", "im.dino.Dino.appdata.xml", None),
    ("nheko", "nheko.appdata.xml", None),
    ("gajim", "org.gajim.Gajim.metainfo.xml", None),
    ("qtox", "io.github.qtox.qTox.appdata.xml", None),
]

# GNOME Software's Explore carousel hard-caps at 5 featured apps (see
# gs_overview_page_load(), "max-results", 5), so tagging all 7 just leaves
# which 5 show up to chance. Pick the 5 most popular/established instead;
# Nheko and qTox stay fully searchable/installable, just not featured.
FEATURED_PKGS = {
    "telegram-desktop",
    "signal-desktop",
    "element-desktop",
    "dino-im",
    "gajim",
}

# Fallback metadata for packages whose .deb does not ship AppStream metainfo.
MANUAL_FALLBACK = {
    "signal-desktop": {
        "id": "org.signal.Signal",
        "name": "Signal",
        "summary": "Private messaging, end-to-end encrypted by default",
        "description": "Signal is a private messenger for phone and desktop. "
        "It uses end-to-end encryption for all messages and calls by default, "
        "and its protocol is open source and widely audited.",
        "categories": ["Network", "InstantMessaging"],
    },
    "element-desktop": {
        "id": "im.riot.Riot",
        "name": "Element",
        "summary": "Matrix chat client, also end-to-end encrypted",
        "description": "Element is a client for Matrix, an open network for "
        "secure, decentralized communication. Rooms can be end-to-end "
        "encrypted.",
        "categories": ["Network", "InstantMessaging"],
    },
}


def log(msg):
    print(f"[build_messenger_catalog] {msg}")


def run(cmd, **kw):
    log("+ " + " ".join(cmd))
    return subprocess.run(cmd, check=True, **kw)


def strip_translations(elem):
    """Drop every child tag that has an xml:lang attribute, keeping only the
    default (English) copy, and recurse into content-bearing containers."""
    lang_key = "{http://www.w3.org/XML/1998/namespace}lang"
    for child in list(elem):
        if child.get(lang_key) is not None:
            elem.remove(child)
        else:
            strip_translations(child)


def find_best_icon(extract_dir):
    """Prefer a 128x128 (or nearest) raster icon, else a scalable svg."""
    apps_dirs = sorted(extract_dir.glob("usr/share/icons/hicolor/*/apps"))
    by_size = {}
    for d in apps_dirs:
        size = d.parent.name
        for f in d.glob("*"):
            if f.suffix.lower() in (".png", ".svg") and "symbolic" not in f.name:
                by_size.setdefault(size, []).append(f)

    for preferred in ("128x128", "256x256", "64x64", "96x96", "48x48"):
        if preferred in by_size:
            return by_size[preferred][0], preferred
    if "scalable" in by_size:
        return by_size["scalable"][0], "scalable"
    for size, files in by_size.items():
        if files:
            return files[0], size

    # some packages (dino) ship icons in a separate -common package; caller
    # handles that by pointing extract_dir at the merged tree.
    return None, None


def download_and_extract(pkg, workdir):
    subprocess.run(["apt-get", "download", pkg], cwd=workdir, check=False,
                    capture_output=True, text=True)
    debs = list(Path(workdir).glob(f"{pkg}_*.deb"))
    if not debs:
        raise RuntimeError(f"apt-get download produced no .deb for {pkg}")

    extract_dir = Path(workdir) / f"extract-{pkg}"
    extract_dir.mkdir(exist_ok=True)
    run(["dpkg-deb", "-x", str(debs[0]), str(extract_dir)])

    # Some packages (e.g. dino-im) ship their metainfo/desktop file but keep
    # icons in a separate "-common" package. Best-effort merge it in too.
    subprocess.run(["apt-get", "download", f"{pkg}-common"], cwd=workdir,
                    check=False, capture_output=True, text=True)
    common_debs = list(Path(workdir).glob(f"{pkg}-common_*.deb"))
    if common_debs:
        run(["dpkg-deb", "-x", str(common_debs[0]), str(extract_dir)])

    return extract_dir


def build_component_from_metainfo(pkg, metainfo_name, extract_dir):
    matches = list(extract_dir.rglob(metainfo_name))
    if not matches:
        raise RuntimeError(f"metainfo {metainfo_name} not found for {pkg}")
    tree = ET.parse(matches[0])
    root = tree.getroot()
    strip_translations(root)

    # Drop bulky sections we don't need for a browse/install catalog entry.
    for tag in ("screenshots", "releases", "url", "provides",
                "content_rating", "launchable", "compulsory_for_desktop",
                "kudos", "translation", "update_contact", "developer_name",
                "developer"):
        for child in root.findall(tag):
            root.remove(child)

    root.set("type", "desktop-application")

    icon_file, size = find_best_icon(extract_dir)
    for icon_el in root.findall("icon"):
        root.remove(icon_el)
    if icon_file:
        icon_name = f"cyberbeest-preview-{pkg}"
        icon_el = ET.SubElement(root, "icon", type="stock")
        icon_el.text = icon_name
        install_icon(icon_file, icon_name, size)

    pkgname_el = ET.SubElement(root, "pkgname")
    pkgname_el.text = pkg
    # pkgname must come before other trailing tags per schema ordering rules
    # used by appstreamcli validate; keep it simple and let appstreamcli
    # tolerate ordering (validate --no-net just to sanity check, not enforced).
    if pkg in FEATURED_PKGS:
        mark_as_featured(root)
    return root


def build_component_manual(pkg, extract_dir):
    info = MANUAL_FALLBACK[pkg]
    comp = ET.Element("component", type="desktop-application")
    ET.SubElement(comp, "id").text = info["id"]
    ET.SubElement(comp, "metadata_license").text = "CC0-1.0"
    ET.SubElement(comp, "name").text = info["name"]
    ET.SubElement(comp, "summary").text = info["summary"]
    desc = ET.SubElement(comp, "description")
    ET.SubElement(desc, "p").text = info["description"]
    cats = ET.SubElement(comp, "categories")
    for c in info["categories"]:
        ET.SubElement(cats, "category").text = c

    icon_file, size = find_best_icon(extract_dir)
    if icon_file:
        icon_name = f"cyberbeest-preview-{pkg}"
        ET.SubElement(comp, "icon", type="stock").text = icon_name
        install_icon(icon_file, icon_name, size)

    ET.SubElement(comp, "pkgname").text = pkg
    if pkg in FEATURED_PKGS:
        mark_as_featured(comp)
    return comp


def mark_as_featured(comp):
    """Surface this app as a Featured tile on GNOME Software's Explore page
    (there's no data-driven way to add a whole new category tile without
    patching gnome-software itself, so this is the closest curated-visibility
    equivalent)."""
    custom = ET.SubElement(comp, "custom")
    value = ET.SubElement(custom, "value", key="GnomeSoftware::FeatureTile")
    value.text = "True"


def install_icon(src, icon_name, size):
    dest_dir = ICON_THEME_DIR / size / "apps"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{icon_name}{src.suffix.lower()}"
    shutil.copyfile(src, dest)
    log(f"installed icon {dest}")


def setup_repo_if_needed(repo):
    if not repo:
        return
    run([HELPER, "setup-repo", repo])


def main():
    if sys.version_info < (3, 9):
        sys.exit("Python 3.9+ required (uses ElementTree.indent)")

    components = []
    with tempfile.TemporaryDirectory() as workdir:
        run(["apt-get", "update"])
        for pkg, metainfo_name, repo in APPS:
            log(f"=== {pkg} ===")
            setup_repo_if_needed(repo)
            try:
                extract_dir = download_and_extract(pkg, workdir)
            except Exception as e:
                log(f"SKIPPING {pkg}: {e}")
                continue

            try:
                if metainfo_name:
                    comp = build_component_from_metainfo(pkg, metainfo_name, extract_dir)
                else:
                    comp = build_component_manual(pkg, extract_dir)
                components.append(comp)
            except Exception as e:
                log(f"SKIPPING {pkg} (metadata build failed): {e}")

    if not components:
        sys.exit("No components built, aborting")

    root = ET.Element("components", version="0.14", origin=ORIGIN)
    for comp in components:
        root.append(comp)

    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(CATALOG_PATH, encoding="UTF-8", xml_declaration=True)
    log(f"wrote {CATALOG_PATH} with {len(components)} components")

    subprocess.run(["gtk-update-icon-cache", "-f", "-t", str(ICON_THEME_DIR)],
                    check=False, capture_output=True)
    subprocess.run(["appstreamcli", "refresh-cache", "--force"],
                    check=False, capture_output=True)
    log("done")


if __name__ == "__main__":
    main()
