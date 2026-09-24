#!/usr/bin/env python3
"""Extracts the current clipboard image to a temp file and opens it in
Cyberbeest Image Viewer directly -- no intermediate dialog. Used by
clipboard-status-menu.py's "Show image" item; split out of
clipboard-status-viewer.py because that dialog's "Clipboard contains an
image" + Show-button step didn't add any information over just opening
the image immediately.
"""

import os
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlparse

# Where 58-cyberbeest-image-viewer.sh installs it. Falls back to xdg-open
# if that script hasn't run on this machine yet.
IMAGE_VIEWER = os.path.expanduser("~/.local/bin/cyberbeest_image_viewer.py")


def get_targets():
    try:
        out = subprocess.run(
            ["xclip", "-selection", "clipboard", "-o", "-t", "TARGETS"],
            capture_output=True, text=True, timeout=2,
        ).stdout
        return out.splitlines()
    except Exception:
        return []


def original_file(targets):
    """The file the clipboard image was copied from, if the clipboard also
    names one (e.g. Cyberbeest Image Viewer's Copy Image) and it still
    exists -- opening that shows the real file (name, full quality,
    animation) instead of a re-encoded temp copy."""
    if "text/uri-list" not in targets:
        return None
    try:
        out = subprocess.run(
            ["xclip", "-selection", "clipboard", "-o", "-t", "text/uri-list"],
            capture_output=True, text=True, timeout=2,
        ).stdout
    except Exception:
        return None
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        uri = urlparse(line)
        if uri.scheme != "file":
            return None
        path = unquote(uri.path)
        return path if os.path.isfile(path) else None
    return None


def open_image(path):
    if os.path.exists(IMAGE_VIEWER):
        subprocess.Popen(["python3", IMAGE_VIEWER, path])
    else:
        subprocess.Popen(["xdg-open", path])


def main():
    targets = get_targets()
    path = original_file(targets)
    if path:
        open_image(path)
        return 0
    # Prefer PNG since it's lossless and every image source offers it;
    # fall back to whatever image/* target is actually there.
    mime = "image/png" if "image/png" in targets else next(
        (t for t in targets if t.startswith("image/")), None
    )
    if mime is None:
        return 1
    ext = mime.split("/", 1)[1].split("+")[0]
    proc = subprocess.run(
        ["xclip", "-selection", "clipboard", "-o", "-t", mime],
        capture_output=True, timeout=2,
    )
    with tempfile.NamedTemporaryFile(
        prefix="clipboard-", suffix=f".{ext}", delete=False
    ) as f:
        f.write(proc.stdout)
        path = f.name
    open_image(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
