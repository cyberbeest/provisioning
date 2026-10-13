#!/usr/bin/env python3
"""Cyberbeest Settings: one window with vertical tabs (Gtk.StackSidebar).
Each tab is a self-contained page class that builds into a Gtk.Box, so adding
another dialog means writing one more page and registering it in PAGES.

Tabs:
  power  Extended power options: the power-saving-while-locked settings (window
         minimizing + browser CPU throttling) used by lock-shutdown-watcher.sh,
         the instant-cover curtain toggle (see lock-screen-curtain.sh), and the
         pre-lock warning notification (see lock-warning-watcher.sh).
  panel  Which panel runs: the stock XFCE panel or the experimental Go panel.
         Only shown where the panel switcher (cyberbeest-panel-choice.sh) is
         installed, i.e. on the dev machine for now.

Launch with --tab=<name> to open on a given tab (the shutdown timer menu's
"Extended power options..." item uses --tab=power). Run as a separate process
from that menu, rather than a Gtk.Dialog inside its process -- see the comment
on open_power_saving_dialog() there for why.

The power tab reads/writes the same config file as lock-shutdown-watcher.sh
and shutdown-timer-menu.py, and keeps its own copy of DEFAULTS (matching the
menu's full set, not just the keys shown here) so a save doesn't drop the
shutdown-timer's own keys -- same duplication convention the rest of this
family of scripts already uses.
"""

import argparse
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


class PowerPage(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.set_border_width(16)
        settings = read_settings()
        box = self

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


PANEL_CHOICE_SCRIPTS = [
    os.path.expanduser("~/.local/bin/cyberbeest-panel-choice.sh"),
    os.path.expanduser("~/claude/provisioning/experimental/gopanel/cyberbeest-panel-choice.sh"),
]
PANEL_CONF = os.path.join(CONFIG_DIR, "panel.conf")


def panel_choice_script():
    for p in PANEL_CHOICE_SCRIPTS:
        if os.access(p, os.X_OK):
            return p
    return None


def current_panel():
    try:
        with open(PANEL_CONF, encoding="utf-8") as f:
            for line in f:
                if line.strip() == "PANEL=gopanel":
                    return "gopanel"
    except OSError:
        pass
    return "xfce"


class PanelPage(Gtk.Box):
    def __init__(self, script):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.set_border_width(16)
        self.script = script

        info = Gtk.Label(wrap=True, max_width_chars=44, xalign=0, label=t("panel.info"))
        self.pack_start(info, False, False, 0)

        self.xfce_radio = Gtk.RadioButton.new_with_label_from_widget(None, t("panel.xfce"))
        self.go_radio = Gtk.RadioButton.new_with_label_from_widget(self.xfce_radio, t("panel.gopanel"))
        (self.go_radio if current_panel() == "gopanel" else self.xfce_radio).set_active(True)
        self.pack_start(self.xfce_radio, False, False, 0)
        self.pack_start(self.go_radio, False, False, 0)

        note = Gtk.Label(wrap=True, max_width_chars=44, xalign=0, label=t("panel.note"))
        note.get_style_context().add_class("dim-label")
        self.pack_start(note, False, False, 0)

        self.xfce_radio.connect("toggled", self.on_toggled, "xfce")
        self.go_radio.connect("toggled", self.on_toggled, "gopanel")

    def on_toggled(self, radio, which):
        if radio.get_active():
            # Switching takes a few seconds (starts one panel, then stops the other).
            subprocess.Popen([self.script, "set", which])


PAGES = [
    ("power", "settings.tab_power", lambda: PowerPage()),
    ("panel", "settings.tab_panel", lambda: PanelPage(panel_choice_script()) if panel_choice_script() else None),
]


class SettingsWindow(Gtk.Window):
    def __init__(self, tab):
        super().__init__(title=t("settings.window_title"))
        self.set_default_size(640, 420)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("destroy", Gtk.main_quit)

        paned = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.add(paned)
        stack = self.stack = Gtk.Stack()
        stack.set_transition_type(Gtk.StackTransitionType.NONE)
        sidebar = Gtk.StackSidebar()
        sidebar.set_stack(stack)
        paned.pack_start(sidebar, False, False, 0)
        paned.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)
        paned.pack_start(stack, True, True, 0)

        for name, title_key, build in PAGES:
            page = build()
            if page is not None:
                stack.add_titled(page, name, t(title_key))
        self.tab = tab

    def select_tab(self):
        # Only works once the pages are shown, so call after show_all().
        if self.stack.get_child_by_name(self.tab):
            self.stack.set_visible_child_name(self.tab)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tab", default="power")
    args = ap.parse_args()
    win = SettingsWindow(args.tab)
    win.show_all()
    win.select_tab()
    Gtk.main()


if __name__ == "__main__":
    main()
