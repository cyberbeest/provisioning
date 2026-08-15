#!/usr/bin/env python3
"""Plays the shutdown chime by holding a logind shutdown "delay" inhibitor
lock, instead of a systemd system-unit ExecStop hook.

Why: the previous approach (a system oneshot service whose ExecStop ran
`aplay` right before poweroff.target) raced the actual power-off against
audio playback with no real synchronization -- it played but got cut off,
and after adding a trailing `sleep 1` to buy margin, went silent entirely
(most likely PulseAudio/PipeWire's own teardown, which can happen in
parallel with our ExecStop, muting/disabling the speaker amp before our
raw ALSA aplay ran).

A delay inhibitor lock genuinely blocks logind from proceeding with
shutdown until we release it (or InhibitDelayMaxSec elapses, default 5s --
see /etc/systemd/logind.conf), and it's taken by a normal user-session
process, so it runs *before* session teardown starts: PulseAudio/PipeWire
and whatever amp/routing state they set up are still fully alive, and we
play through the normal desktop audio stack (paplay) instead of bypassing
it.

Runs as a systemd --user service with Restart=always: each time it (re)
starts it grabs a fresh lock, waits for logind's PrepareForShutdown
signal, plays the chime, then releases the lock and exits -- letting
shutdown proceed.
"""
import os
import subprocess
import sys

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

CHIME = os.path.expanduser("~/.local/share/sounds/cyberbeest-shutdown-chime.wav")
STATE_FILE = os.path.expanduser("~/.config/cyberbeest/shutdown-chime-enabled")


def is_enabled():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return f.read().strip() != "0"
    except OSError:
        return True


def is_rebooting():
    # PrepareForShutdown fires the same way for both poweroff and reboot --
    # only play the chime for an actual power-off, not a restart.
    try:
        out = subprocess.run(
            ["systemctl", "list-jobs", "--no-legend"],
            capture_output=True, text=True, check=False,
        ).stdout
        return "reboot.target" in out
    except Exception:
        return False


def take_inhibitor(bus):
    result, fd_list = bus.call_with_unix_fd_list_sync(
        "org.freedesktop.login1",
        "/org/freedesktop/login1",
        "org.freedesktop.login1.Manager",
        "Inhibit",
        GLib.Variant("(ssss)", ("shutdown", "cyberbeest-shutdown-chime", "Play the shutdown chime", "delay")),
        GLib.VariantType("(h)"),
        Gio.DBusCallFlags.NONE,
        -1,
        None,
        None,
    )
    handle = result.unpack()[0]
    return fd_list.get(handle)


def main():
    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    fd = take_inhibitor(bus)
    loop = GLib.MainLoop()

    def on_prepare_for_shutdown(_conn, _sender, _path, _iface, _signal, params):
        (starting,) = params.unpack()
        if not starting:
            return
        if not is_rebooting() and is_enabled():
            subprocess.run(["paplay", CHIME], check=False)
        os.close(fd)
        loop.quit()

    bus.signal_subscribe(
        "org.freedesktop.login1",
        "org.freedesktop.login1.Manager",
        "PrepareForShutdown",
        "/org/freedesktop/login1",
        None,
        Gio.DBusSignalFlags.NONE,
        on_prepare_for_shutdown,
    )

    loop.run()


if __name__ == "__main__":
    sys.exit(main())
