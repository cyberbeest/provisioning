#!/usr/bin/env python3
"""Right-click-style popup menu for the clipboard-status panel icon
(clipboard-status-genmon.sh's <txtclick> target). Replaces jumping straight
to clipboard-status-viewer.py: shows only the commands relevant to what's
actually in the clipboard right now, plus the auto-clear settings command
which is always available.

Standalone process, same popup-at-pointer mechanics as
shutdown-timer-menu.py (see that file's main() for why the trigger event
has to be synthesized).
"""

import os
import subprocess
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk

from i18n import t

STATE_FILE = os.path.expanduser("~/.config/cyberbeest/clipboard-status.state")
CONFIG_FILE = os.path.expanduser("~/.config/cyberbeest/clipboard-status.conf")
VIEWER = os.path.expanduser("~/.local/bin/clipboard-status-viewer.py")
SHOW_IMAGE = os.path.expanduser("~/.local/bin/clipboard-show-image.py")
AUTO_CLEAR_SETTINGS = os.path.expanduser("~/.local/bin/clipboard-auto-clear-settings.py")

# Must match clipboard-watcher.sh's DEFAULT_AUTO_CLEAR_SECS and
# clipboard-auto-clear-settings.py's DEFAULTS -- duplicated rather than
# shared, same convention the shutdown-timer family of scripts uses.
DEFAULT_AUTO_CLEAR_SECS = 900


def read_auto_clear_seconds():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("AUTO_CLEAR_SECONDS="):
                    try:
                        return int(line.split("=", 1)[1])
                    except ValueError:
                        pass
    return DEFAULT_AUTO_CLEAR_SECS


def read_state():
    state = {"TYPE": "empty", "PREVIEW": "", "CHANGED": "0"}
    if not os.path.exists(STATE_FILE):
        return state
    state["TYPE"] = "empty"
    # PREVIEW is written shell-quoted (printf %q) for clipboard-status-genmon.sh's
    # own `source $STATE_FILE`, so undo that the same way -- via bash's own
    # parser -- rather than re-implementing %q-unescaping in Python, which
    # would mis-handle values %q renders as $'...'-quoted or leaves
    # unquoted vs. single-quoted.
    try:
        out = subprocess.run(
            ["bash", "-c", 'source "$1"; printf "%s\\n%s\\n%s"'
             ' "$TYPE" "$CHANGED" "$PREVIEW"', "_", STATE_FILE],
            capture_output=True, text=True, timeout=1,
        ).stdout
        parts = out.split("\n", 2)
        if len(parts) == 3:
            state["TYPE"], state["CHANGED"], state["PREVIEW"] = parts
    except Exception:
        pass
    return state


# Unit suffixes (s/m/h) are left untranslated, same convention as
# shutdown-timer-genmon.sh's fmt().
def fmt_age(changed):
    try:
        secs = int(time.time()) - int(changed)
    except ValueError:
        return ""
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    return f"{secs // 3600}h"


def status_labels():
    return {
        "text": t("clipboard.label_text"),
        "image": t("clipboard.label_image"),
        "image_file": t("clipboard.label_image_file"),
        "files": t("clipboard.label_files"),
        "unknown": t("clipboard.label_unknown"),
    }


