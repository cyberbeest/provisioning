#!/usr/bin/env python3
"""Cyberbeest Extended Power Options: a standalone dialog for the two
power-saving-while-locked settings (window minimizing + browser CPU
throttling) used by lock-shutdown-watcher.sh. Has its own Whisker menu
entry (Cyberbeest category), and is also launched as a separate process from
shutdown-timer-menu.py's "Power saving while locked..." item, rather than
opened as a Gtk.Dialog inside the menu's own process -- see the comment on
open_power_saving_dialog() there for why.

Reads/writes the same config file as lock-shutdown-watcher.sh and
shutdown-timer-menu.py, and keeps its own copy of DEFAULTS (matching the
menu's full set, not just the two keys shown here) so a save from this
dialog doesn't drop the shutdown-timer's own keys -- same duplication
convention the rest of this family of scripts already uses.
"""

import os
import subprocess

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from i18n import t

CONFIG_DIR = os.path.expanduser("~/.config/cyberbeest")
CONFIG_PATH = os.path.join(CONFIG_DIR, "power-settings.conf")

# Must match this machine's live panel plugin id (~/.config/xfce4/panel/genmon-25.rc).
GENMON_WIDGET_NAME = "__GENMON_WIDGET__"

DEFAULTS = {
    "AC_SHUTDOWN_MINUTES": "60",
    "BATTERY_SHUTDOWN_MINUTES": "60",
    "LINK_AC_BATTERY": "true",
    "MINIMIZE_MINUTES": "10",
    "BROWSER_THROTTLE_PERCENT": "10",
}


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


def write_setting(key, value):
    settings = read_settings()
    settings[key] = str(value)
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        for k in DEFAULTS:
            f.write(f"{k}={settings[k]}\n")
    # Otherwise the panel icon only catches up at its next 30s poll.
    subprocess.Popen(["xfce4-panel", f"--plugin-event={GENMON_WIDGET_NAME}:refresh:bool:true"])


def fmt_minutes_output(spin):
    value = spin.get_value_as_int()
    spin.set_text(t("lockpower.never") if value == 0 else str(value))
    return True


def fmt_percent_output(spin):
    value = spin.get_value_as_int()
    spin.set_text(t("lockpower.off") if value == 0 else str(value))
    return True


class PowerSavingDialog(Gtk.Window):
    def __init__(self):
        super().__init__(title=t("lockpower.window_title"))
        self.set_default_size(380, -1)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_border_width(16)
        self.connect("destroy", Gtk.main_quit)

        settings = read_settings()

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.add(box)

        info = Gtk.Label(
            wrap=True,
            max_width_chars=44,
            xalign=0,
            label=t("lockpower.info"),
        )
        box.pack_start(info, False, False, 0)

        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        box.pack_start(grid, False, False, 0)

        grid.attach(Gtk.Label(label=t("lockpower.minimize_after"), xalign=0), 0, 0, 1, 1)
        self.minimize_spin = Gtk.SpinButton.new_with_range(0, 120, 1)
        self.minimize_spin.set_value(int(settings["MINIMIZE_MINUTES"]))
        self.minimize_spin.connect("output", fmt_minutes_output)
        self.minimize_spin.connect("value-changed", self.on_minimize_changed)
        grid.attach(self.minimize_spin, 1, 0, 1, 1)

        grid.attach(Gtk.Label(label=t("lockpower.limit_cpu"), xalign=0), 0, 1, 1, 1)
        self.throttle_spin = Gtk.SpinButton.new_with_range(0, 100, 5)
        self.throttle_spin.set_value(int(settings["BROWSER_THROTTLE_PERCENT"]))
        self.throttle_spin.connect("output", fmt_percent_output)
        self.throttle_spin.connect("value-changed", self.on_throttle_changed)
        grid.attach(self.throttle_spin, 1, 1, 1, 1)

        button_box = Gtk.ButtonBox(layout_style=Gtk.ButtonBoxStyle.END)
        box.pack_start(button_box, False, False, 0)
        close_button = Gtk.Button(label=t("lockpower.close"))
        close_button.connect("clicked", lambda _b: self.destroy())
        button_box.pack_start(close_button, False, False, 0)

    def on_minimize_changed(self, spin):
        write_setting("MINIMIZE_MINUTES", spin.get_value_as_int())

    def on_throttle_changed(self, spin):
        write_setting("BROWSER_THROTTLE_PERCENT", spin.get_value_as_int())


def main():
    win = PowerSavingDialog()
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
