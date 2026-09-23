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


def main():
    targets = get_targets()
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
    if os.path.exists(IMAGE_VIEWER):
        subprocess.Popen(["python3", IMAGE_VIEWER, path])
    else:
        subprocess.Popen(["xdg-open", path])
    return 0


if __name__ == "__main__":
    sys.exit(main())
