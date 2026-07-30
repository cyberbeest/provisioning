#!/usr/bin/env python3
"""GUI front-end for the NN-*.sh provisioning scripts.

Unlike the old version of this tool, it does NOT shell out to run-all.sh /
run-changed.sh. It lists every NN-*.sh script in a sidebar (with a status:
pending/done/running/failed, "done" meaning its .log is newer than the
script -- same test run-changed.sh uses), and runs each one directly as its
own `sudo -A bash NN-*.sh` subprocess, streaming its output into the shared
log view on the right and updating that script's sidebar status as it goes.

"Run all" / "Run changed only" walk the whole list; double-clicking a single
row in the sidebar runs just that script (handy for debugging one step),
regardless of whether it's already marked done. Only one run -- whole
sequence or single script -- can be active at a time.

No batch-level xfce4-panel reload here (unlike run-all.sh/run-changed.sh):
the only two scripts that touch panel config, 11-xfce-panel-plugins.sh and
12-xfce-panel-layout.sh, already reload the panel themselves.

Scripts in NEEDS_TERMINAL (currently just 00-locale-keyboard-timezone.sh)
use whiptail, which needs a real controlling terminal to draw its menus --
piping its stdout/stderr into our log view like every other script breaks
that. Those are instead opened in an xterm window (still elevated via the
same graphical sudo prompt) and we block until it closes, rather than
streaming their output into the shared log pane. Deliberately xterm, not
xfce4-terminal: xfce4-terminal is a D-Bus single-instance app, so a new
invocation can silently hand its command off to an already-running
xfce4-terminal (e.g. the one run-gui.py itself was launched from) and exit
immediately -- no window appears and we stop "blocking" before the command
even starts. xterm has no such client/server model, so it can't do that.

xterm also doesn't reliably propagate the wrapped command's own exit status
as its own -- it exits 0 on normal termination regardless of how the command
inside it fared -- so _run_in_terminal captures the real exit code to a temp
file from inside the shell instead of trusting xterm's proc.returncode.

Requires zenity (for the graphical sudo prompt). On a brand new machine that
hasn't run any NN-*.sh script yet, zenity may not be installed at all (it's
only otherwise pulled in as a side effect of 04-software-launch-warning.sh)
-- checked for at startup and installed automatically if missing (plain
`sudo apt-get install`, prompting on whatever terminal this tool itself was
launched from, since the graphical askpass obviously can't be used yet).

Every script subprocess gets stdin=DEVNULL and start_new_session=True: without
those, a script inherits run-gui.py's own stdin/process group -- i.e. the
terminal it was launched from, if any -- and a subprocess still alive when
the window is closed can be left holding that terminal's controlling tty,
making it look frozen even though it's really just an orphaned background
process waiting to read from a tty nothing will ever type into again.

Dev tool only (not shipped to end users), so unlike lib/*.py it doesn't use
lib/i18n.py.
"""
import glob
import os
import shutil
import subprocess
import tempfile
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango

DIR = os.path.dirname(os.path.realpath(__file__))
ASKPASS = os.path.join(DIR, "lib", "zenity-askpass.sh")

NEEDS_TERMINAL = {"00-locale-keyboard-timezone.sh"}

STATUS_STYLE = {
    "pending": ("pending", "#8a8a8a"),
    "running": ("running...", "#2b78e4"),
    "done": ("done", "#2a9d3f"),
    "failed": ("failed", "#d43f3f"),
}


def list_scripts():
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(DIR, "[0-9][0-9]-*.sh")))


def log_path_for(script):
    return os.path.join(DIR, script[:-3] + ".log")


def script_is_done(script):
    log = log_path_for(script)
    script_path = os.path.join(DIR, script)
    return os.path.exists(log) and os.path.getmtime(log) > os.path.getmtime(script_path)


class ScriptRow(Gtk.ListBoxRow):
    def __init__(self, script):
        super().__init__()
        self.script = script

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_border_width(4)
        self.add(box)

        name_label = Gtk.Label(label=script, xalign=0)
        name_label.set_ellipsize(Pango.EllipsizeMode.END)
        box.pack_start(name_label, True, True, 0)

        self.status_label = Gtk.Label(label="", xalign=1)
        box.pack_start(self.status_label, False, False, 0)

        self.set_status("done" if script_is_done(script) else "pending")

    def set_status(self, state):
        text, color = STATUS_STYLE[state]
        self.status_label.set_markup(f'<span foreground="{color}">{GLib.markup_escape_text(text)}</span>')


class RunGuiWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Cyberbeest Provisioning Runner")
        self.set_default_size(920, 560)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("destroy", self.on_destroy)

        self.proc = None
        self.busy = False
        self.stop_requested = False
        self.rows = {}

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        root.set_border_width(12)
        self.add(root)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        root.pack_start(button_box, False, False, 0)

        self.run_changed_button = Gtk.Button(label="Run changed only")
        self.run_changed_button.connect("clicked", lambda _b: self.start_sequence(changed_only=True))
        button_box.pack_start(self.run_changed_button, False, False, 0)

        self.run_all_button = Gtk.Button(label="Run all")
        self.run_all_button.connect("clicked", lambda _b: self.start_sequence(changed_only=False))
        button_box.pack_start(self.run_all_button, False, False, 0)

        self.stop_button = Gtk.Button(label="Stop after current script")
        self.stop_button.set_sensitive(False)
        self.stop_button.connect("clicked", self.on_stop)
        button_box.pack_start(self.stop_button, False, False, 0)

        self.status_label = Gtk.Label(label="Idle. Double-click a script below to run just that one.", xalign=0)
        root.pack_start(self.status_label, False, False, 0)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(300)
        root.pack_start(paned, True, True, 0)

        sidebar_scroller = Gtk.ScrolledWindow()
        sidebar_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar_scroller.set_size_request(280, -1)
        paned.pack1(sidebar_scroller, False, False)

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-activated", self.on_row_activated)
        sidebar_scroller.add(self.listbox)

        for script in list_scripts():
            row = ScriptRow(script)
            self.rows[script] = row
            self.listbox.add(row)

        log_scroller = Gtk.ScrolledWindow()
        log_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        paned.pack2(log_scroller, True, False)

        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_cursor_visible(False)
        self.log_view.set_monospace(True)
        self.log_buffer = self.log_view.get_buffer()
        log_scroller.add(self.log_view)

        self.show_all()

        if shutil.which("zenity") is None:
            self._ensure_zenity()

    def _ensure_zenity(self):
        # On a brand new machine that hasn't run any NN-*.sh script yet,
        # zenity may not be installed (it's only pulled in as a side effect
        # of 04-software-launch-warning.sh) -- install it ourselves here
        # rather than making that a manual prerequisite, since it's tiny
        # (~35-40MB all in, mostly its GTK4/libadwaita deps that a GTK3-based
        # XFCE image wouldn't otherwise have). Plain `sudo` (not -A), since
        # zenity itself -- needed for the graphical askpass -- doesn't exist
        # yet: this needs a real terminal to prompt on, same assumption the
        # rest of this dev-only tool already makes about how it's launched.
        self.append_log("zenity not found -- installing it (enter your sudo password in this terminal if asked)...\n")
        self.status_label.set_text("Installing zenity...")
        self._set_controls_busy(True)
        threading.Thread(target=self._install_zenity_worker, daemon=True).start()

    def _install_zenity_worker(self):
        proc = subprocess.Popen(
            ["sudo", "apt-get", "-o", "DPkg::Lock::Timeout=60", "install", "-y", "zenity"],
            stdin=None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        for line in proc.stdout:
            GLib.idle_add(self.append_log, line)
        status = proc.wait()
        GLib.idle_add(self._on_zenity_installed, status)

    def _on_zenity_installed(self, status):
        self._set_controls_busy(False)
        if status == 0 and shutil.which("zenity"):
            self.append_log("=== zenity installed ===\n")
            self.status_label.set_text("Idle. Double-click a script below to run just that one.")
        else:
            self.append_log(
                f"=== failed to install zenity (exit {status}) -- install it manually "
                "(sudo apt-get install zenity) and restart this tool ===\n"
            )
            self.status_label.set_text("zenity install failed -- see log above.")
            self.run_changed_button.set_sensitive(False)
            self.run_all_button.set_sensitive(False)
            self.listbox.set_sensitive(False)

    # -- log helpers --------------------------------------------------

    def append_log(self, text):
        end = self.log_buffer.get_end_iter()
        self.log_buffer.insert(end, text)
        mark = self.log_buffer.create_mark(None, self.log_buffer.get_end_iter(), False)
        self.log_view.scroll_to_mark(mark, 0.0, False, 0.0, 1.0)

    def set_row_status(self, script, state):
        self.rows[script].set_status(state)

    # -- starting runs --------------------------------------------------

    def _set_controls_busy(self, busy):
        self.busy = busy
        self.run_changed_button.set_sensitive(not busy)
        self.run_all_button.set_sensitive(not busy)
        self.stop_button.set_sensitive(busy)
        self.listbox.set_sensitive(not busy)

    def start_sequence(self, changed_only):
        if self.busy:
            return
        scripts = list_scripts()
        if changed_only:
            scripts = [s for s in scripts if not script_is_done(s)]
            if not scripts:
                self.status_label.set_text("Nothing to run -- everything is already up to date.")
                return
        self._start_run(scripts, label="Run changed only" if changed_only else "Run all")

    def on_row_activated(self, _listbox, row):
        if self.busy:
            return
        self._start_run([row.script], label=f"Run {row.script}")

    def _start_run(self, scripts, label):
        self.stop_requested = False
        self.log_buffer.set_text("")
        self.status_label.set_text(f"{label}: starting (enter sudo password if prompted)...")
        self._set_controls_busy(True)
        threading.Thread(target=self._worker, args=(scripts,), daemon=True).start()

    # -- running a single script --------------------------------------------------

    def _sudo_env(self):
        env = dict(os.environ)
        env["SUDO_ASKPASS"] = ASKPASS
        return env

    def _run_piped(self, script):
        proc = subprocess.Popen(
            ["sudo", "-A", "-p", "", "bash", script],
            cwd=DIR,
            env=self._sudo_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        self.proc = proc
        for line in proc.stdout:
            GLib.idle_add(self.append_log, line)
        status = proc.wait()
        self.proc = None
        return status

    def _run_in_terminal(self, script):
        GLib.idle_add(
            self.append_log,
            f"=== opening {script} in a terminal window (needs an interactive TTY) -- "
            "complete it there ===\n",
        )
        # xterm doesn't reliably propagate the wrapped command's exit status as
        # its own (it exits 0 on normal termination regardless of how the
        # command inside fared), so its own proc.returncode can't be trusted --
        # capture the real exit code to a file from inside the shell instead.
        fd, exit_file = tempfile.mkstemp(prefix="run-gui-exit-")
        os.close(fd)
        env = self._sudo_env()
        env["EXITFILE"] = exit_file
        try:
            proc = subprocess.Popen(
                [
                    "xterm", "-T", script, "-e", "bash", "-c",
                    'status=0; "$@" || status=$?; echo "$status" > "$EXITFILE"',
                    "_", "sudo", "-A", "-p", "", "bash", script,
                ],
                cwd=DIR,
                env=env,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            self.proc = proc
            proc.wait()
            self.proc = None
            try:
                return int(open(exit_file).read().strip())
            except (OSError, ValueError):
                return 1
        finally:
            try:
                os.remove(exit_file)
            except OSError:
                pass

    # -- worker thread --------------------------------------------------

    def _worker(self, scripts):
        stopped = False
        failed_script = None
        remaining = list(scripts)

        while remaining:
            if self.stop_requested:
                stopped = True
                GLib.idle_add(self.append_log, f"=== stop requested: skipping {len(remaining)} remaining script(s) ===\n")
                break

            script = remaining.pop(0)
            GLib.idle_add(self.set_row_status, script, "running")
            GLib.idle_add(self.status_label.set_text, f"Running: {script}")

            if script in NEEDS_TERMINAL:
                status = self._run_in_terminal(script)
            else:
                GLib.idle_add(self.append_log, f"=== running {script} ===\n")
                status = self._run_piped(script)

            if status == 0:
                GLib.idle_add(self.append_log, f"=== {script} done ===\n")
                GLib.idle_add(self.set_row_status, script, "done")
            else:
                failed_script = script
                GLib.idle_add(self.append_log, f"=== {script} FAILED (exit {status}) ===\n")
                GLib.idle_add(self.set_row_status, script, "failed")
                if remaining:
                    GLib.idle_add(
                        self.append_log,
                        "Stopping here since later scripts may depend on this one.\n",
                    )
                break

        GLib.idle_add(self._on_finished, stopped, failed_script)

    def _on_finished(self, stopped, failed_script):
        self._set_controls_busy(False)
        if stopped:
            self.status_label.set_text("Stopped after current script.")
        elif failed_script:
            self.status_label.set_text(f"Failed: {failed_script} -- see log above.")
        else:
            self.status_label.set_text("Finished successfully.")

    def on_stop(self, _button):
        if not self.busy:
            return
        self.stop_requested = True
        self.stop_button.set_sensitive(False)
        self.status_label.set_text("Stop requested -- finishing current script, then stopping...")

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
