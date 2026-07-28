#!/usr/bin/env python3
"""GUI front-end for run-all.sh / run-changed.sh.

Runs as the normal (non-root) user. Elevates once via `sudo -A`, using
lib/zenity-askpass.sh as the graphical password prompt, then runs the
chosen script (run-all.sh or run-changed.sh) as a single root subprocess,
streaming its stdout/stderr live into the log view -- same one-password,
one-process model as `sudo ./run-all.sh` in a terminal, just graphical.

"Stop after current script" doesn't kill the subprocess -- it touches
.graceful-stop-requested next to the scripts, which run-all.sh/run-changed.sh
check between scripts (see their own comments). Whatever script is currently
running always finishes; only the next one is skipped.

Dev tool only (not shipped to end users), so unlike lib/*.py it doesn't use
lib/i18n.py.
"""
import os
import subprocess
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

DIR = os.path.dirname(os.path.realpath(__file__))
STOP_FILE = os.path.join(DIR, ".graceful-stop-requested")
ASKPASS = os.path.join(DIR, "lib", "zenity-askpass.sh")


class RunGuiWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Cyberbeest Provisioning Runner")
        self.set_default_size(760, 520)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("destroy", self.on_destroy)

        self.proc = None
        self.stop_requested = False

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        root.set_border_width(12)
        self.add(root)

        mode_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        root.pack_start(mode_box, False, False, 0)

        self.radio_changed = Gtk.RadioButton.new_with_label_from_widget(
            None, "Run changed scripts only (run-changed.sh)"
        )
        self.radio_all = Gtk.RadioButton.new_with_label_from_widget(
            self.radio_changed, "Run all scripts (run-all.sh)"
        )
        mode_box.pack_start(self.radio_changed, False, False, 0)
        mode_box.pack_start(self.radio_all, False, False, 0)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        root.pack_start(button_box, False, False, 0)

        self.start_button = Gtk.Button(label="Start")
        self.start_button.connect("clicked", self.on_start)
        button_box.pack_start(self.start_button, False, False, 0)

        self.stop_button = Gtk.Button(label="Stop after current script")
        self.stop_button.set_sensitive(False)
        self.stop_button.connect("clicked", self.on_stop)
        button_box.pack_start(self.stop_button, False, False, 0)

        self.status_label = Gtk.Label(label="Idle.", xalign=0)
        root.pack_start(self.status_label, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        root.pack_start(scroller, True, True, 0)

        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_cursor_visible(False)
        self.log_view.set_monospace(True)
        self.log_buffer = self.log_view.get_buffer()
        scroller.add(self.log_view)

        self.show_all()

    def append_log(self, text):
        end = self.log_buffer.get_end_iter()
        self.log_buffer.insert(end, text)
        mark = self.log_buffer.create_mark(None, self.log_buffer.get_end_iter(), False)
        self.log_view.scroll_to_mark(mark, 0.0, False, 0.0, 1.0)
        if "=== running " in text:
            script = text.split("=== running ", 1)[1].split(" ===", 1)[0].strip()
            self.status_label.set_text(f"Running: {script}")

    def on_start(self, _button):
        if self.proc is not None:
            return
        try:
            if os.path.exists(STOP_FILE):
                os.remove(STOP_FILE)
        except OSError:
            pass

        script = "run-all.sh" if self.radio_all.get_active() else "run-changed.sh"
        self.log_buffer.set_text("")
        self.status_label.set_text(f"Starting {script} (enter sudo password if prompted)...")
        self.start_button.set_sensitive(False)
        self.stop_button.set_sensitive(True)
        self.stop_requested = False

        env = dict(os.environ)
        env["SUDO_ASKPASS"] = ASKPASS
        self.proc = subprocess.Popen(
            ["sudo", "-A", "-p", "", "bash", script],
            cwd=DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        threading.Thread(target=self._read_output, args=(self.proc,), daemon=True).start()

    def _read_output(self, proc):
        for line in proc.stdout:
            GLib.idle_add(self.append_log, line)
        status = proc.wait()
        GLib.idle_add(self._on_finished, proc, status)

    def _on_finished(self, proc, status):
        if proc is not self.proc:
            return
        self.proc = None
        self.start_button.set_sensitive(True)
        self.stop_button.set_sensitive(False)
        if self.stop_requested:
            self.status_label.set_text("Stopped after current script.")
        elif status == 0:
            self.status_label.set_text("Finished successfully.")
        else:
            self.status_label.set_text(f"Failed (exit {status}) -- see log above.")

    def on_stop(self, _button):
        if self.proc is None:
            return
        self.stop_requested = True
        self.stop_button.set_sensitive(False)
        self.status_label.set_text("Stop requested -- finishing current script, then stopping...")
        try:
            with open(STOP_FILE, "w"):
                pass
        except OSError as e:
            self.append_log(f"\n[run-gui.py] couldn't write stop file: {e}\n")

    def on_destroy(self, _window):
        if self.proc is not None and self.proc.poll() is None:
            self.append_log("\n[run-gui.py] window closed while a run was active -- ")
            self.append_log("leaving the root process running; check a terminal with `ps` if unsure.\n")
        Gtk.main_quit()


def main():
    RunGuiWindow()
    Gtk.main()


if __name__ == "__main__":
    main()
