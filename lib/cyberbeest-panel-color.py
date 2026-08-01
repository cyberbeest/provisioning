#!/usr/bin/env python3
"""Cyberbeest Panel Color.

Sets the xfce4-panel background color and keeps the kitt-scanner LED
plugin's margin color in sync with it -- kitt-scanner.c hardcodes its own
background to match the *default* theme color (#F6F5F4) rather than
reading the panel's live background, so a plain panel color change alone
leaves it looking like a mismatched patch.

Written as a self-contained Gtk.Box page (PanelColorPage) so it can later
be dropped into a unified Cyberbeest Settings dialog as a tab, rather than
staying its own top-level window forever.
"""

import os
import subprocess
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

from i18n import t

# How long to wait after the last color pick before actually restarting
# kitt-scanner -- clicking through several swatches quickly would otherwise
# fire one restart per click. Coalescing into one restart after the user
# settles on a color keeps things responsive without spamming restarts.
KITT_RESTART_DEBOUNCE_MS = 700

# xfce4-panel permanently drops an external plugin (with a "do you want to
# restart it?" dialog) if it exits more than once within its own hardcoded
# 60-second window -- this is a global property of the panel, not something
# tunable here, so restart_kitt_scanner() below enforces a real minimum gap
# between restarts on top of the debounce above, persisted to disk so it
# holds across separate script/GUI invocations (e.g. manual testing) too.
KITT_MIN_RESTART_INTERVAL_S = 65
KITT_RESTART_STATE_PATH = os.path.expanduser("~/.cache/cyberbeest/kitt-scanner-last-restart")

PANEL_XFCONF_PROP = "/panels/panel-1"

# Substituted at install time to match the panel-layout template's
# kitt-scanner plugin instance (12-xfce-panel-layout.sh: kitt-scanner-14.rc).
KITT_RC_PATH = "__KITT_RC_PATH__"

# Same value as kitt-scanner.c's DEFAULT_BG -- the panel theme's actual
# background, used when "Theme default" is picked.
THEME_DEFAULT_RGB = (0.9647, 0.9608, 0.9569)


def _presets():
    # Built lazily (not at import time) so it reads the active locale.
    return [
        (t("panelcolor.preset_theme_default"), None),
        (t("panelcolor.preset_slate_blue"), (0.60, 0.70, 0.90)),
        (t("panelcolor.preset_forest_green"), (0.55, 0.75, 0.60)),
        (t("panelcolor.preset_warm_amber"), (0.85, 0.70, 0.45)),
        (t("panelcolor.preset_charcoal"), (0.25, 0.25, 0.28)),
    ]


def set_panel_color(rgb):
    if rgb is None:
        subprocess.run(
            ["xfconf-query", "-c", "xfce4-panel", "-p", f"{PANEL_XFCONF_PROP}/background-style", "-s", "0"],
            check=True,
        )
        return
    r, g, b = rgb
    subprocess.run(
        ["xfconf-query", "-c", "xfce4-panel", "-p", f"{PANEL_XFCONF_PROP}/background-style", "-s", "1"],
        check=True,
    )
    subprocess.run(
        [
            "xfconf-query", "-c", "xfce4-panel", "-p", f"{PANEL_XFCONF_PROP}/background-rgba",
            "-n", "-t", "double", "-t", "double", "-t", "double", "-t", "double",
            "-s", str(r), "-s", str(g), "-s", str(b), "-s", "1.0",
        ],
        check=True,
    )


def write_kitt_margin_color(rgb):
    if not os.path.exists(KITT_RC_PATH):
        return
    r, g, b = (round(c * 255) for c in (rgb if rgb is not None else THEME_DEFAULT_RGB))
    new_line = f"MarginColor=rgb({r},{g},{b})\n"

    with open(KITT_RC_PATH, encoding="utf-8") as f:
        lines = f.readlines()
    for i, line in enumerate(lines):
        if line.startswith("MarginColor="):
            lines[i] = new_line
            break
    else:
        lines.append(new_line)
    with open(KITT_RC_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)


def _read_last_kitt_restart():
    try:
        with open(KITT_RESTART_STATE_PATH, encoding="utf-8") as f:
            return float(f.read().strip())
    except (OSError, ValueError):
        return 0.0


def _write_last_kitt_restart(ts):
    os.makedirs(os.path.dirname(KITT_RESTART_STATE_PATH), exist_ok=True)
    with open(KITT_RESTART_STATE_PATH, "w", encoding="utf-8") as f:
        f.write(str(ts))


def _do_kitt_restart_now():
    # kitt-scanner only reads its rc file at startup, so restart its wrapper
    # process to pick up the new margin color -- xfce4-panel respawns
    # external plugins automatically when their process exits.
    subprocess.run(["pkill", "-f", "libkitt-scanner.so"])
    _write_last_kitt_restart(time.time())