def fmt_duration(secs):
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m {secs % 60}s" if secs % 60 else f"{secs // 60}m"
    return f"{secs // 3600}h {(secs % 3600) // 60}m" if secs % 3600 else f"{secs // 3600}h"


def status_header_text(state):
    clip_type = state["TYPE"]
    if clip_type == "empty":
        return t("clipboard.empty")
    label = status_labels().get(clip_type, t("clipboard.label_unknown"))
    age = fmt_age(state["CHANGED"])
    text = f"{label} ({age})" if age else label
    preview = state["PREVIEW"].strip()
    if preview and clip_type in ("text", "files", "image_file"):
        if len(preview) > 40:
            # A path's useful end is the file name, so shorten it from the
            # front instead.
            preview = preview[:40] + "…" if clip_type == "text" else "…" + preview[-40:]
        text += f": {preview}"

    delay = read_auto_clear_seconds()
    if delay > 0:
        try:
            remaining = delay - (int(time.time()) - int(state["CHANGED"]))
        except ValueError:
            remaining = delay
        remaining = max(remaining, 0)
        text += t("clipboard.clears_in").format(duration=fmt_duration(remaining))
    return text


def clipboard_file_uris():
    """file:// URIs on the clipboard whose files still exist."""
    try:
        out = subprocess.run(
            ["xclip", "-selection", "clipboard", "-o", "-t", "text/uri-list"],
            capture_output=True, text=True, timeout=2,
        ).stdout
    except Exception:
        return []
    uris = []
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("file://"):
            continue
        try:
            path = GLib.filename_from_uri(line)[0]
        except GLib.Error:
            continue
        if os.path.exists(path):
            uris.append(line)
    return uris


def first_uri_per_folder(uris):
    """One URI per distinct containing folder, in clipboard order."""
    seen = {}
    for uri in uris:
        folder = os.path.dirname(GLib.filename_from_uri(uri)[0])
        seen.setdefault(folder, uri)
    return list(seen.values())


def show_in_folder(_item, uris):
    Gtk.main_quit()
    # Opens each containing folder with a file selected -- Files (Thunar)
    # implements the freedesktop FileManager1 interface for this. It opens
    # a separate window per URI passed (even for files in the same
    # folder), so only one file per folder is passed: one window each.
    for uri in first_uri_per_folder(uris):
        try:
            Gio.bus_get_sync(Gio.BusType.SESSION).call_sync(
                "org.freedesktop.FileManager1", "/org/freedesktop/FileManager1",
                "org.freedesktop.FileManager1", "ShowItems",
                GLib.Variant("(ass)", ([uri], "")), None, Gio.DBusCallFlags.NONE, 5000,
            )
        except GLib.Error:
            subprocess.Popen(["xdg-open", os.path.dirname(GLib.filename_from_uri(uri)[0])])


def launch(_item, cmd):
    Gtk.main_quit()
    subprocess.Popen(cmd)


def clear_clipboard(_item):
    Gtk.main_quit()
    subprocess.run(["xclip", "-selection", "clipboard", "-i", "/dev/null"], timeout=2)


def build_menu():
    state = read_state()
    clip_type = state["TYPE"]
    menu = Gtk.Menu()

    header = Gtk.MenuItem(label=status_header_text(state))
    header.set_sensitive(False)
    menu.append(header)
    menu.append(Gtk.SeparatorMenuItem())

    # Image skips the viewer dialog entirely -- "Clipboard contains an
    # image" + a Show button added nothing a direct open didn't already
    # say, so its command goes straight to clipboard-show-image.py.
    view_actions = {
        "text": (t("clipboard.view_edit"), [VIEWER]),
        "image": (t("clipboard.show_image"), [SHOW_IMAGE]),
        "image_file": (t("clipboard.show_image"), [SHOW_IMAGE]),
        "files": (t("clipboard.view"), [VIEWER]),
        "unknown": (t("clipboard.view"), [VIEWER]),
    }
    if clip_type in ("files", "image_file"):
        uris = clipboard_file_uris()
        # For image + file, "Show image" already opens the original file.
        if clip_type == "files" and len(uris) == 1:
            open_item = Gtk.MenuItem(label=t("clipboard.open_file"))
            open_item.connect("activate", launch, ["xdg-open", GLib.filename_from_uri(uris[0])[0]])
            menu.append(open_item)
        if uris:
            folder_count = len(first_uri_per_folder(uris))
            folder_item = Gtk.MenuItem(
                label=t("clipboard.show_in_folder") if folder_count == 1
                else t("clipboard.show_in_folders").format(count=folder_count)
            )
            folder_item.connect("activate", show_in_folder, uris)
            menu.append(folder_item)

    if clip_type in view_actions:
        label, cmd = view_actions[clip_type]
        view_item = Gtk.MenuItem(label=label)
        view_item.connect("activate", launch, cmd)
        menu.append(view_item)

        clear_item = Gtk.MenuItem(label=t("clipboard.clear_clipboard"))
        clear_item.connect("activate", clear_clipboard)
        menu.append(clear_item)

        menu.append(Gtk.SeparatorMenuItem())

    settings_item = Gtk.MenuItem(label=t("clipboard.auto_clear_settings"))
    settings_item.connect("activate", launch, [AUTO_CLEAR_SETTINGS])
    menu.append(settings_item)

    menu.show_all()
    return menu


def main():
    menu = build_menu()
    menu.connect("deactivate", lambda _m: Gtk.main_quit())

    display = Gdk.Display.get_default()
    seat = display.get_default_seat()
    pointer = seat.get_pointer()
    screen, px, py = pointer.get_position()
    rect = Gdk.Rectangle()
    rect.x, rect.y, rect.width, rect.height = px, py, 1, 1

    trigger_event = Gdk.Event.new(Gdk.EventType.BUTTON_PRESS)
    trigger_event.button.window = screen.get_root_window()
    trigger_event.button.device = seat.get_pointer()
    trigger_event.button.x = float(px)
    trigger_event.button.y = float(py)
    trigger_event.button.x_root = float(px)
    trigger_event.button.y_root = float(py)
    trigger_event.button.time = Gdk.CURRENT_TIME
    trigger_event.button.button = 1

    menu.popup_at_rect(
        screen.get_root_window(), rect, Gdk.Gravity.NORTH_WEST, Gdk.Gravity.NORTH_WEST, trigger_event
    )

    Gtk.main()


if __name__ == "__main__":
    main()
