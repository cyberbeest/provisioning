#!/usr/bin/env python3
"""Post-install setup for Proton VPN, right after it's installed via the
Cyberbeest Package Manager's opt-in "Proton VPN" row. Two independent bits,
both filling gaps Proton's own app leaves open:

1. Autostart at login: Proton's own app has no "launch at login" setting.
   The proton-vpn-gnome-desktop package we install is just an empty
   metapackage (`dpkg -L` on it lists no .desktop file); the real one --
   currently proton.vpn.app.gtk.desktop, `Exec=protonvpn-app` -- is
   registered by whichever dependency package actually ships the GTK app,
   and that has changed across Proton's own package splits before. So
   instead of trusting any particular package name, this scans
   /usr/share/applications for a .desktop file whose Exec line invokes the
   protonvpn-app binary, and (after asking via a GTK Yes/No dialog) copies
   that file, unmodified, into ~/.config/autostart/ -- the actual XDG
   equivalent of a Windows Startup folder.

2. Kill switch: pre-seeds Proton's own settings.json with the "Standard"
   kill switch turned on (disconnects the internet if the VPN connection
   drops -- only once actually connected, unlike the stronger "Advanced"
   mode which can block all internet before first connect and isn't set
   here). Silent, no dialog -- Proton's own settings persistence
   (proton.vpn.core.settings) only fills in missing keys from defaults, so
   pre-writing this key before first login sticks, and only writes it if
   the key isn't already present (never overwrites an explicit user choice
   from a previous install).

Runs unprivileged, as the user (no pkexec). Idempotent: safe to re-run.
Call with no args after install (silently pre-seeds the kill switch, then
shows the autostart Yes/No dialog); call with "remove" after uninstall to
kill any still-running protonvpn-app instance (apt removing the package
doesn't touch an already-running process -- it keeps its tray icon and
all until killed or logged out) and clean up the autostart entry, both
silently, no dialog. The kill switch preference is left alone on remove,
same as any other app's user config.
"""

import glob
import os
import subprocess
import sys

APPLICATIONS_DIR = "/usr/share/applications"
EXEC_BINARY = "protonvpn-app"
AUTOSTART_DIR = os.path.expanduser("~/.config/autostart")
KILLSWITCH_STANDARD = 1


def find_desktop_file():
    for path in glob.glob(os.path.join(APPLICATIONS_DIR, "*.desktop")):
        try:
            with open(path, encoding="utf-8") as f:
                contents = f.read()
        except OSError:
            continue
        for line in contents.splitlines():
            if not line.startswith("Exec="):
                continue
            command = line[len("Exec="):].split()[0] if line[len("Exec="):].split() else ""
            if os.path.basename(command) == EXEC_BINARY:
                return path
    return None


def install_autostart(desktop_file):
    os.makedirs(AUTOSTART_DIR, exist_ok=True)
    with open(desktop_file, encoding="utf-8") as f:
        contents = f.read()
    if "X-GNOME-Autostart-enabled" not in contents:
        contents = contents.rstrip("\n") + "\nX-GNOME-Autostart-enabled=true\n"
    dest = os.path.join(AUTOSTART_DIR, os.path.basename(desktop_file))
    with open(dest, "w", encoding="utf-8") as f:
        f.write(contents)


def ask_yes_no():
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    dialog = Gtk.MessageDialog(
        transient_for=None,
        modal=True,
        message_type=Gtk.MessageType.QUESTION,
        buttons=Gtk.ButtonsType.YES_NO,
        text="Start Proton VPN automatically when you log in?",
    )
    dialog.format_secondary_text(
        "Proton VPN doesn't offer this itself. You can undo it later by "
        "uninstalling Proton VPN from the Package Manager, which removes "
        "this too."
    )
    response = dialog.run()
    dialog.destroy()
    return response == Gtk.ResponseType.YES


def preseed_killswitch():
    try:
        from proton.vpn.core.cache_handler import CacheHandler
        from proton.vpn.core.settings.settings import SETTINGS
    except ImportError:
        return  # proton package not importable here -- nothing to seed

    handler = CacheHandler(SETTINGS)
    data = handler.load() or {}
    if "killswitch" in data:
        return  # already set, by us before or by the user -- don't clobber
    data["killswitch"] = KILLSWITCH_STANDARD
    handler.save(data)


def do_install():
    preseed_killswitch()

    desktop_file = find_desktop_file()
    if not desktop_file:
        return  # package didn't register a .desktop entry -- nothing to offer
    if ask_yes_no():
        install_autostart(desktop_file)


def kill_running_app():
    # apt removing the package doesn't touch an already-running instance --
    # it keeps running from its now-unlinked binary, tray icon and all,
    # until killed or logged out. pkill excludes its own process, so this
    # can't self-match.
    subprocess.run(["pkill", "-f", EXEC_BINARY], check=False)


def do_remove():
    kill_running_app()

    if not os.path.isdir(AUTOSTART_DIR):
        return
    for name in os.listdir(AUTOSTART_DIR):
        if "proton" in name.lower() and name.endswith(".desktop"):
            os.remove(os.path.join(AUTOSTART_DIR, name))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "remove":
        do_remove()
    else:
        do_install()


if __name__ == "__main__":
    main()
