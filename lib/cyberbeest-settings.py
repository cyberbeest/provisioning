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
  wallpaper  Single picture or an hourly-rotating nature/space photo pack
         (70-rotating-wallpapers.sh; applied by cyberbeest-wallpaper-theme).

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
import json
import os
import re
import shutil
import subprocess

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

from i18n import t

CONFIG_DIR = os.path.expanduser("~/.config/cyberbeest")
CONFIG_PATH = os.path.join(CONFIG_DIR, "power-settings.conf")

# Must match this machine's live panel plugin id (~/.config/xfce4/panel/genmon-211.rc,
# the merged security-status/shutdown-timer widget -- see panel-status-genmon.sh).
GENMON_WIDGET_NAME = "__GENMON_WIDGET__"

def gopanel_exe():
    """The gopanel binary: installed link, PATH, or the dev checkout."""
    for p in (os.path.expanduser("~/.local/bin/gopanel"), shutil.which("gopanel") or "",
              os.path.expanduser("~/claude/provisioning/experimental/gopanel/gopanel"),
              os.path.expanduser("~/claude/gopanel/gopanel")):
        if p and os.access(p, os.X_OK):
            return p
    return None


def refresh_genmon():
    """Ask the running panel to re-run the status genmon now: gopanel's own refresh when it is
    the panel, else XFCE's plugin event, nothing when neither runs (xfce4-panel would pop up an
    error dialog instead)."""
    def running(name):
        return subprocess.run(["pgrep", "-x", name], capture_output=True).returncode == 0
    if running("gopanel"):
        exe = gopanel_exe()
        if exe:
            subprocess.Popen([exe, "refresh"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif running("xfce4-panel"):
        subprocess.Popen(["xfce4-panel", f"--plugin-event={GENMON_WIDGET_NAME}:refresh:bool:true"])


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
    refresh_genmon()


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


def read_panel_conf():
    out = {}
    try:
        with open(PANEL_CONF, encoding="utf-8") as f:
            for line in f:
                k, sep, v = line.strip().partition("=")
                if sep:
                    out[k] = v
    except OSError:
        pass
    return out


def write_panel_conf(key, value):
    """Set one KEY=value line in panel.conf, keeping the others (PANEL=...)."""
    conf = read_panel_conf()
    conf[key] = value
    os.makedirs(os.path.dirname(PANEL_CONF), exist_ok=True)
    with open(PANEL_CONF, "w", encoding="utf-8") as f:
        for k, v in conf.items():
            f.write("%s=%s\n" % (k, v))


def connected_monitors():
    """[(name, width, height)] of the active monitors, from xrandr."""
    try:
        out = subprocess.run(["xrandr", "--listmonitors"], capture_output=True, text=True, timeout=5,
                             env=dict(os.environ, LC_ALL="C")).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    mons = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 3:
            m = re.match(r"(\d+)/\d+x(\d+)/\d+", parts[2])
            if m:  # parts[1] is "+*NAME": + = automatic, * = primary
                mons.append((parts[1].lstrip("+*"), int(m.group(1)), int(m.group(2))))
    return mons


def current_panel():
    try:
        with open(PANEL_CONF, encoding="utf-8") as f:
            for line in f:
                if line.strip() == "PANEL=gopanel":
                    return "gopanel"
    except OSError:
        pass
    return "xfce"


BG_CYCLES = ["off", "24h", "1h", "5m", "1m", "10s"]


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

        self.mon_combo = None
        mons = connected_monitors()
        if len(mons) > 1:
            self.pack_start(Gtk.Separator(), False, False, 0)
            row = Gtk.Box(spacing=10)
            row.pack_start(Gtk.Label(label=t("panel.monitor_label"), xalign=0), False, False, 0)
            self.mon_combo = Gtk.ComboBoxText()
            self.mon_combo.append("auto", t("panel.monitor_auto"))
            for name, w, h in mons:
                self.mon_combo.append(name, "%s (%dx%d)" % (name, w, h))
            self.mon_combo.append("all", t("panel.monitor_all"))
            if not self.mon_combo.set_active_id(read_panel_conf().get("MONITOR", "auto")):
                self.mon_combo.set_active_id("auto")
            row.pack_start(self.mon_combo, False, False, 0)
            self.pack_start(row, False, False, 0)
            mnote = Gtk.Label(wrap=True, max_width_chars=44, xalign=0, label=t("panel.monitor_note"))
            mnote.get_style_context().add_class("dim-label")
            self.pack_start(mnote, False, False, 0)

        self.pack_start(Gtk.Separator(), False, False, 0)
        brow = Gtk.Box(spacing=10)
        brow.pack_start(Gtk.Label(label=t("panel.bg_label"), xalign=0), False, False, 0)
        self.bg_combo = Gtk.ComboBoxText()
        for cid in BG_CYCLES:
            self.bg_combo.append(cid, t("panel.bg_" + cid))
        if not self.bg_combo.set_active_id(read_panel_conf().get("BG_CYCLE", "off")):
            self.bg_combo.set_active_id("off")
        brow.pack_start(self.bg_combo, False, False, 0)
        self.pack_start(brow, False, False, 0)
        self.wild_check = Gtk.CheckButton(label=t("panel.bg_wild"))
        self.wild_check.set_active(read_panel_conf().get("BG_STYLE", "") == "wild")
        self.wild_check.set_sensitive(self.bg_combo.get_active_id() != "off")
        self.bg_combo.connect("changed", lambda c: self.wild_check.set_sensitive(c.get_active_id() != "off"))
        self.pack_start(self.wild_check, False, False, 0)
        bnote = Gtk.Label(wrap=True, max_width_chars=44, xalign=0, label=t("panel.bg_note"))
        bnote.get_style_context().add_class("dim-label")
        self.pack_start(bnote, False, False, 0)

        # Nothing changes until Apply or OK: what is shown now is the "applied" state.
        self.applied = self.chosen()
        buttons = Gtk.ButtonBox(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        buttons.set_layout(Gtk.ButtonBoxStyle.END)
        self.apply_btn = Gtk.Button(label=t("settings.apply"))
        self.ok_btn = Gtk.Button(label=t("settings.ok"))
        self.apply_btn.connect("clicked", lambda b: self.apply())
        self.ok_btn.connect("clicked", self.on_ok)
        buttons.pack_start(self.apply_btn, False, False, 0)
        buttons.pack_start(self.ok_btn, False, False, 0)
        self.pack_end(buttons, False, False, 0)

    def chosen(self):
        panel = "gopanel" if self.go_radio.get_active() else "xfce"
        return (panel, self.mon_combo.get_active_id() if self.mon_combo else None, self.bg_combo.get_active_id(),
                self.wild_check.get_active())

    def set_busy(self, busy):
        # grey while the panels are being switched (a few seconds), so a second click cannot
        # start another switch on top of the running one
        self.apply_btn.set_sensitive(not busy)
        self.ok_btn.set_sensitive(not busy)

    def apply(self, then=None):
        panel, monitor, bg, wild = self.chosen()
        # the settings go first: a panel that starts below reads them at startup
        if monitor is not None:
            write_panel_conf("MONITOR", monitor or "auto")
        write_panel_conf("BG_CYCLE", bg or "off")
        write_panel_conf("BG_STYLE", "wild" if wild else "")
        self.applied = (panel, monitor, bg, wild)
        self.set_busy(True)
        self.then = then
        # Always (re)apply the chosen panel, changed or not: `set` starts it if it is not
        # running and stops the other one -- a no-op when everything already is as chosen.
        try:
            self.proc = subprocess.Popen([self.script, "set", panel])
        except OSError:
            self.finish()
            return
        GLib.timeout_add(200, self.poll_set, panel)

    def poll_set(self, panel):
        if self.proc.poll() is None:
            return True
        exe = gopanel_exe() if panel == "gopanel" else None
        if exe:
            # a running panel re-reads the settings on reload and moves/copies/recolours itself
            try:
                self.proc = subprocess.Popen([exe, "reload"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                GLib.timeout_add(100, self.poll_reload)
                return False
            except OSError:
                pass
        self.finish()
        return False

    def poll_reload(self):
        if self.proc.poll() is None:
            return True
        self.finish()
        return False

    def finish(self):
        self.set_busy(False)
        if self.then:
            self.then()

    def on_ok(self, button):
        self.apply(then=lambda: self.get_toplevel().destroy())


# Texts for the Properties page of the Go panel's plugins (taken from the XFCE plugins' own
# dialogs). key -> label; ordered like the original dialogs. Unknown keys are listed at the end.
_ENABLED_SCAN = "Enabled (off freezes the scanner, centered)"
_WIDTH = "Width, pixels:"
_FPS = "Frame rate, fps:"
_MARGIN = "Margin color:"
_OFF = "\"Off\" LEDs are fully invisible (vs. dim housing color)"
_SWEEP = "Sweep pattern:"
RC_INFO = {
    "kitt-scanner": {
        "title": "Kitt Scanner",
        "about": "A scanner whose sweep speed follows the CPU load.",
        "keys": {
            "Enabled": _ENABLED_SCAN,
            "Width": _WIDTH,
            "MinRate": "Min speed (0% CPU load), sweeps/sec:",
            "MaxRate": "Max speed (100% CPU load), sweeps/sec:",
            "Gamma": "Gamma (>1 slows low load further, <1 speeds it up):",
            "FPS": _FPS,
            "MarginColor": _MARGIN,
            "UsePanelBg": "Use the panel background color for the margin",
            "OffIsBg": _OFF,
            "SineSweep": _SWEEP,
            "ShowPercent": "Show CPU load percentage over the LEDs",
            "FriendlyNames": "Use plain-English names in the Top CPU tooltip list (e.g. \"window drawing\" for Xorg)",
        },
    },
    "io-scanner": {
        "title": "I/O Scanner",
        "about": "A scanner whose sweep speed follows disk throughput.",
        "keys": {
            "Enabled": _ENABLED_SCAN,
            "MinRate": "Min speed (idle disk), sweeps/sec:",
            "MaxRate": "Max speed (full-scale I/O), sweeps/sec:",
            "Factor": "Rate factor (rate = factor * MB/s ^ exponent):",
            "Exponent": "Rate exponent (0.301 = doubles every 10x MB/s):",
            "IoMaxMbps": "Full-scale disk throughput, MB/s:",
            "Gamma": "Gamma (>1 slows low throughput further, <1 speeds it up):",
            "FPS": _FPS,
            "MarginColor": _MARGIN,
            "OffIsBg": _OFF,
            "SineSweep": _SWEEP,
            "ShowRate": "Show MB/s number over the LEDs",
        },
    },
    "network-scanner": {
        "title": "Network Scanner",
        "about": "A scanner whose sweep speed follows network traffic.",
        "keys": {
            "Enabled": _ENABLED_SCAN,
            "MinRate": "Min speed (no traffic), sweeps/sec:",
            "MaxRate": "Max speed (full-scale traffic), sweeps/sec:",
            "Factor": "Rate factor (rate = factor * MB/s ^ exponent):",
            "Exponent": "Rate exponent (0.301 = doubles every 10x MB/s):",
            "FPS": _FPS,
            "MarginColor": _MARGIN,
            "OffIsBg": _OFF,
            "SineSweep": _SWEEP,
            "ShowRate": "Show MB/s number over the LEDs",
        },
    },
    "mem-liquid": {
        "title": "Memory Liquid",
        "about": "A tank of liquid whose level shows how much memory is in use.",
        "keys": {
            "Enabled": "Enabled (off freezes the liquid motion)",
            "FPS": _FPS,
            "ShowPercent": "Show percentage inside the tank",
            "CountMapped": "Count loaded mmap'd file pages as used (e.g. LLM weights)",
            "FriendlyNames": "Use plain-English names in the Top RAM tooltip list (e.g. \"window drawing\" for Xorg)",
            "DiskWarningPercent": "Warn when disk usage reaches, %:",
            "MarginColor": _MARGIN,
        },
    },
    "wattage-panel": {
        "title": "Wattage Panel",
        "about": "Battery power draw and the estimated time remaining.",
        "keys": {"DebugRaw": "Show last 10 raw energy_now readings in tooltip (debug)"},
    },
    "genmon": {
        "title": "Generic Monitor",
        "about": "Shows the output of a command. The command prints <txt>, <img>, <tool> and <click> tags.",
        "keys": {
            "Command": "Command:",
            "UpdatePeriod": "Update period, milliseconds:",
            "UseLabel": "Show a label next to the output",
            "Text": "Label text:",
            "Font": "Font:",
        },
    },
}
# longer explanations shown as tooltips
RC_TIPS = {
    "CountMapped": "On (default): counts resident/loaded mmap'd pages as used, even though clean, because evicting "
    "an actively-read mapping (like a model file mmap'd by llama.cpp) causes real refault stalls. Off: matches "
    "MemAvailable -- clean mmap'd pages count as free. Either way the warning tracks MemAvailable.",
    "Gamma": "1 is linear. Above 1 the scanner stays slow longer as the load rises; below 1 it speeds up sooner.",
    "SineSweep": "A sine sweep slows down at each end of the track; linear keeps one constant speed.",
}


BOOL01 = {"UseLabel"}  # booleans stored as 0/1


class RcPage(Gtk.Box):
    """Properties page for a panel plugin's xfce rc file (the plugin menu's "Properties..." of
    the Go panel): one widget per key, with the wording of the original XFCE plugin dialogs,
    chosen by the value's look (true/false, number, rgb(r,g,b), anything else). Saved on
    every change; the panel notices the file change and restarts the plugin."""

    def __init__(self, path, kind=""):
        import configparser
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.set_border_width(18)
        self.path = path
        info = RC_INFO.get(kind, {})
        self.labels = info.get("keys", {})
        self.cp = configparser.RawConfigParser(strict=False)
        self.cp.optionxform = str
        with open(path, encoding="utf-8") as f:
            text = f.read()
        # some rc files (genmon) have no [section] line; give them one for parsing, leave it out on save
        self.headerless = not text.lstrip().startswith("[")
        self.cp.read_string(("[General]\n" + text) if self.headerless else text)

        head = Gtk.Label(xalign=0)
        head.set_markup("<b>%s</b>" % GLib.markup_escape_text(info.get("title", os.path.basename(path))))
        self.pack_start(head, False, False, 0)
        if info.get("about"):
            about = Gtk.Label(label=info["about"], xalign=0, wrap=True, max_width_chars=60)
            about.get_style_context().add_class("dim-label")
            self.pack_start(about, False, False, 0)
        self.pack_start(Gtk.Separator(), False, False, 0)

        grid = Gtk.Grid(column_spacing=16, row_spacing=10)
        self.pack_start(grid, False, False, 0)
        items = {}
        for section in self.cp.sections():
            for key, value in self.cp.items(section):
                items[key] = (section, value)
        order = [k for k in self.labels if k in items] + [k for k in items if k not in self.labels]
        row = 0
        for key in order:
            section, value = items[key]
            label = self.labels.get(key) or self.pretty(key)
            tip = RC_TIPS.get(key)
            if key == "SineSweep" and value in ("true", "false"):
                self.add_sweep(grid, row, section, key, label, value == "true", tip)
            elif value in ("true", "false") or (key in BOOL01 and value in ("0", "1")):
                on, off = ("1", "0") if value in ("0", "1") else ("true", "false")
                w = Gtk.CheckButton(label=label)
                w.get_child().set_line_wrap(True)
                w.set_active(value == on)
                w.connect("toggled", lambda b, s=section, k=key, on=on, off=off: self.save(s, k, on if b.get_active() else off))
                if tip:
                    w.set_tooltip_text(tip)
                grid.attach(w, 0, row, 2, 1)
            else:
                lab = Gtk.Label(label=label, xalign=0, wrap=True, max_width_chars=44)
                lab.set_hexpand(True)
                if tip:
                    lab.set_tooltip_text(tip)
                grid.attach(lab, 0, row, 1, 1)
                grid.attach(self.widget_for(section, key, value), 1, row, 1, 1)
            row += 1

    @staticmethod
    def pretty(key):
        import re
        if key.isupper():
            return key
        return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", key).capitalize() + ":"

    def add_sweep(self, grid, row, section, key, label, sine, tip):
        lab = Gtk.Label(label=label, xalign=0, yalign=0)
        grid.attach(lab, 0, row, 1, 1)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        r1 = Gtk.RadioButton.new_with_label(None, "Sine wave (eases at each end)")
        r2 = Gtk.RadioButton.new_with_label_from_widget(r1, "Linear (constant speed)")
        (r1 if sine else r2).set_active(True)
        r1.connect("toggled", lambda b: self.save(section, key, "true" if b.get_active() else "false"))
        box.pack_start(r1, False, False, 0)
        box.pack_start(r2, False, False, 0)
        grid.attach(box, 1, row, 1, 1)

    def save(self, section, key, value):
        self.cp.set(section, key, str(value))
        import io
        buf = io.StringIO()
        self.cp.write(buf, space_around_delimiters=False)
        out = buf.getvalue()
        if self.headerless and out.startswith("[General]\n"):
            out = out[len("[General]\n"):]
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(out)

    def widget_for(self, section, key, value):
        import re
        m = re.fullmatch(r"rgb\((\d+),\s*(\d+),\s*(\d+)\)", value.strip())
        if m:
            rgba = Gdk.RGBA()
            rgba.red, rgba.green, rgba.blue = (int(m.group(i)) / 255 for i in (1, 2, 3))
            rgba.alpha = 1.0
            w = Gtk.ColorButton.new_with_rgba(rgba)

            def picked(b):
                c = b.get_rgba()
                self.save(section, key, "rgb(%d,%d,%d)" % tuple(round(x * 255) for x in (c.red, c.green, c.blue)))

            w.connect("color-set", picked)
            return w
        if re.fullmatch(r"-?\d+", value):
            w = Gtk.SpinButton.new_with_range(-1000000, 1000000, 1)
            w.set_value(int(value))
            w.connect("value-changed", lambda b: self.save(section, key, b.get_value_as_int()))
            return w
        if re.fullmatch(r"-?\d+\.\d+", value):
            w = Gtk.SpinButton.new_with_range(-1000000, 1000000, 0.1)
            w.set_digits(2)
            w.set_value(float(value))
            w.connect("value-changed", lambda b: self.save(section, key, ("%.2f" % b.get_value()).rstrip("0").rstrip(".")))
            return w
        w = Gtk.Entry()
        w.set_text(value)
        w.set_width_chars(44)
        w.connect("changed", lambda e: self.save(section, key, e.get_text()))
        return w


BUTLER_DIRS = [
    os.path.expanduser("~/.local/share/cyberbeest/butler"),
    os.path.expanduser("~/claude/provisioning/experimental/butler"),
]
BUTLER_CONF_DIR = os.path.join(CONFIG_DIR, "butler")


def butler_catalog_dir():
    for d in BUTLER_DIRS:
        if os.path.isdir(os.path.join(d, "butler", "catalog")):
            return os.path.join(d, "butler", "catalog")
    return None


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


class ButlerPage(Gtk.Box):
    """Butler on/off for the menu search (gopanel reads settings.json when the menu opens)."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_border_width(16)
        self.settings_path = os.path.join(BUTLER_CONF_DIR, "settings.json")
        self.settings = {"enabled": True, **read_json(self.settings_path, {})}

        info = Gtk.Label(wrap=True, max_width_chars=60, xalign=0, label=t("butler.info"))
        self.pack_start(info, False, False, 0)
        enabled = Gtk.CheckButton(label=t("butler.enabled"))
        enabled.set_active(bool(self.settings["enabled"]))
        enabled.connect("toggled", self.on_enabled)
        self.pack_start(enabled, False, False, 0)
        note = Gtk.Label(wrap=True, xalign=0, label=t("butler.note"))
        note.get_style_context().add_class("dim-label")
        self.pack_start(note, False, False, 0)

    def on_enabled(self, check):
        self.settings["enabled"] = check.get_active()
        write_json(self.settings_path, self.settings)


WALLPAPER_PACK = "/usr/share/backgrounds/cyberbeest"
WALLPAPER_HELPER = "/usr/local/bin/cyberbeest-wallpaper-theme"
WALLPAPER_SAVED = os.path.join(CONFIG_DIR, "wallpaper-previous.tsv")


def wallpaper_choice_now():
    """nature / space while xfdesktop cycles through that pack, standard for our own
    default picture, else previous (a picture the user chose)."""
    def q(path):
        r = subprocess.run(["xfconf-query", "-c", "xfce4-desktop", "-p", path],
                           capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""
    mon = subprocess.run("xrandr --current | awk '/ connected/{print $1; exit}'",
                         shell=True, capture_output=True, text=True).stdout.strip()
    base = f"/backdrop/screen0/monitor{mon}/workspace0"
    image = q(base + "/last-image")
    if q(base + "/backdrop-cycle-enable") == "true":
        for theme in ("nature", "space"):
            if image.startswith(f"{WALLPAPER_PACK}/{theme}/"):
                return theme
    if image.startswith("/usr/share/backgrounds/xfce/cyberbeest-fallback."):
        return "standard"
    return "previous"


class WallpaperPage(Gtk.Box):
    """Standard picture, the user's own picture, or an hourly-rotating photo pack
    (xfdesktop's own cycling)."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_border_width(16)
        self.pack_start(Gtk.Label(wrap=True, max_width_chars=60, xalign=0,
                                  label=t("wallpaper.info")), False, False, 0)
        current = wallpaper_choice_now()
        group = None
        for choice, key in (("standard", "wallpaper.standard"), ("previous", "wallpaper.previous"),
                            ("nature", "wallpaper.nature"), ("space", "wallpaper.space")):
            radio = Gtk.RadioButton.new_with_label_from_widget(group, t(key))
            group = group or radio
            radio.set_active(choice == current)
            if choice == "previous":
                # Only meaningful when a picture of the user's is shown or was saved.
                has_saved = os.path.exists(WALLPAPER_SAVED) and os.path.getsize(WALLPAPER_SAVED) > 0
                radio.set_sensitive(current == "previous" or has_saved)
            radio.connect("toggled", self.on_toggled, choice)
            self.pack_start(radio, False, False, 0)
        settings = Gtk.LinkButton.new_with_label("", t("wallpaper.desktop_settings"))
        settings.connect("activate-link", self.on_desktop_settings)
        settings.set_halign(Gtk.Align.START)
        self.pack_start(settings, False, False, 0)
        credits = Gtk.LinkButton.new_with_label("file://" + WALLPAPER_PACK + "/CREDITS.md",
                                                t("wallpaper.credits"))
        credits.set_halign(Gtk.Align.START)
        self.pack_start(credits, False, False, 0)

    def on_toggled(self, radio, choice):
        if radio.get_active():
            subprocess.Popen([WALLPAPER_HELPER, choice])

    def on_desktop_settings(self, button):
        subprocess.Popen(["xfdesktop-settings"])
        return True


PAGES = [
    ("power", "settings.tab_power", lambda: PowerPage()),
    ("panel", "settings.tab_panel", lambda: PanelPage(panel_choice_script()) if panel_choice_script() else None),
    ("wallpaper", "settings.tab_wallpaper", lambda: WallpaperPage() if os.access(WALLPAPER_HELPER, os.X_OK) and os.path.isdir(WALLPAPER_PACK) else None),
    ("butler", "settings.tab_butler", lambda: ButlerPage() if butler_catalog_dir() else None),
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
    ap.add_argument("--rc", help="open the Properties page of this plugin rc file instead")
    ap.add_argument("--title", default="")
    ap.add_argument("--kind", default="", help="plugin type (kitt-scanner, genmon, ...) for the wording")
    args = ap.parse_args()
    if args.rc:
        win = Gtk.Window(title=t("settings.props_title").format(name=args.title or os.path.basename(args.rc)))
        win.set_position(Gtk.WindowPosition.CENTER)
        win.connect("destroy", Gtk.main_quit)
        win.set_default_size(560, -1)
        win.add(RcPage(args.rc, args.kind))
        win.set_focus(None)
        win.show_all()
        Gtk.main()
        return
    win = SettingsWindow(args.tab)
    win.show_all()
    win.select_tab()
    Gtk.main()


if __name__ == "__main__":
    main()
