#!/usr/bin/env python3
"""Quick popup menu for the shutdown-timer panel icon (shutdown-timer-genmon.sh).

Lets you pick a preset auto-shutdown-while-locked time for AC/battery
(linked or independent) without opening the full Cyberbeest Power Settings
dialog, which is still one click away via "More settings...". Reads/writes
the same config file as cyberbeest_power_settings_gui.py and duplicates its
small read/write helpers rather than importing it, matching how the
lock-shutdown-watcher shell script and the genmon script also each keep
their own copy.
"""

import os
import subprocess

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk

from i18n import t

CONFIG_DIR = os.path.expanduser("~/.config/cyberbeest")
CONFIG_PATH = os.path.join(CONFIG_DIR, "power-settings.conf")
SETTINGS_GUI = os.path.expanduser("~/claude/cyberbeest_power_settings_gui.py")

# Must match this machine's live panel plugin id (~/.config/xfce4/panel/genmon-25.rc).
GENMON_WIDGET_NAME = "__GENMON_WIDGET__"

DEFAULTS = {
    "NOTIFICATIONS_WHEN_LOCKED": "false",
    "AC_SHUTDOWN_MINUTES": "60",
    "BATTERY_SHUTDOWN_MINUTES": "60",
    "LINK_AC_BATTERY": "true",
    "AWAKE_MINUTES": "1",
    "ASLEEP_MINUTES": "9",
}
LEGACY_SHUTDOWN_KEY = "SHUTDOWN_MINUTES"

# 0 is the "Never" sentinel -- lock-shutdown-watcher.sh skips the shutdown
# check entirely for that power source when it reads 0. Listed last since
# it's conceptually the far end of the scale (infinity), not a short time.
PRESETS = [15, 30, 60, 120, 240, 0]

# The idle-to-lock delay isn't part of power-settings.conf -- xfce4-screensaver
# 4.18 reads it from gsettings directly (org.gnome.desktop.session idle-delay,
# in seconds), same as lock-countdown-genmon.sh already does. 0 is the same
# "Never" sentinel as PRESETS above -- gsettings' idle-delay=0 is the
# documented way to disable idle-triggered locking/blanking entirely.
LOCK_PRESETS = [1, 2, 5, 10, 15, 30, 0]


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


def write_settings(updates):
    settings = read_settings()
    settings.update(updates)
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        for k in DEFAULTS:
            f.write(f"{k}={settings[k]}\n")
    # Otherwise the panel icon only catches up at its next 30s poll.
    subprocess.Popen(["xfce4-panel", f"--plugin-event={GENMON_WIDGET_NAME}:refresh:bool:true"])


def fmt(mins):
    mins = int(mins)
    if mins == 0:
        return t("timer.never")
    if mins % 60 == 0:
        return f"{mins // 60}h"
    if mins >= 60:
        return f"{mins // 60}h{mins % 60}m"
    return f"{mins}m"


def get_idle_delay_minutes():
    try:
        out = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.session", "idle-delay"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        seconds = int(out.split()[-1])  # e.g. "uint32 300"
    except Exception:
        seconds = 300
    if seconds == 0:
        return 0  # Never -- don't clamp this one up to 1 minute below
    return max(1, round(seconds / 60))


def set_idle_delay_minutes(mins):
    subprocess.run(
        ["gsettings", "set", "org.gnome.desktop.session", "idle-delay", str(mins * 60)],
        check=False,
    )
    # Keep the display's DPMS sleep/off timing in step with the lock delay,
    # so the screen doesn't stay lit well past when it's already locked (or
    # blank long before). off is sleep+1 so there's still a brief dimmed
    # state instead of jumping straight to fully off. This can't track a
    # mid-lock wake-by-click-without-unlocking perfectly (DPMS then restarts
    # its own countdown from that click), but it keeps the common path --
    # idle straight through to lock -- in sync. mins=0 (Never) disables DPMS
    # auto-sleep/off too, rather than leaving "off" dangling at 1 minute
    # below a disabled "sleep".
    dpms_off = mins + 1 if mins > 0 else 0
    subprocess.run(
        ["xfconf-query", "-c", "xfce4-power-manager", "-p", "/xfce4-power-manager/dpms-on-ac-sleep", "-s", str(mins)],
        check=False,
    )
    subprocess.run(
        ["xfconf-query", "-c", "xfce4-power-manager", "-p", "/xfce4-power-manager/dpms-on-ac-off", "-s", str(dpms_off)],
        check=False,
    )
    # Also clear/sync the legacy X11 screensaver timeout (xset s). It's a
    # separate mechanism from gsettings idle-delay and from xfce4-power-manager's
    # DPMS keys above, and nothing else in this stack ever touches it -- a
    # leftover value (e.g. from an old autostart script) would otherwise sit
    # there forever, silently re-blanking/re-locking on its own schedule even
    # after idle-delay is set to "Never".
    xset_secs = mins * 60
    subprocess.run(["xset", "s", str(xset_secs), str(xset_secs)], check=False)
    restart_screensaver()