_kitt_restart_lock = threading.Lock()
_kitt_restart_pending_timer = None


def restart_kitt_scanner():
    """Restart kitt-scanner's wrapper process, respecting the panel's
    60s crash-loop guard. If called again before enough time has passed,
    coalesces into a single delayed restart rather than queuing one per
    call -- the rc file (written separately by write_kitt_margin_color)
    already holds whatever color should apply once it fires."""
    global _kitt_restart_pending_timer
    with _kitt_restart_lock:
        elapsed = time.time() - _read_last_kitt_restart()
        if elapsed >= KITT_MIN_RESTART_INTERVAL_S:
            _do_kitt_restart_now()
            return
        if _kitt_restart_pending_timer is not None and _kitt_restart_pending_timer.is_alive():
            return
        delay = KITT_MIN_RESTART_INTERVAL_S - elapsed
        _kitt_restart_pending_timer = threading.Timer(delay, _do_kitt_restart_now)
        _kitt_restart_pending_timer.daemon = True
        _kitt_restart_pending_timer.start()


def set_kitt_margin_color(rgb):
    write_kitt_margin_color(rgb)
    restart_kitt_scanner()


def apply_color(rgb):
    set_panel_color(rgb)
    set_kitt_margin_color(rgb)


class PanelColorPage(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.set_border_width(16)

        heading = Gtk.Label(xalign=0)
        heading.set_markup(f"<b>{t('panelcolor.heading')}</b>")
        self.pack_start(heading, False, False, 0)

        info = Gtk.Label(
            wrap=True,
            max_width_chars=44,
            xalign=0,
            label=t("panelcolor.info"),
        )
        self.pack_start(info, False, False, 0)

        warning = Gtk.Label(
            wrap=True,
            max_width_chars=44,
            xalign=0,
            label=t("panelcolor.warning"),
        )
        warning.get_style_context().add_class("dim-label")
        self.pack_start(warning, False, False, 0)

        swatch_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.pack_start(swatch_row, False, False, 0)
        for name, rgb in _presets():
            swatch_row.pack_start(self._make_swatch(name, rgb), False, False, 0)

        custom_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.pack_start(custom_row, False, False, 0)
        custom_row.pack_start(Gtk.Label(label=t("panelcolor.custom")), False, False, 0)
        self.color_button = Gtk.ColorButton()
        self.color_button.connect("color-set", self.on_custom_color_set)
        custom_row.pack_start(self.color_button, False, False, 0)

        self.status_label = Gtk.Label(label="", xalign=0)
        self.status_label.set_no_show_all(True)
        self.pack_start(self.status_label, False, False, 0)
        self._hide_status_timeout = None
        self._kitt_restart_timeout = None

    def _make_swatch(self, name, rgb):
        button = Gtk.Button()
        button.set_tooltip_text(name)
        button.set_size_request(36, 28)
        swatch_rgb = rgb if rgb is not None else THEME_DEFAULT_RGB
        r, g, b = (round(c * 255) for c in swatch_rgb)

        css = Gtk.CssProvider()
        css.load_from_data(
            f"button {{ background-image: none; background-color: rgb({r},{g},{b}); }}".encode()
        )
        button.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        button.connect("clicked", self.on_preset_clicked, rgb)
        return button

    def on_preset_clicked(self, _button, rgb):
        self._apply(rgb)

    def on_custom_color_set(self, button):
        rgba = button.get_rgba()
        self._apply((rgba.red, rgba.green, rgba.blue))

    def _apply(self, rgb):
        set_panel_color(rgb)
        write_kitt_margin_color(rgb)
        if self._kitt_restart_timeout is not None:
            GLib.source_remove(self._kitt_restart_timeout)
        self._kitt_restart_timeout = GLib.timeout_add(
            KITT_RESTART_DEBOUNCE_MS, self._do_kitt_restart
        )
        self._saved()

    def _do_kitt_restart(self):
        restart_kitt_scanner()
        self._kitt_restart_timeout = None
        return False

    def _saved(self):
        self.status_label.set_text(t("panelcolor.applied"))
        self.status_label.set_no_show_all(False)
        self.status_label.show()
        if self._hide_status_timeout is not None:
            GLib.source_remove(self._hide_status_timeout)
        self._hide_status_timeout = GLib.timeout_add_seconds(3, self._hide_status)

    def _hide_status(self):
        self.status_label.hide()
        self._hide_status_timeout = None
        return False


class PanelColorWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title=t("panelcolor.window_title"))
        self.set_default_size(340, -1)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("destroy", Gtk.main_quit)
        self.add(PanelColorPage())


def main():
    win = PanelColorWindow()
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
