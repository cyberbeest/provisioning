#!/usr/bin/env python3
"""Login-time nag: if the LUKS master and/or cyberbeest login (short)
password still match the value recorded at initial-set time (see
cyberbeest-record-initial-password.sh), prompt the user to change it via
cyberbeest-change-password (disk_password_gui.py). Re-checks after that GUI
closes and keeps nagging as long as a still-default password remains and
hasn't been explicitly dismissed.

Delegates the actual root-level test to cyberbeest-check-default-passwords
via `sudo -n` -- a narrowly-scoped NOPASSWD sudoers rule allows exactly that
one fixed command with no arguments, so this runs without an interactive
auth prompt. This script itself never touches /etc/shadow or the LUKS
header directly, and the checker never prints the actual password values.

If nothing was ever recorded (self-installer who set their own real
password during Debian install), the checker prints nothing and this exits
immediately without showing anything.
"""

import os
import subprocess

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from i18n import t

CHECKER = "/usr/local/sbin/cyberbeest-check-default-passwords"
CHANGE_GUI = os.path.expanduser("~/.local/bin/cyberbeest-change-password")
DISMISS_FILE = os.path.expanduser("~/.config/cyberbeest/password-nag-dismissed")

TITLES = {"master": t("pw.master_title"), "short": t("pw.short_title")}


def run_check():
    try:
        out = subprocess.run(
            ["sudo", "-n", CHECKER],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    result = {}
    for line in out.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()
    return result


def load_dismissed():
    if not os.path.exists(DISMISS_FILE):
        return set()
    with open(DISMISS_FILE, encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def save_dismissed(dismissed):
    os.makedirs(os.path.dirname(DISMISS_FILE), exist_ok=True)
    with open(DISMISS_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(dismissed)) + ("\n" if dismissed else ""))


def still_pending(check, dismissed):
    """Returns {type: tag} for types still on their recorded initial value and not dismissed."""
    pending = {}
    for ptype, key in (("master", "MASTER"), ("short", "SHORT")):
        if ptype in dismissed:
            continue
        if check.get(f"{key}_STILL_DEFAULT") == "1":
            pending[ptype] = check.get(f"{key}_TAG", "weak")
    return pending


def show_nag(pending):
    """Returns ("change", ptype), ("keep", ptype), or ("later", None)."""
    dialog = Gtk.MessageDialog(
        message_type=Gtk.MessageType.WARNING,
        text=t("nag.title"),
    )

    lines = []
    for ptype, tag in pending.items():
        title = TITLES[ptype]
        if tag == "secure":
            lines.append(f"{title}: {t('nag.still_secure_default')}")
        else:
            lines.append(f"{title}: {t('nag.still_temp_default')}")
    dialog.format_secondary_text("\n\n".join(lines))

    dialog.add_button(t("nag.remind_later"), 0)
    action_for_response = {}
    next_id = 1
    for ptype in pending:
        dialog.add_button(t("nag.change_now").format(title=TITLES[ptype]), next_id)
        action_for_response[next_id] = ("change", ptype)
        next_id += 1
    for ptype, tag in pending.items():
        if tag == "secure":
            dialog.add_button(t("nag.keep").format(title=TITLES[ptype]), next_id)
            action_for_response[next_id] = ("keep", ptype)
            next_id += 1

    response = dialog.run()
    dialog.destroy()
    # Pump pending events so the dialog window actually disappears before a
    # potentially slow subprocess (the change-password GUI) starts.
    while Gtk.events_pending():
        Gtk.main_iteration()

    return action_for_response.get(response, ("later", None))


def main():
    dismissed = load_dismissed()
    while True:
        check = run_check()
        pending = still_pending(check, dismissed)
        if not pending:
            return

        action, ptype = show_nag(pending)

        if action == "change":
            subprocess.run([CHANGE_GUI, "--tab", ptype])
            continue  # re-check after the GUI closes

        if action == "keep":
            dismissed.add(ptype)
            save_dismissed(dismissed)
            continue  # re-check -- the other type might still be pending

        return  # "later" -- stop nagging for this login


if __name__ == "__main__":
    main()
