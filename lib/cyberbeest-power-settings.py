#!/usr/bin/env python3
"""Cyberbeest Power Settings.

Controls behavior of the lock-shutdown-watcher user service: how many
minutes it stays locked before shutting down, and whether it cycles
suspend/wake on battery while locked (to still deliver notification
sounds) or just stays awake until the shutdown, same as on AC, plus
the awake/asleep minutes used for that cycle.

Written as a self-contained Gtk.Box page (PowerSettingsPage) so it can later
be dropped into a unified Cyberbeest Settings dialog as a tab, rather than
staying its own top-level window forever.
"""

import os

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

CONFIG_DIR = os.path.expanduser("~/.config/cyberbeest")
CONFIG_PATH = os.path.join(CONFIG_DIR, "power-settings.conf")

DEFAULTS = {
    "NOTIFICATIONS_WHEN_LOCKED": "false",  # experimental, off by default
    "SHUTDOWN_MINUTES": "60",
    "AWAKE_MINUTES": "1",
    "ASLEEP_MINUTES": "9",
}


def read_settings():
    settings = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
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


class PowerSettingsPage(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.set_border_width(16)
        settings = read_settings()

        heading = Gtk.Label(xalign=0)
        heading.set_markup("<b>Locked screen behavior</b>")
        self.pack_start(heading, False, False, 0)

        info = Gtk.Label(
            wrap=True,
            max_width_chars=40,
            xalign=0,
            label=(
                "This machine locks after 5 minutes idle and fully shuts down after "
                "being continuously locked, for safety."
            ),
        )
        self.pack_start(info, False, False, 0)

        shutdown_grid = Gtk.Grid(column_spacing=10, row_spacing=8)
        self.pack_start(shutdown_grid, False, False, 0)

        shutdown_grid.attach(Gtk.Label(label="Shutdown after (minutes locked):", xalign=0), 0, 0, 1, 1)
        self.shutdown_spin = Gtk.SpinButton.new_with_range(5, 480, 5)
        self.shutdown_spin.set_value(int(settings["SHUTDOWN_MINUTES"]))
        self.shutdown_spin.connect("value-changed", self.on_shutdown_changed)
        shutdown_grid.attach(self.shutdown_spin, 1, 0, 1, 1)

        experimental_frame = Gtk.Frame()
        experimental_frame.set_label_widget(Gtk.Label(label="  Experimental  "))
        experimental_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        experimental_box.set_border_width(10)
        experimental_frame.add(experimental_box)
        self.pack_start(experimental_frame, False, False, 0)

        self.notif_check = Gtk.CheckButton(
            label="Play notifications while locked, on battery"
        )
        self.notif_check.set_active(settings["NOTIFICATIONS_WHEN_LOCKED"] == "true")
        self.notif_check.connect("toggled", self.on_toggled)
        experimental_box.pack_start(self.notif_check, False, False, 0)

        detail = Gtk.Label(
            wrap=True,
            max_width_chars=40,
            xalign=0,
            label=(
                "When enabled, on battery the machine cycles suspend and wake during "
                "that hour instead of staying fully awake, so notification sounds can "
                "still come through periodically while using much less power. "
                "Messages may arrive late, up to the asleep time below. "
                "On AC power this has no effect — the machine just "
                "stays awake for the whole locked period."
            ),
        )
        detail.get_style_context().add_class("dim-label")
        experimental_box.pack_start(detail, False, False, 0)

        cycle_grid = Gtk.Grid(column_spacing=10, row_spacing=8)
        experimental_box.pack_start(cycle_grid, False, False, 0)

        cycle_grid.attach(Gtk.Label(label="Awake minutes per cycle:", xalign=0), 0, 0, 1, 1)
        self.awake_spin = Gtk.SpinButton.new_with_range(1, 60, 1)
        self.awake_spin.set_value(int(settings["AWAKE_MINUTES"]))
        self.awake_spin.connect("value-changed", self.on_awake_changed)
        cycle_grid.attach(self.awake_spin, 1, 0, 1, 1)

        cycle_grid.attach(Gtk.Label(label="Asleep minutes per cycle:", xalign=0), 0, 1, 1, 1)
        self.asleep_spin = Gtk.SpinButton.new_with_range(1, 60, 1)
        self.asleep_spin.set_value(int(settings["ASLEEP_MINUTES"]))
        self.asleep_spin.connect("value-changed", self.on_asleep_changed)
        cycle_grid.attach(self.asleep_spin, 1, 1, 1, 1)

        self.status_label = Gtk.Label(label="", xalign=0)
        self.status_label.set_no_show_all(True)
        self.pack_start(self.status_label, False, False, 0)
        self._hide_status_timeout = None

    def _saved(self):
        self.status_label.set_text(
            "Saved. Takes effect on the next lock cycle, no restart needed."
        )
        self.status_label.set_no_show_all(False)
        self.status_label.show()

        if self._hide_status_timeout is not None:
            GLib.source_remove(self._hide_status_timeout)
        self._hide_status_timeout = GLib.timeout_add_seconds(5, self._hide_status)

    def _hide_status(self):
        self.status_label.hide()
        self._hide_status_timeout = None
        return False

    def on_shutdown_changed(self, _spin):
        write_setting("SHUTDOWN_MINUTES", self.shutdown_spin.get_value_as_int())
        self._saved()

    def on_toggled(self, _button):
        write_setting("NOTIFICATIONS_WHEN_LOCKED", "true" if self.notif_check.get_active() else "false")
        self._saved()

    def on_awake_changed(self, _spin):
        write_setting("AWAKE_MINUTES", self.awake_spin.get_value_as_int())
        self._saved()

    def on_asleep_changed(self, _spin):
        write_setting("ASLEEP_MINUTES", self.asleep_spin.get_value_as_int())
        self._saved()


class PowerSettingsWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Cyberbeest Power Settings")
        self.set_default_size(380, -1)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("destroy", Gtk.main_quit)
        self.add(PowerSettingsPage())


def main():
    win = PowerSettingsWindow()
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
