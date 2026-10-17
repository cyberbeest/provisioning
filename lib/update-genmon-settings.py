#!/usr/bin/env python3
"""Settings for the security-update panel icon (update-genmon.sh).

Launched from the log dialog's "Settings..." button
(update-genmon-view-log.py). Currently one setting: how long to wait after
startup before the first update check (2 minutes at least), so a machine that sometimes resets
shortly after a cold boot isn't caught mid-install.

Enforcement lives in security-update-check.sh, which reads
/etc/cyberbeest/security-update.conf. That file is root-owned, so saving goes
through the scoped sudo rule for security-update-set-startup-delay (see
lib/setup-security-update-timer.sh).
"""

import subprocess

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from i18n import t

CONF_PATH = "/etc/cyberbeest/security-update.conf"
HELPER = "/usr/local/sbin/security-update-set-startup-delay"
# Must match the whitelist in the helper. 2 is the minimum and the default.
PRESETS = [2, 5, 10, 30, 60]


def read_delay():
    try:
        with open(CONF_PATH, encoding="utf-8") as f:
            for line in f:
                key, _, value = line.strip().partition("=")
                if key == "STARTUP_DELAY_MINUTES" and value.isdigit():
                    return max(int(value), 2)
    except OSError:
        pass
    return 2


def label(minutes):
    return f"{minutes} min"


def main():
    current = read_delay()

    win = Gtk.Window(title=t("update_genmon.settings_title"))
    win.set_border_width(12)
    win.connect("destroy", Gtk.main_quit)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    win.add(box)

    prompt = Gtk.Label(label=t("update_genmon.delay_prompt"), xalign=0)
    prompt.set_line_wrap(True)
    prompt.set_max_width_chars(48)
    box.pack_start(prompt, False, False, 0)

    group = None
    chosen = [current]
    for preset in PRESETS:
        item = Gtk.RadioButton.new_with_label_from_widget(group, label(preset))
        group = item
        item.set_active(preset == current)
        item.connect("toggled", lambda i, p=preset: chosen.__setitem__(0, p) if i.get_active() else None)
        box.pack_start(item, False, False, 0)

    hint = Gtk.Label(label=t("update_genmon.delay_hint"), xalign=0)
    hint.set_line_wrap(True)
    hint.set_max_width_chars(48)
    box.pack_start(hint, False, False, 4)

    buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    buttons.set_halign(Gtk.Align.END)
    cancel = Gtk.Button(label=t("update_genmon.cancel"))
    cancel.connect("clicked", lambda b: win.destroy())
    save = Gtk.Button(label=t("update_genmon.save"))

    def on_save(_b):
        try:
            result = subprocess.run(
                ["sudo", "-n", HELPER, str(chosen[0])],
                capture_output=True, text=True, timeout=15,
            )
            ok = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        if ok:
            win.destroy()
            return
        err = Gtk.MessageDialog(
            transient_for=win, message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK, text=t("update_genmon.settings_save_failed"),
        )
        err.run()
        err.destroy()

    save.connect("clicked", on_save)
    buttons.pack_start(cancel, False, False, 0)
    buttons.pack_start(save, False, False, 0)
    box.pack_start(buttons, False, False, 8)

    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
