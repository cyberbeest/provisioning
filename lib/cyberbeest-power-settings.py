#!/usr/bin/env python3
"""Cyberbeest Power Settings.

Controls behavior of the lock-shutdown-watcher user service: how many
minutes it stays locked before shutting down -- on AC and on battery,
either linked to a single value or set independently -- and whether it
cycles suspend/wake on battery while locked (to still deliver notification
sounds) or just stays awake until the shutdown, same as on AC, plus
the awake/asleep minutes used for that cycle.

Written as a self-contained Gtk.Box page (PowerSettingsPage) so it can later
be dropped into a unified Cyberbeest Settings dialog as a tab, rather than
staying its own top-level window forever.

The panel's shutdown-timer genmon icon (shutdown-timer-genmon.sh) and its
click menu (shutdown-timer-menu.py) read/write the same config file and
duplicate the small bits of read/write logic below rather than importing
this module, matching how the lock-shutdown-watcher shell script already
does its own independent read_setting().
"""

import os
import subprocess

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

CONFIG_DIR = os.path.expanduser("~/.config/cyberbeest")
CONFIG_PATH = os.path.join(CONFIG_DIR, "power-settings.conf")

# Substituted at install time to match the panel-layout template's genmon plugin id.
GENMON_WIDGET_NAME = "__GENMON_WIDGET__"

DEFAULTS = {
    "NOTIFICATIONS_WHEN_LOCKED": "false",  # experimental, off by default
    "AC_SHUTDOWN_MINUTES": "60",
    "BATTERY_SHUTDOWN_MINUTES": "60",
    "LINK_AC_BATTERY": "true",
    "AWAKE_MINUTES": "1",
    "ASLEEP_MINUTES": "9",
}

# Pre-split config files only have this one key; treat it as the value for
# both AC_SHUTDOWN_MINUTES and BATTERY_SHUTDOWN_MINUTES until the file is
# next saved, at which point it's replaced by the two new keys below.
LEGACY_SHUTDOWN_KEY = "SHUTDOWN_MINUTES"


def read_settings():
    settings = dict(DEFAULTS)
    seen = set()
    legacy_shutdown = None
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" not in line or line.startswith("#"):
                    continue
                key, value = line.split("=", 1)
                value = value.strip()
                if key in DEFAULTS:
                    settings[key] = value
                    seen.add(key)
                elif key == LEGACY_SHUTDOWN_KEY:
                    legacy_shutdown = value
    if legacy_shutdown is not None:
        if "AC_SHUTDOWN_MINUTES" not in seen:
            settings["AC_SHUTDOWN_MINUTES"] = legacy_shutdown
        if "BATTERY_SHUTDOWN_MINUTES" not in seen:
            settings["BATTERY_SHUTDOWN_MINUTES"] = legacy_shutdown
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
                "This machine locks after 5 minutes idle and, by default, fully shuts "
                "down after being continuously locked, for safety. Set a time to 0 for "
                "“Never” to disable auto-shutdown for that power source."
            ),
        )
        self.pack_start(info, False, False, 0)

        self.link_check = Gtk.CheckButton(label="Use the same time on AC and battery")
        self.link_check.set_active(settings["LINK_AC_BATTERY"] == "true")
        self.link_check.connect("toggled", self.on_link_toggled)
        self.pack_start(self.link_check, False, False, 0)

        shutdown_grid = Gtk.Grid(column_spacing=10, row_spacing=8)
        self.pack_start(shutdown_grid, False, False, 0)

        self.ac_label = Gtk.Label(xalign=0)
        shutdown_grid.attach(self.ac_label, 0, 0, 1, 1)
        self.ac_spin = Gtk.SpinButton.new_with_range(0, 480, 5)
        self.ac_spin.set_value(int(settings["AC_SHUTDOWN_MINUTES"]))
        self.ac_spin.connect("value-changed", self.on_ac_changed)
        self.ac_spin.connect("output", self.on_spin_output)
        shutdown_grid.attach(self.ac_spin, 1, 0, 1, 1)

        self.battery_label = Gtk.Label(label="On battery (minutes locked):", xalign=0)
        self.battery_label.set_no_show_all(True)
        shutdown_grid.attach(self.battery_label, 0, 1, 1, 1)
        self.battery_spin = Gtk.SpinButton.new_with_range(0, 480, 5)
        self.battery_spin.set_value(int(settings["BATTERY_SHUTDOWN_MINUTES"]))
        self.battery_spin.connect("value-changed", self.on_battery_changed)
        self.battery_spin.connect("output", self.on_spin_output)
        self.battery_spin.set_no_show_all(True)
        shutdown_grid.attach(self.battery_spin, 1, 1, 1, 1)

        self._update_link_visibility()

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

    def _update_link_visibility(self):
        linked = self.link_check.get_active()
        self.ac_label.set_text(
            "Shutdown after (minutes locked):" if linked else "On AC power (minutes locked):"
        )
        if linked:
            self.battery_label.hide()
            self.battery_spin.hide()
        else:
            self.battery_label.show()
            self.battery_spin.show()

    def on_link_toggled(self, _button):
        linked = self.link_check.get_active()
        write_setting("LINK_AC_BATTERY", "true" if linked else "false")
        if linked:
            self.battery_spin.set_value(self.ac_spin.get_value_as_int())
        self._update_link_visibility()
        self._saved()

    def on_spin_output(self, spin):
        # 0 means "Never" (auto-shutdown disabled for that power source) --
        # display it as text instead of "0".
        value = spin.get_value_as_int()
        spin.set_text("Never" if value == 0 else str(value))
        return True

    def on_ac_changed(self, _spin):
        value = self.ac_spin.get_value_as_int()
        write_setting("AC_SHUTDOWN_MINUTES", value)
        if self.link_check.get_active():
            self.battery_spin.set_value(value)
        self._saved()

    def on_battery_changed(self, _spin):
        write_setting("BATTERY_SHUTDOWN_MINUTES", self.battery_spin.get_value_as_int())
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
