#!/usr/bin/env python3
"""Auto-clear delay settings for the clipboard-status panel icon.

Launched from clipboard-status-menu.py's "Auto-clear settings..." item
(always present, regardless of what's currently in the clipboard).

Enforcement lives in clipboard-watcher.sh: every clipboard change (re)reads
AUTO_CLEAR_SECONDS from the config file this dialog writes and schedules a
clear that long afterward, cancelled/superseded by the next change.
"""

import os

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from i18n import t

CONFIG_DIR = os.path.expanduser("~/.config/cyberbeest")
CONFIG_PATH = os.path.join(CONFIG_DIR, "clipboard-status.conf")

DEFAULTS = {
    "AUTO_CLEAR_SECONDS": "900",
}

# 0 is the "Never" sentinel, same convention as shutdown-timer-menu.py's
# PRESETS -- listed last since it's conceptually the far end of the scale.
PRESETS = [30, 60, 300, 900, 1800, 3600, 0]


def read_settings():
    settings = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" not in line or line.startswith("#"):
                    continue
                key, value = line.split("=", 1)
                if key in DEFAULTS:
                    settings[key] = value.strip()
    return settings


def write_settings(updates):
    settings = read_settings()
    settings.update(updates)
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        for k in DEFAULTS:
            f.write(f"{k}={settings[k]}\n")


# Unit suffixes (s/m/h) are left untranslated, same convention as
# shutdown-timer-genmon.sh's fmt().
def fmt(secs):
    secs = int(secs)
    if secs == 0:
        return t("clipboard.never")
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m" if secs % 60 == 0 else f"{secs // 60}m {secs % 60}s"
    return f"{secs // 3600}h" if secs % 3600 == 0 else f"{secs // 3600}h {(secs % 3600) // 60}m"


def main():
    current = int(read_settings()["AUTO_CLEAR_SECONDS"])

    win = Gtk.Window(title=t("clipboard.autoclear_title"))
    win.set_border_width(12)
    win.connect("destroy", Gtk.main_quit)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    win.add(box)

    label = Gtk.Label(label=t("clipboard.autoclear_prompt"))
    label.set_xalign(0)
    box.pack_start(label, False, False, 0)

    group = None
    for preset in PRESETS:
        item = Gtk.RadioButton.new_with_label_from_widget(group, fmt(preset))
        group = item
        item.set_active(preset == current)

        def on_toggled(item, preset=preset):
            if item.get_active():
                write_settings({"AUTO_CLEAR_SECONDS": str(preset)})

        item.connect("toggled", on_toggled)
        box.pack_start(item, False, False, 0)

    close_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
    close_box.set_halign(Gtk.Align.END)
    close_btn = Gtk.Button(label=t("clipboard.close"))
    close_btn.connect("clicked", lambda b: win.destroy())
    close_box.pack_start(close_btn, False, False, 0)
    box.pack_start(close_box, False, False, 8)

    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
