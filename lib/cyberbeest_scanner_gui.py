#!/usr/bin/env python3
"""Cyberbeest Malware Scanner.

Runs four checks (debsums, clamscan, rkhunter, chkrootkit) via pkexec +
cyberbeest-scanner-helper.sh (installed by 59-cyberbeest-scanner.sh), shows
live progress and the raw tool output (same as watching it in a terminal),
then runs interpret_results.py's rule-based classifier over the finished
report -- no AI reads the log; see that module's docstring for why.

Runs against the live system this GUI is installed on -- not from separate
boot media. See the offline-scanner-stick-plan notes if that ever changes.
"""
import datetime
import os
import re
import subprocess
import sys
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango

sys.path.insert(0, os.path.expanduser("~/.local/lib/cyberbeest-scanner"))
import interpret_results  # noqa: E402

HELPER = "/usr/local/lib/cyberbeest/cyberbeest-scanner-helper.sh"
REPORTS_DIR = os.path.expanduser("~/.local/share/cyberbeest/scanner/reports")
REPORT_NAME_RE = re.compile(r"scan-(\d{8})-(\d{6})\.log$")
# Keyed by the short stage name the helper script sends as @@STAGE@@'s 4th
# field (not by index -- with phase checkboxes, index n now means "the nth
# stage actually run", which stage that is depends on what was selected).
PHASES = [
    ("debsums", "Checking base-system files (debsums)"),
    ("clamscan", "Scanning for known malware (ClamAV)"),
    ("rkhunter", "Checking for rootkits (rkhunter)"),
    ("chkrootkit", "Checking for rootkits (chkrootkit)"),
]
STAGE_NAMES = dict(PHASES)

LEVEL_COLORS = {"GREEN": "#2e7d32", "YELLOW": "#e6a700", "RED": "#c62828"}
PHASE_STATUS_STYLE = {
    "pending": ("Pending", "#8a8a8a"),
    "skipped": ("Skipped", "#8a8a8a"),
    "running": ("Running…", "#2b78e4"),
    "done": ("Done", "#2a9d3f"),
    "failed": ("Failed", "#c62828"),
}


def format_duration(seconds):
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def find_last_report():
    # The start time is in the filename (set once, before the scan runs);
    # the end time is the file's own mtime (last written to as the scan's
    # final stage completes) -- both already exist for every report ever
    # produced, including ones from earlier sessions, so no separate
    # "last scan" state needs to be persisted anywhere.
    try:
        candidates = [f for f in os.listdir(REPORTS_DIR) if REPORT_NAME_RE.search(f)]
    except OSError:
        return None
    if not candidates:
        return None
    candidates.sort()  # timestamp-named, sorts chronologically
    return os.path.join(REPORTS_DIR, candidates[-1])


def parse_report_start_time(path):
    m = REPORT_NAME_RE.search(os.path.basename(path))
    return datetime.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")


class PhaseRow(Gtk.ListBoxRow):
    """One checkbox + status label for a scan phase. Simpler than run-gui.py's
    ScriptRow -- no per-row run button, since the single Scan Now button runs
    whatever's checked."""

    def __init__(self, key, label):
        super().__init__()
        self.key = key
        self.set_selectable(False)
        self.set_activatable(False)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_border_width(4)
        self.add(box)

        self.check = Gtk.CheckButton(label=label)
        self.check.set_active(True)
        box.pack_start(self.check, True, True, 0)

        self.status_label = Gtk.Label(label="", xalign=1)
        box.pack_start(self.status_label, False, False, 0)

        self.set_status("pending")

    @property
    def selected(self):
        return self.check.get_active()

    def set_status(self, state):
        text, color = PHASE_STATUS_STYLE[state]
        self.status_label.set_markup(f'<span foreground="{color}">{GLib.markup_escape_text(text)}</span>')


class ScannerWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Cyberbeest Malware Scanner")
        self.set_default_size(760, 560)
        self.set_border_width(12)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(root)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        root.pack_start(top, False, False, 0)

        self.scan_button = Gtk.Button(label="Scan Now")
        self.scan_button.connect("clicked", self.on_scan_clicked)
        top.pack_start(self.scan_button, False, False, 0)

        self.progress = Gtk.ProgressBar()
        self.progress.set_show_text(True)
        self.progress.set_text("Idle")
        top.pack_start(self.progress, True, True, 0)

        self.timer_label = Gtk.Label(label="")
        top.pack_start(self.timer_label, False, False, 0)

        phases_label = Gtk.Label(label="Checks to run:")
        phases_label.set_xalign(0)
        root.pack_start(phases_label, False, False, 0)

        self.phase_listbox = Gtk.ListBox()
        self.phase_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.phase_rows = {}
        for key, label in PHASES:
            row = PhaseRow(key, label)
            row.check.connect("toggled", self.on_phase_toggled)
            self.phase_rows[key] = row
            self.phase_listbox.add(row)
        root.pack_start(self.phase_listbox, False, False, 0)

        self.verdict_label = Gtk.Label(label="")
        self.verdict_label.set_xalign(0)
        self.verdict_label.set_line_wrap(True)
        root.pack_start(self.verdict_label, False, False, 0)

        self.verdict_view = Gtk.TextView()
        self.verdict_view.set_editable(False)
        self.verdict_view.set_monospace(True)
        self.verdict_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.verdict_buffer = self.verdict_view.get_buffer()
        verdict_scroller = Gtk.ScrolledWindow()
        verdict_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        verdict_scroller.set_min_content_height(140)
        verdict_scroller.add(self.verdict_view)
        root.pack_start(verdict_scroller, False, False, 0)

        log_label = Gtk.Label(label="Raw tool output:")
        log_label.set_xalign(0)
        root.pack_start(log_label, False, False, 0)

        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_monospace(True)
        self.log_view.override_font(Pango.FontDescription("monospace 9"))
        self.log_buffer = self.log_view.get_buffer()
        log_scroller = Gtk.ScrolledWindow()
        log_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        log_scroller.add(self.log_view)
        root.pack_start(log_scroller, True, True, 0)

        self.connect("destroy", self.on_destroy)

        self.stage_index = 0
        self.stage_total = 1
        self.stage_label = ""
        self.current_stage_key = None
        self.clam_total = None
        self.scan_proc = None
        self.scan_start_time = None
        self.timer_source = None

        self._update_scan_button_sensitivity()
        self._show_last_scan_summary()

    def on_phase_toggled(self, _check):
        self._update_scan_button_sensitivity()

    def _update_scan_button_sensitivity(self):
        scanning = self.scan_proc is not None and self.scan_proc.poll() is None
        self.scan_button.set_sensitive(not scanning and any(row.selected for row in self.phase_rows.values()))

    def _show_last_scan_summary(self):
        path = find_last_report()
        if not path:
            self.verdict_label.set_markup("<i>No scan has been run yet.</i>")
            return
        start_dt = parse_report_start_time(path)
        duration = max(0, os.path.getmtime(path) - start_dt.timestamp())
        with open(path) as f:
            text = f.read()
        # do_debsums_diff=False: this is a passive peek at startup, not an
        # active scan -- skip the network-dependent pristine-package diff so
        # opening the window is instant, not gated on apt-get download.
        verdict = interpret_results.build_verdict(text, do_debsums_diff=False)
        color = LEVEL_COLORS.get(verdict["level"], "#000000")
        when = start_dt.strftime("%Y-%m-%d %H:%M")
        self.verdict_label.set_markup(
            f"<b>Last scan:</b> {GLib.markup_escape_text(when)}, took {format_duration(duration)} — "
            f"<span foreground='{color}'><b>{GLib.markup_escape_text(verdict['headline'])}</b></span>"
            f"  (full report: {GLib.markup_escape_text(path)})")
        self.verdict_buffer.set_text(interpret_results.render_text(verdict))
        # Strip the machine "===<key>===" section markers -- during a live
        # scan those only ever land in the report file, never on stdout (so
        # never in this log pane); replaying the raw file verbatim would
        # show internal plumbing a live scan never actually displays.
        visible_lines = [l for l in text.splitlines() if not re.match(r"^===\w+===$", l)]
        self.log_buffer.set_text("\n".join(visible_lines))

    def on_destroy(self, _widget):
        # pkexec forwards SIGTERM to what it launched (the helper script),
        # which has its own trap to stop clamd and save incremental-scan
        # progress before it actually exits -- see cyberbeest-scanner-
        # helper.sh. Without this, closing the window mid-scan orphaned the
        # whole thing: it kept running in the background, indefinitely,
        # with nothing left to show for it.
        if self.scan_proc and self.scan_proc.poll() is None:
            self.scan_proc.terminate()
        if self.timer_source is not None:
            GLib.source_remove(self.timer_source)
            self.timer_source = None
        Gtk.main_quit()

    def on_scan_clicked(self, _button):
        self.selected_phases = [key for key, _ in PHASES if self.phase_rows[key].selected]
        for key, row in self.phase_rows.items():
            row.set_status("pending" if key in self.selected_phases else "skipped")
        self.phase_listbox.set_sensitive(False)
        self.scan_button.set_sensitive(False)
        self.log_buffer.set_text("")
        self.verdict_buffer.set_text("")
        self.verdict_label.set_markup("<b>Scanning...</b>")
        self.progress.set_fraction(0.0)
        self.progress.set_text("Starting...")
        self.clam_total = None
        self.current_stage_key = None
        self.scan_start_time = time.monotonic()
        self.timer_label.set_text("0:00")
        self.timer_source = GLib.timeout_add(1000, self._tick_timer)
        threading.Thread(target=self._run_scan, daemon=True).start()

    def _tick_timer(self):
        self.timer_label.set_text(format_duration(time.monotonic() - self.scan_start_time))
        return True

    def _stop_timer(self):
        if self.timer_source is not None:
            GLib.source_remove(self.timer_source)
            self.timer_source = None
        if self.scan_start_time is not None:
            self.timer_label.set_text(f"took {format_duration(time.monotonic() - self.scan_start_time)}")

    def _append_log(self, text):
        end = self.log_buffer.get_end_iter()
        self.log_buffer.insert(end, text + "\n")
        GLib.idle_add(self._scroll_log_to_bottom)
        return False

    def _scroll_log_to_bottom(self):
        mark = self.log_buffer.get_insert()
        self.log_view.scroll_mark_onscreen(mark)
        return False

    def _set_progress(self, index, total, name):
        if self.current_stage_key in self.phase_rows:
            self.phase_rows[self.current_stage_key].set_status("done")
        self.current_stage_key = name
        if name in self.phase_rows:
            self.phase_rows[name].set_status("running")

        self.stage_index = index
        self.stage_total = total
        self.stage_label = STAGE_NAMES.get(name, name)
        self.clam_total = None
        self.progress.set_fraction((index - 1) / total)
        self.progress.set_text(f"{index}/{total}: {self.stage_label}")
        return False

    def _set_clam_total(self, total):
        self.clam_total = total
        return False

    def _set_clam_progress(self, done):
        if not self.clam_total:
            return False
        frac_within = min(done / self.clam_total, 1.0)
        self.progress.set_fraction((self.stage_index - 1 + frac_within) / self.stage_total)
        self.progress.set_text(
            f"{self.stage_index}/{self.stage_total}: {self.stage_label} — {done}/{self.clam_total} files")
        return False

    def _run_scan(self):
        try:
            proc = subprocess.Popen(
                ["pkexec", HELPER, ",".join(self.selected_phases)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        except Exception as e:
            GLib.idle_add(self._on_scan_failed, f"Could not start pkexec: {e}")
            return
        self.scan_proc = proc

        report_path = None
        interrupted = False
        for line in proc.stdout:
            line = line.rstrip("\n")
            if line.startswith("@@STAGE@@ "):
                _, idx, total, name = line.split(" ", 3)
                GLib.idle_add(self._set_progress, int(idx), int(total), name)
            elif line.startswith("@@CLAMTOTAL@@ "):
                GLib.idle_add(self._set_clam_total, int(line.split(" ", 1)[1]))
            elif line.startswith("@@CLAMPROGRESS@@ "):
                GLib.idle_add(self._set_clam_progress, int(line.split(" ", 1)[1]))
            elif line.startswith("@@DONE@@ "):
                report_path = line[len("@@DONE@@ "):].strip()
            elif line.startswith("@@INTERRUPTED@@"):
                interrupted = True
            else:
                GLib.idle_add(self._append_log, line)
        proc.wait()

        if interrupted:
            GLib.idle_add(self._on_scan_failed, "Scan interrupted (nothing left running in the background)")
            return
        if proc.returncode != 0 or not report_path:
            GLib.idle_add(self._on_scan_failed, f"Scan did not complete (exit code {proc.returncode})")
            return

        GLib.idle_add(self._on_scan_done, report_path)

    def _on_scan_failed(self, message):
        self._stop_timer()
        if self.current_stage_key in self.phase_rows:
            self.phase_rows[self.current_stage_key].set_status("failed")
        self.current_stage_key = None
        self.progress.set_fraction(0.0)
        self.progress.set_text("Failed")
        self.verdict_label.set_markup(f"<b><span foreground='#c62828'>{GLib.markup_escape_text(message)}</span></b>")
        self.phase_listbox.set_sensitive(True)
        self._update_scan_button_sensitivity()
        return False

    def _on_scan_done(self, report_path):
        self._stop_timer()
        if self.current_stage_key in self.phase_rows:
            self.phase_rows[self.current_stage_key].set_status("done")
        self.current_stage_key = None
        self.progress.set_fraction(1.0)
        self.progress.set_text("Done")
        with open(report_path) as f:
            text = f.read()
        verdict = interpret_results.build_verdict(text)
        color = LEVEL_COLORS.get(verdict["level"], "#000000")
        self.verdict_label.set_markup(
            f"<b><span foreground='{color}'>{GLib.markup_escape_text(verdict['headline'])}</span></b>"
            f"  (full report: {GLib.markup_escape_text(report_path)})")
        self.verdict_buffer.set_text(interpret_results.render_text(verdict))
        self.phase_listbox.set_sensitive(True)
        self._update_scan_button_sensitivity()
        return False


if __name__ == "__main__":
    win = ScannerWindow()
    win.show_all()
    Gtk.main()
