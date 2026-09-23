#!/usr/bin/env python3
"""Cyberbeest Send Report.

Builds a failure report for one provisioning script, strips personal data
from it, and shows the owner the exact text in an editable window. Nothing
leaves the machine until they click Send.

Usage: cyberbeest-send-report.py [--print] SCRIPT.sh [EXIT_STATUS]

The report has no machine ID, so two reports from the same laptop can't be
linked. The receiver (reports.cyberbeest.com) does not store IP addresses.
"""
import getpass
import ipaddress
import os
import pwd
import re
import socket
import subprocess
import sys
import threading
import urllib.error
import urllib.request

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

LIB_DIR = os.path.dirname(os.path.abspath(__file__))
PROVISIONING_DIR = os.path.dirname(LIB_DIR)
sys.path.insert(0, LIB_DIR)
from i18n import t  # noqa: E402

REPORT_URL = os.environ.get("CYBERBEEST_REPORT_URL", "https://reports.cyberbeest.com/report")
LOG_TAIL_LINES = 100
MAX_REPORT_BYTES = 64 * 1024
# Shipped defaults: the same on every machine, so they identify nobody, and
# scrubbing them would mangle names like cyberbeest-update.sh in the log.
GENERIC_NAMES = {"cyberbeest", "localhost", "debian", "root"}


def _git(*args):
    try:
        return subprocess.run(
            ["git", "-C", PROVISIONING_DIR, *args],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _log_tail(script):
    text = _read(os.path.join(PROVISIONING_DIR, script[:-3] + ".log"))
    if not text:
        return t("report.no_log")
    return "\n".join(text.splitlines()[-LOG_TAIL_LINES:])


def _known_wifi_names():
    try:
        out = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    names = []
    for line in out.splitlines():
        name, _, kind = line.rpartition(":")
        if "wireless" in kind and len(name) >= 3:
            names.append(name.replace("\\:", ":"))
    return names


def _replace_word(text, word, replacement):
    return re.sub(r"(?<![\w.-])" + re.escape(word) + r"(?![\w-])", replacement, text)


def _scrub_ips(text):
    def ip_or_keep(match):
        candidate = match.group(0)
        try:
            ip = ipaddress.ip_address(candidate)
        except ValueError:
            return candidate
        if ip.is_loopback or ip.is_unspecified:
            return candidate
        return "<ipv4>" if ip.version == 4 else "<ipv6>"

    text = re.sub(r"(?<![\w.])\d{1,3}(?:\.\d{1,3}){3}(?![\w.])", ip_or_keep, text)
    return re.sub(r"(?<![\w:])[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}(?![\w:])", ip_or_keep, text)


def scrub(text):
    user = getpass.getuser()
    home = os.path.expanduser("~")
    real_name = pwd.getpwuid(os.getuid()).pw_gecos.split(",")[0].strip()
    host = socket.gethostname()

    text = text.replace(home, "~")
    text = re.sub(r"/home/[^/\s]+", "/home/<user>", text)
    for name, label in ((real_name, "<name>"), (user, "<user>"), (host, "<host>")):
        if len(name) >= 3 and name.lower() not in GENERIC_NAMES:
            text = _replace_word(text, name, label)
    for ssid in _known_wifi_names():
        text = text.replace(ssid, "<wifi>")
    text = re.sub(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b", "<email>", text)
    text = re.sub(r"\b[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}\b", "<mac>", text)
    return _scrub_ips(text)


def build_report(script, status):
    commit = _git("rev-parse", "--short", "HEAD") or "?"
    track = _git("rev-parse", "--abbrev-ref", "HEAD") or "?"
    debian = _read("/etc/debian_version").strip() or "?"
    header = [
        "Cyberbeest failure report",
        f"Script:       {script}",
        f"Exit status:  {status}",
        f"Provisioning: {track} @ {commit}",
        f"Debian:       {debian}",
        "",
        f"--- last {LOG_TAIL_LINES} lines of {script[:-3]}.log ---",
    ]
    return scrub("\n".join(header) + "\n" + _log_tail(script) + "\n")


class SendReportWindow(Gtk.Window):
    def __init__(self, script, status):
        super().__init__(title=t("report.window_title"))
        self.set_default_size(760, 540)
        self.set_border_width(12)
        self.connect("destroy", Gtk.main_quit)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(root)

        intro = Gtk.Label(label=t("report.intro").format(script=script), xalign=0)
        intro.set_line_wrap(True)
        root.pack_start(intro, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_shadow_type(Gtk.ShadowType.IN)
        self.text_view = Gtk.TextView()
        self.text_view.set_monospace(True)
        self.text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.text_view.get_buffer().set_text(build_report(script, status))
        scroller.add(self.text_view)
        root.pack_start(scroller, True, True, 0)

        self.status_label = Gtk.Label(label=t("report.privacy_note"), xalign=0)
        self.status_label.set_line_wrap(True)
        self.status_label.set_ellipsize(Pango.EllipsizeMode.NONE)
        root.pack_start(self.status_label, False, False, 0)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        root.pack_start(buttons, False, False, 0)
        self.close_button = Gtk.Button(label=t("report.cancel"))
        self.close_button.connect("clicked", lambda _b: self.destroy())
        buttons.pack_end(self.close_button, False, False, 0)
        self.send_button = Gtk.Button(label=t("report.send"))
        self.send_button.get_style_context().add_class("suggested-action")
        self.send_button.connect("clicked", self.on_send)
        buttons.pack_end(self.send_button, False, False, 0)

    def on_send(self, _button):
        buf = self.text_view.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        data = text.encode("utf-8")
        if not text.strip():
            self.status_label.set_text(t("report.empty"))
            return
        if len(data) > MAX_REPORT_BYTES:
            self.status_label.set_text(t("report.too_large"))
            return
        self.send_button.set_sensitive(False)
        self.text_view.set_editable(False)
        self.status_label.set_text(t("report.sending"))
        threading.Thread(target=self._post, args=(data,), daemon=True).start()

    def _post(self, data):
        request = urllib.request.Request(
            REPORT_URL, data=data, method="POST",
            headers={"Content-Type": "text/plain; charset=utf-8", "User-Agent": "cyberbeest-report"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                reply = response.read().decode("utf-8", "replace").strip()
            GLib.idle_add(self._on_sent, reply)
        except urllib.error.HTTPError as e:
            GLib.idle_add(self._on_failed, e.read().decode("utf-8", "replace").strip() or str(e))
        except (urllib.error.URLError, OSError) as e:
            GLib.idle_add(self._on_failed, str(getattr(e, "reason", e)))

    def _on_sent(self, reply):
        self.status_label.set_text(t("report.sent").format(reply=reply))
        self.close_button.set_label(t("report.close"))

    def _on_failed(self, error):
        self.status_label.set_text(t("report.failed").format(error=error))
        self.send_button.set_sensitive(True)
        self.text_view.set_editable(True)


def main():
    # --print: write the scrubbed report to stdout instead of opening the window.
    args = [a for a in sys.argv[1:] if a != "--print"]
    if not args or not args[0].endswith(".sh"):
        print("usage: cyberbeest-send-report.py [--print] SCRIPT.sh [EXIT_STATUS]", file=sys.stderr)
        sys.exit(2)
    script = os.path.basename(args[0])
    status = args[1] if len(args) > 1 else "?"
    if "--print" in sys.argv:
        print(build_report(script, status))
        return
    SendReportWindow(script, status).show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
