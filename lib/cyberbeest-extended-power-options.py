#!/usr/bin/env python3
"""Cyberbeest Extended Power Options: a standalone dialog for the
power-saving-while-locked settings (window minimizing + browser CPU
throttling) used by lock-shutdown-watcher.sh, the instant-cover curtain
toggle (see lock-screen-curtain.sh), and the pre-lock warning notification
(see lock-warning-watcher.sh) -- none of these are surfaced anywhere else,
so they all live in this one dialog. Has its own Whisker menu entry
(Cyberbeest category), and is also launched as a separate process from
shutdown-timer-menu.py's "Extended power options..." item, rather than
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

# Must match this machine's live panel plugin id (~/.config/xfce4/panel/genmon-211.rc,
# the merged security-status/shutdown-timer widget -- see panel-status-genmon.sh).
GENMON_WIDGET_NAME = "__GENMON_WIDGET__"

DEFAULTS = {
    "AC_SHUTDOWN_MINUTES": "60",
    "BATTERY_SHUTDOWN_MINUTES": "60",
    "LINK_AC_BATTERY": "true",
    "MINIMIZE_MINUTES": "1",
    "BROWSER_THROTTLE_PERCENT": "10",
    "CURTAIN_ENABLED": "true",
    "WARN_BEFORE_LOCK_ENABLED": "true",
    "WARN_SECONDS_BEFORE_LOCK": "10",
    "NO_MERCY_LOCK_ENABLED": "false",
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

        self.curtain_check = Gtk.CheckButton(label=t("lockpower.curtain_enabled"))
        self.curtain_check.set_active(settings["CURTAIN_ENABLED"] == "true")
        self.curtain_check.connect("toggled", self.on_curtain_toggled)
        box.pack_start(self.curtain_check, False, False, 0)

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

        self.warn_check = Gtk.CheckButton(label=t("lockpower.warn_enabled"))
        self.warn_check.set_active(settings["WARN_BEFORE_LOCK_ENABLED"] == "true")
        self.warn_check.connect("toggled", self.on_warn_toggled)
        grid.attach(self.warn_check, 0, 2, 2, 1)

        self.warn_seconds_label = Gtk.Label(label=t("lockpower.warn_seconds"), xalign=0)
        grid.attach(self.warn_seconds_label, 0, 3, 1, 1)
        self.warn_spin = Gtk.SpinButton.new_with_range(1, 60, 1)
        self.warn_spin.set_value(int(settings["WARN_SECONDS_BEFORE_LOCK"]))
        self.warn_spin.connect("value-changed", self.on_warn_seconds_changed)
        grid.attach(self.warn_spin, 1, 3, 1, 1)
        self.warn_seconds_label.set_sensitive(self.warn_check.get_active())
        self.warn_spin.set_sensitive(self.warn_check.get_active())

        self.no_mercy_check = Gtk.CheckButton(label=t("lockpower.no_mercy_enabled"))
        self.no_mercy_check.set_active(settings["NO_MERCY_LOCK_ENABLED"] == "true")
        self.no_mercy_check.connect("toggled", self.on_no_mercy_toggled)
        box.pack_start(self.no_mercy_check, False, False, 0)

        no_mercy_info = Gtk.Label(
            wrap=True,
            max_width_chars=44,
            xalign=0,
            label=t("lockpower.no_mercy_info"),
        )
        no_mercy_info.get_style_context().add_class("dim-label")
        box.pack_start(no_mercy_info, False, False, 0)

        button_box = Gtk.ButtonBox(layout_style=Gtk.ButtonBoxStyle.END)
        box.pack_start(button_box, False, False, 0)
        close_button = Gtk.Button(label=t("lockpower.close"))
        close_button.connect("clicked", lambda _b: self.destroy())
        button_box.pack_start(close_button, False, False, 0)

    def on_minimize_changed(self, spin):
        write_setting("MINIMIZE_MINUTES", spin.get_value_as_int())

    def on_throttle_changed(self, spin):
        write_setting("BROWSER_THROTTLE_PERCENT", spin.get_value_as_int())

    def on_curtain_toggled(self, check):
        write_setting("CURTAIN_ENABLED", "true" if check.get_active() else "false")

    def on_warn_toggled(self, check):
        enabled = check.get_active()
        write_setting("WARN_BEFORE_LOCK_ENABLED", "true" if enabled else "false")
        self.warn_seconds_label.set_sensitive(enabled)
        self.warn_spin.set_sensitive(enabled)

    def on_warn_seconds_changed(self, spin):
        write_setting("WARN_SECONDS_BEFORE_LOCK", spin.get_value_as_int())

    def on_no_mercy_toggled(self, check):
        write_setting("NO_MERCY_LOCK_ENABLED", "true" if check.get_active() else "false")


def main():
    win = PowerSavingDialog()
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
