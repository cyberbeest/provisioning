#!/usr/bin/env python3
"""GUI front-end for the cyberbeest QA flows (flow-*.sh in this directory).

Deliberately a separate, smaller tool rather than sharing code with
provisioning/run-gui.py: that tool's complexity (sudo askpass caching, the
whiptail/xterm NEEDS_TERMINAL workaround, mtime-vs-lib-deps "done" freshness
heuristic) is all provisioning-specific and doesn't apply here. QA flows run
as the current user, need no elevation, and "done" simply means "did the
last run's log end in PASS or FAIL" -- there's no dependency-freshness
question. The two tools share a UX shape (sidebar + log pane + run
all/selected/single) by eye, not by import.

Each flow script already does its own OCR-based assertions and writes
logs/<flow>.log; this GUI just discovers flow-*.sh, runs them as subprocesses,
streams their combined stdout/stderr into a log pane, and colors each
sidebar row by pass/fail. Only one flow runs at a time, since they all drive
the real mouse/keyboard -- a second flow starting mid-run would fight the
first for control of the desktop.

Auto-lock/screen-lock flows are out of scope on purpose (they need a manual
unlock) and simply won't have a flow-*.sh written for them.
"""
import glob
import os
import subprocess
import threading

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango

DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(DIR, "logs")

STATUS_COLORS = {
    "idle": "#888888",
    "running": "#2b7fd6",
    "pass": "#2e9e44",
    "fail": "#c0392b",
}
STATUS_LABELS = {
    "idle": "not run",
    "running": "running…",
    "pass": "PASS",
    "fail": "FAIL",
}


def discover_flows():
    paths = sorted(glob.glob(os.path.join(DIR, "flow-*.sh")))
    return [os.path.basename(p)[len("flow-"):-len(".sh")] for p in paths]


def flow_script_path(flow):
    return os.path.join(DIR, f"flow-{flow}.sh")


def last_known_status(flow):
    log_path = os.path.join(LOGS_DIR, f"flow-{flow}.log")
    if not os.path.exists(log_path):
        return "idle"
    try:
        with open(log_path, "r", errors="replace") as f:
            tail = f.readlines()[-5:]
    except OSError:
        return "idle"
    text = "".join(tail)
    if "ALL PASSED" in text:
        return "pass"
    if "FAILED" in text:
        return "fail"
    return "idle"


class FlowRow(Gtk.ListBoxRow):
    def __init__(self, flow):
        super().__init__()
        self.flow = flow
        self.status = last_known_status(flow)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_border_width(6)
        self.name_label = Gtk.Label(label=flow, xalign=0)
        self.name_label.set_hexpand(True)
        self.status_label = Gtk.Label(label=STATUS_LABELS[self.status])
        box.pack_start(self.name_label, True, True, 0)
        box.pack_start(self.status_label, False, False, 0)
        self.add(box)
        self._apply_color()

    def set_status(self, status):
        self.status = status
        self.status_label.set_text(STATUS_LABELS[status])
        self._apply_color()

    def _apply_color(self):
        color = STATUS_COLORS[self.status]
        self.status_label.set_markup(
            f'<span foreground="{color}">{GLib.markup_escape_text(STATUS_LABELS[self.status])}</span>'
        )


class QaRunnerWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Cyberbeest QA Flows")
        self.set_default_size(900, 600)
        self.connect("destroy", Gtk.main_quit)

        self.logs = {}  # flow -> accumulated text
        self.rows = {}  # flow -> FlowRow
        self.running = False
        self.stop_requested = False
        self.proc = None
        self.displayed_flow = None
        self.follow_live = None

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(root)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        toolbar.set_border_width(6)
        self.run_all_btn = Gtk.Button(label="Run all")
        self.run_all_btn.connect("clicked", lambda _b: self.start_run(discover_flows()))
        self.run_selected_btn = Gtk.Button(label="Run selected")
        self.run_selected_btn.connect("clicked", self._on_run_selected)
        self.stop_btn = Gtk.Button(label="Stop after current")
        self.stop_btn.connect("clicked", self._on_stop)
        self.stop_btn.set_sensitive(False)
        toolbar.pack_start(self.run_all_btn, False, False, 0)
        toolbar.pack_start(self.run_selected_btn, False, False, 0)
        toolbar.pack_start(self.stop_btn, False, False, 0)
        self.status_label = Gtk.Label(label="")
        toolbar.pack_end(self.status_label, False, False, 0)
        root.pack_start(toolbar, False, False, 0)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        root.pack_start(paned, True, True, 0)

        sidebar_scroll = Gtk.ScrolledWindow()
        sidebar_scroll.set_size_request(260, -1)
        self.listbox = Gtk.ListBox()
        self.listbox.set_activate_on_single_click(False)
        self.listbox.connect("row-activated", self._on_row_activated)
        self.listbox.connect("selected-rows-changed", self._on_selection_changed)
        self.listbox.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
        for flow in discover_flows():
            row = FlowRow(flow)
            self.rows[flow] = row
            self.logs[flow] = ""
            self.listbox.add(row)
        sidebar_scroll.add(self.listbox)
        paned.pack1(sidebar_scroll, False, False)

        log_scroll = Gtk.ScrolledWindow()
        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_monospace(True)
        self.log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.log_buffer = self.log_view.get_buffer()
        log_scroll.add(self.log_view)
        paned.pack2(log_scroll, True, False)

        self.show_all()
        self._update_selected_sensitivity()

    # -- running flows --------------------------------------------------

    def _on_run_selected(self, _btn):
        flows = [row.flow for row in self.listbox.get_selected_rows()]
        if flows:
            self.start_run(flows)

    def _on_row_activated(self, _listbox, row):
        self.start_run([row.flow])

    def _on_stop(self, _btn):
        self.stop_requested = True
        self.stop_btn.set_sensitive(False)

    def _on_selection_changed(self, _listbox):
        selected = self.listbox.get_selected_rows()
        self._update_selected_sensitivity()
        if len(selected) == 1 and not self.running:
            self._show_log(selected[0].flow)

    def _update_selected_sensitivity(self):
        self.run_selected_btn.set_sensitive(bool(self.listbox.get_selected_rows()) and not self.running)

    def start_run(self, flows):
        if self.running or not flows:
            return
        self.running = True
        self.stop_requested = False
        self.run_all_btn.set_sensitive(False)
        self.run_selected_btn.set_sensitive(False)
        self.stop_btn.set_sensitive(True)
        threading.Thread(target=self._worker, args=(flows,), daemon=True).start()

    def _worker(self, flows):
        for flow in flows:
            if self.stop_requested:
                GLib.idle_add(self.append_log, "", f"Stopped before running: {', '.join(flows[flows.index(flow):])}\n")
                break
            GLib.idle_add(self._begin_flow_display, flow)
            GLib.idle_add(self.rows[flow].set_status, "running")
            GLib.idle_add(self.status_label.set_text, f"Running: {flow}")

            proc = subprocess.Popen(
                ["bash", flow_script_path(flow)],
                cwd=DIR,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
            self.proc = proc
            for line in proc.stdout:
                GLib.idle_add(self.append_log, flow, line)
            status = proc.wait()
            self.proc = None

            GLib.idle_add(self.rows[flow].set_status, "pass" if status == 0 else "fail")

        GLib.idle_add(self._on_finished)

    def _on_finished(self):
        self.running = False
        self.stop_requested = False
        self.run_all_btn.set_sensitive(True)
        self.stop_btn.set_sensitive(False)
        self._update_selected_sensitivity()
        self.status_label.set_text("Idle")

    # -- log display ------------------------------------------------------

    def _begin_flow_display(self, flow):
        self.logs[flow] = ""
        self.follow_live = flow
        self._show_log(flow)

    def append_log(self, flow, text):
        self.logs[flow] = self.logs.get(flow, "") + text
        if self.displayed_flow == flow or (flow == "" and self.displayed_flow is None):
            self.log_buffer.insert(self.log_buffer.get_end_iter(), text)
            self._scroll_to_end()

    def _show_log(self, flow):
        self.displayed_flow = flow
        self.log_buffer.set_text(self.logs.get(flow, ""))
        self._scroll_to_end()

    def _scroll_to_end(self):
        mark = self.log_buffer.get_insert()
        self.log_buffer.place_cursor(self.log_buffer.get_end_iter())
        self.log_view.scroll_mark_onscreen(mark)


def main():
    win = QaRunnerWindow()
    Gtk.main()


if __name__ == "__main__":
    main()