def restart_screensaver():
    # xfce4-screensaver reads idle-delay once at startup and doesn't pick up
    # live gsettings changes, so a running daemon keeps locking on whatever
    # value was active when it launched until it's restarted.
    subprocess.run(["pkill", "-f", "^xfce4-screensaver$"], check=False)
    subprocess.Popen(
        ["xfce4-screensaver"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def open_settings(_item):
    subprocess.Popen([SETTINGS_GUI])


def run_logout_action(_item, cmd):
    Gtk.main_quit()
    subprocess.Popen(cmd)


def add_preset_section(menu, label, key, current, linked):
    header = Gtk.MenuItem(label=label)
    header.set_sensitive(False)
    menu.append(header)

    # Build every item and settle its active state *before* connecting any
    # "toggled" handler. GtkRadioMenuItem's group bookkeeping can flip an
    # earlier item's active state as a side effect of activating a later
    # one (e.g. the first item in a fresh group starts active by default),
    # so connecting handlers inline in the same loop that calls
    # set_active() let an already-wired earlier item's handler fire from
    # that internal deactivation -- which is what caused every selection to
    # actually persist whichever preset happened to be first (15m).
    items = []
    group = None
    for preset in PRESETS:
        item = Gtk.RadioMenuItem.new_with_label_from_widget(group, fmt(preset))
        group = item
        item.set_active(preset == current)
        menu.append(item)
        items.append((item, preset))

    for item, preset in items:
        def on_toggled(item, preset=preset, key=key):
            if not item.get_active():
                return
            updates = {key: str(preset)}
            if linked:
                other_key = (
                    "BATTERY_SHUTDOWN_MINUTES" if key == "AC_SHUTDOWN_MINUTES" else "AC_SHUTDOWN_MINUTES"
                )
                updates[other_key] = str(preset)
            write_settings(updates)
            Gtk.main_quit()

        item.connect("toggled", on_toggled)


def add_lock_delay_section(menu):
    header = Gtk.MenuItem(label=t("timer.lock_screen_after"))
    header.set_sensitive(False)
    menu.append(header)

    current = get_idle_delay_minutes()

    # Same two-phase construction as add_preset_section, for the same reason.
    items = []
    group = None
    for preset in LOCK_PRESETS:
        item = Gtk.RadioMenuItem.new_with_label_from_widget(group, fmt(preset))
        group = item
        item.set_active(preset == current)
        menu.append(item)
        items.append((item, preset))

    for item, preset in items:
        def on_toggled(item, preset=preset):
            if not item.get_active():
                return
            set_idle_delay_minutes(preset)
            Gtk.main_quit()

        item.connect("toggled", on_toggled)


def build_menu():
    settings = read_settings()
    linked = settings["LINK_AC_BATTERY"] == "true"
    ac_min = int(settings["AC_SHUTDOWN_MINUTES"])
    bat_min = int(settings["BATTERY_SHUTDOWN_MINUTES"])

    menu = Gtk.Menu()

    # Same actions/commands as the Power launcher's cyberbeest-logout dialog.
    for label, cmd in (
        (t("timer.lock_now"), ["xflock4"]),
        (t("timer.restart_now"), ["xfce4-session-logout", "--reboot"]),
        (t("timer.shutdown_now"), ["xfce4-session-logout", "--halt"]),
    ):
        logout_item = Gtk.MenuItem(label=label)
        logout_item.connect("activate", run_logout_action, cmd)
        menu.append(logout_item)
    menu.append(Gtk.SeparatorMenuItem())

    add_lock_delay_section(menu)
    menu.append(Gtk.SeparatorMenuItem())

    title = Gtk.MenuItem(label=t("timer.auto_shutdown_while_locked"))
    title.set_sensitive(False)
    menu.append(title)
    menu.append(Gtk.SeparatorMenuItem())

    link_item = Gtk.CheckMenuItem(label=t("timer.use_same_time"))
    link_item.set_active(linked)

    def on_link_toggled(item):
        new_linked = item.get_active()
        updates = {"LINK_AC_BATTERY": "true" if new_linked else "false"}
        if new_linked:
            updates["BATTERY_SHUTDOWN_MINUTES"] = str(ac_min)
        write_settings(updates)
        Gtk.main_quit()

    link_item.connect("toggled", on_link_toggled)
    menu.append(link_item)
    menu.append(Gtk.SeparatorMenuItem())

    if linked:
        add_preset_section(menu, t("timer.shutdown_after_both"), "AC_SHUTDOWN_MINUTES", ac_min, linked)
    else:
        add_preset_section(menu, t("timer.on_ac"), "AC_SHUTDOWN_MINUTES", ac_min, linked)
        menu.append(Gtk.SeparatorMenuItem())
        add_preset_section(menu, t("timer.on_battery"), "BATTERY_SHUTDOWN_MINUTES", bat_min, linked)

    menu.append(Gtk.SeparatorMenuItem())
    more_item = Gtk.MenuItem(label=t("timer.more_settings"))
    more_item.connect("activate", open_settings)
    menu.append(more_item)

    menu.show_all()
    return menu


def main():
    menu = build_menu()
    menu.connect("deactivate", lambda _m: Gtk.main_quit())

    # Launched standalone by genmon's <click>, with no triggering GTK event
    # and no widget of our own realized yet, so popup_at_pointer(None) fails
    # (it needs a GdkWindow to anchor to). Anchor to the root window instead,
    # at the actual pointer position.
    display = Gdk.Display.get_default()
    pointer = display.get_default_seat().get_pointer()
    screen, px, py = pointer.get_position()
    rect = Gdk.Rectangle()
    rect.x, rect.y, rect.width, rect.height = px, py, 1, 1
    menu.popup_at_rect(screen.get_root_window(), rect, Gdk.Gravity.NORTH_WEST, Gdk.Gravity.NORTH_WEST, None)

    Gtk.main()


if __name__ == "__main__":
    main()
