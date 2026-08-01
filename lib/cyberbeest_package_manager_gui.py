#!/usr/bin/env python3
"""Cyberbeest Package Manager.

Left: a checklist of common applications, grouped by category, with a
"Show installed only" filter for quick uninstalls. Right: the queue of
changes that checking/unchecking boxes has built up so far, plus a
running history of everything ever applied. Nothing touches disk until
you press Go, which applies the whole queue in one shot.

Privileged work (apt install/remove, adding vendor apt repos) is done by
cyberbeest-pkg-helper.sh, run via pkexec so the user gets a normal
graphical authentication prompt. The whole queue is sent to a single
`pkexec ... batch` invocation so pressing Go asks for the password at
most once per press, rather than once per queued change. See
22-i2p-package-manager.sh for the (root, at provisioning time) setup that
registers the polkit policy for that helper.
"""

import os
import subprocess
import threading
from datetime import datetime

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

TERMINAL_CSS = b"""
.cyberbeest-terminal {
    background-color: #000000;
    padding: 6px;
}
"""


def _load_terminal_css():
    provider = Gtk.CssProvider()
    provider.load_from_data(TERMINAL_CSS)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )

# Root-owned path, matching com.cyberbeest.package-manager.policy's
# exec.path -- pkexec only trusts that this exact path is what it claims to
# be if it's not writable by the invoking (non-root) user.
HELPER = "/usr/local/lib/cyberbeest/cyberbeest-pkg-helper.sh"
LOG_PATH = "__LOG_PATH__"
LOG_DISPLAY_LIMIT = 100

APPS = [
    {
        "id": "i2p",
        "name": "I2P + qBittorrent",
        "description": "Anonymous eepsite browsing (i2pd, dedicated Alpenglow-themed Firefox profile) and I2P torrenting (qBittorrent, SAM bridge)",
        "category": "Privacy & Anonymity",
        "check_pkg": "i2pd",
        "install_pkg": "i2pd qbittorrent",
        "remove_pkg": "i2pd qbittorrent",
        "repo": None,
        "extra_install_steps": ["setup-i2pd-toggle"],
        "extra_remove_steps": ["teardown-i2pd-toggle"],
        "post_install_script": "__POST_INSTALL_SCRIPT__",
        "post_remove_script": "__POST_INSTALL_SCRIPT__",
    },
]

LIST_HEIGHT = 100
LOG_HEIGHT = 60


def append_log(entries):
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        for line in entries:
            f.write(line + "\n")


def read_recent_log(limit=LOG_DISPLAY_LIMIT):
    if not os.path.exists(LOG_PATH):
        return []
    with open(LOG_PATH, encoding="utf-8") as f:
        lines = [line.rstrip("\n") for line in f if line.strip()]
    return lines[-limit:]


def is_installed(pkg):
    result = subprocess.run(
        ["dpkg-query", "-W", "-f", "${Status}", pkg],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and "install ok installed" in result.stdout


def run_helper_batch(steps):
    """Run a queue of setup-repo/install/remove steps as ONE pkexec call.

    steps: list of strings like "install signal-desktop" or
    "setup-repo signal", applied in order under a single authentication.
    Returns (success, message).
    """
    try:
        proc = subprocess.run(
            ["pkexec", HELPER, "batch"],
            input="\n".join(steps) + "\n",
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as e:
        return False, f"Could not start pkexec: {e}"

    if proc.returncode == 0:
        return True, "All changes applied"
    if proc.returncode in (126, 127):
        return False, "Authentication was cancelled. No changes were made"
    detail = (proc.stderr or proc.stdout or "").strip()
    if detail:
        return False, f"{detail} (see cyberbeest_pkg_helper.log for details)"
    return False, f"Failed (exit code {proc.returncode})"


class AppRow(Gtk.Box):
    def __init__(self, app, on_changed):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.app = app
        self.on_changed = on_changed
        self.installed = is_installed(app["check_pkg"])

        self.check = Gtk.CheckButton()
        self.check.set_active(self.installed)
        self.check.set_valign(Gtk.Align.START)
        self.check.connect("toggled", self._on_toggled)
        self.pack_start(self.check, False, False, 0)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.pack_start(text_box, True, True, 0)

        name_label = Gtk.Label(xalign=0)
        name_label.set_markup(f"<b>{GLib.markup_escape_text(app['name'])}</b>")
        text_box.pack_start(name_label, False, False, 0)

        desc_label = Gtk.Label(label=app["description"], xalign=0, wrap=True)
        desc_label.get_style_context().add_class("dim-label")
        text_box.pack_start(desc_label, False, False, 0)

        self.state_label = Gtk.Label(xalign=0)
        self.state_label.set_no_show_all(True)
        self.state_label.hide()
        text_box.pack_start(self.state_label, False, False, 0)

        self.spinner = Gtk.Spinner()
        self.spinner.set_valign(Gtk.Align.START)
        self.spinner.set_no_show_all(True)
        self.spinner.hide()
        self.pack_start(self.spinner, False, False, 0)

    def _on_toggled(self, _check):
        self.on_changed()

    def pending_action(self):
        """None, 'install', or 'remove' -- the queued change, if any."""
        wants = self.check.get_active()
        if wants == self.installed:
            return None
        return "install" if wants else "remove"

    def set_checked_silently(self, active):
        self.check.handler_block_by_func(self._on_toggled)
        self.check.set_active(active)
        self.check.handler_unblock_by_func(self._on_toggled)

    def set_busy(self, busy):
        self.check.set_sensitive(not busy)
        if busy:
            action = self.pending_action()
            text = {"install": "INSTALLING", "remove": "REMOVING"}.get(action, "")
            self.state_label.set_markup(f"<b>{text}</b>")
            self.state_label.show()
            self.spinner.start()
            self.spinner.show()
        else:
            self.state_label.hide()
            self.spinner.stop()
            self.spinner.hide()

    def sync_to_actual(self):
        """After a batch runs, re-check real dpkg state and settle the row."""
        self.installed = is_installed(self.app["check_pkg"])
        self.set_checked_silently(self.installed)


class TaskRow(Gtk.Box):
    def __init__(self, app_row, on_cancel):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.app_row = app_row

        verb = "Install" if app_row.pending_action() == "install" else "Remove"
        label = Gtk.Label(xalign=0)
        label.set_markup(f"{verb} <b>{GLib.markup_escape_text(app_row.app['name'])}</b>")
        self.pack_start(label, True, True, 0)

        self.spinner = Gtk.Spinner()
        self.spinner.set_no_show_all(True)
        self.pack_start(self.spinner, False, False, 0)

        self.cancel_button = Gtk.Button()
        self.cancel_button.set_relief(Gtk.ReliefStyle.NONE)
        self.cancel_button.add(
            Gtk.Image.new_from_icon_name("window-close-symbolic", Gtk.IconSize.MENU)
        )
        self.cancel_button.set_tooltip_text("Remove from queue")
        self.cancel_button.connect("clicked", lambda _b: on_cancel(app_row))
        self.pack_start(self.cancel_button, False, False, 0)

    def set_running(self, running):
        if running:
            self.cancel_button.hide()
            self.spinner.show()
            self.spinner.start()
        else:
            self.spinner.stop()
            self.spinner.hide()
            self.cancel_button.show()


class PackagesPage(Gtk.Box):
    def __init__(self, parent_window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.parent_window = parent_window
        self.set_border_width(16)
        self.task_rows = {}

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_wide_handle(True)
        self.pack_start(paned, True, True, 0)

        apps_pane = self._build_apps_pane()
        apps_pane.set_margin_end(10)
        paned.pack1(apps_pane, True, False)

        tasks_pane = self._build_tasks_pane()
        tasks_pane.set_margin_start(10)
        paned.pack2(tasks_pane, True, False)

        self.rebuild_tasks()

    def _build_apps_pane(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        heading = Gtk.Label(xalign=0)
        heading.set_markup('<span size="large"><b>Applications</b></span>')
        box.pack_start(heading, False, False, 0)

        info = Gtk.Label(
            wrap=True,
            xalign=0,
            label="Check a box to install. Uncheck to uninstall",
        )
        info.get_style_context().add_class("dim-label")
        box.pack_start(info, False, False, 0)

        filter_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.pack_start(filter_box, False, False, 0)

        filter_box.pack_start(Gtk.Box(), True, True, 0)
        filter_box.pack_start(Gtk.Label(label="Show installed only"), False, False, 0)

        self.installed_only_switch = Gtk.Switch()
        self.installed_only_switch.set_valign(Gtk.Align.CENTER)
        self.installed_only_switch.connect("notify::active", self.on_filter_changed)
        filter_box.pack_start(self.installed_only_switch, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_overlay_scrolling(False)
        scroller.set_size_request(-1, LIST_HEIGHT)
        box.pack_start(scroller, True, True, 0)

        list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        list_box.set_border_width(2)
        scroller.add(list_box)

        self.rows = {}
        self.categories = []
        current_category = None
        cat_rows = None
        for app in APPS:
            if app["category"] != current_category:
                current_category = app["category"]
                cat_label = Gtk.Label(xalign=0)
                cat_label.set_markup(f"<b>{GLib.markup_escape_text(current_category)}</b>")
                cat_label.get_style_context().add_class("dim-label")
                list_box.pack_start(cat_label, False, False, 0)
                cat_rows = []
                self.categories.append((cat_label, cat_rows))
            row = AppRow(app, self.on_row_changed)
            list_box.pack_start(row, False, False, 0)
            self.rows[app["id"]] = row
            cat_rows.append(row)

        return box

    def _build_tasks_pane(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        self.tasks_heading = Gtk.Label(xalign=0)
        box.pack_start(self.tasks_heading, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_overlay_scrolling(False)
        scroller.set_size_request(-1, LIST_HEIGHT)
        box.pack_start(scroller, True, True, 0)

        self.tasks_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.tasks_list.set_border_width(2)
        scroller.add(self.tasks_list)

        self.tasks_empty_label = Gtk.Label(xalign=0, label="Nothing queued yet")
        self.tasks_empty_label.get_style_context().add_class("dim-label")

        self.status_label = Gtk.Label(xalign=1, wrap=True)
        self.status_label.set_no_show_all(True)
        box.pack_start(self.status_label, False, False, 0)

        self.go_button = Gtk.Button(label="GO")
        self.go_button.get_style_context().add_class("suggested-action")
        self.go_button.connect("clicked", self.on_go_clicked)
        box.pack_start(self.go_button, False, False, 0)

        warning_label = Gtk.Label(
            wrap=True,
            xalign=0,
            label="You may be asked for your short password multiple times",
        )
        warning_label.get_style_context().add_class("dim-label")
        box.pack_start(warning_label, False, False, 0)

        log_section = self._build_log_section()
        log_section.set_margin_top(16)
        box.pack_start(log_section, False, False, 0)

        return box

    def _build_log_section(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        heading = Gtk.Label(xalign=0)
        heading.set_markup("<b>History</b>")
        box.pack_start(heading, False, False, 0)

        self.log_scroller = Gtk.ScrolledWindow()
        self.log_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.log_scroller.set_overlay_scrolling(False)
        self.log_scroller.set_size_request(-1, LOG_HEIGHT)
        box.pack_start(self.log_scroller, False, False, 0)

        self.log_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.log_list.set_border_width(2)
        self.log_list.get_style_context().add_class("cyberbeest-terminal")
        self.log_scroller.add(self.log_list)

        self.rebuild_log()
        return box

    def _pending_rows(self):
        return [row for row in self.rows.values() if row.pending_action()]

    def on_filter_changed(self, switch, _pspec):
        installed_only = switch.get_active()
        for cat_label, cat_rows in self.categories:
            any_visible = False
            for row in cat_rows:
                visible = row.installed or not installed_only
                row.set_visible(visible)
                any_visible = any_visible or visible
            cat_label.set_visible(any_visible)

    def on_row_changed(self):
        self.rebuild_tasks()

    def rebuild_tasks(self):
        for child in self.tasks_list.get_children():
            self.tasks_list.remove(child)

        pending = self._pending_rows()
        self.task_rows = {}
        if not pending:
            self.tasks_list.pack_start(self.tasks_empty_label, False, False, 0)
            self.tasks_empty_label.show()
        else:
            for row in pending:
                task_row = TaskRow(row, self.on_cancel_task)
                task_row.show_all()
                self.tasks_list.pack_start(task_row, False, False, 0)
                self.task_rows[row.app["id"]] = task_row

        count = len(pending)
        self.tasks_heading.set_markup(
            '<span size="large"><b>Tasks</b></span>' + (f" ({count})" if count else "")
        )
        self.go_button.set_sensitive(count > 0)

    def on_cancel_task(self, app_row):
        app_row.set_checked_silently(app_row.installed)
        self.rebuild_tasks()

    def rebuild_log(self):
        for child in self.log_list.get_children():
            self.log_list.remove(child)

        entries = read_recent_log() or ["No history yet"]
        for line in entries:
            label = Gtk.Label(xalign=0)
            label.set_markup(
                f'<span font_family="monospace" foreground="#33ff66">'
                f"{GLib.markup_escape_text(line)}</span>"
            )
            self.log_list.pack_start(label, False, False, 0)

        self.log_list.show_all()
        GLib.idle_add(self._scroll_log_to_bottom)

    def _scroll_log_to_bottom(self):
        adj = self.log_scroller.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())
        return False

    def set_status(self, text, is_error=False):
        self.status_label.set_markup(
            f'<span foreground="{"red" if is_error else "green"}">{GLib.markup_escape_text(text)}</span>'
        )
        self.status_label.set_no_show_all(False)
        self.status_label.show()

    def on_go_clicked(self, _button):
        pending = self._pending_rows()
        if not pending:
            return

        summary_lines = [
            f"{'Install' if row.pending_action() == 'install' else 'Remove'} {row.app['name']}"
            for row in pending
        ]
        if not self._confirm("Apply these changes?\n\n" + "\n".join(summary_lines)):
            return

        steps = []
        used_repos = set()
        for row in pending:
            if row.pending_action() == "install":
                repo = row.app["repo"]
                if repo and repo not in used_repos:
                    steps.append(f"setup-repo {repo}")
                    used_repos.add(repo)
                steps.append(f"install {row.app['install_pkg']}")
                steps.extend(row.app.get("extra_install_steps", []))
            else:
                steps.extend(row.app.get("extra_remove_steps", []))
                steps.append(f"remove {row.app['remove_pkg']}")

        self.go_button.set_sensitive(False)
        self.installed_only_switch.set_sensitive(False)
        for row in pending:
            row.set_busy(True)
            task_row = self.task_rows.get(row.app["id"])
            if task_row:
                task_row.set_running(True)

        threading.Thread(target=self._run_batch, args=(steps, pending), daemon=True).start()

    def _confirm(self, question):
        dialog = Gtk.MessageDialog(
            transient_for=self.parent_window,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=question,
        )
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.YES

    def _run_batch(self, steps, pending_rows):
        ok, message = run_helper_batch(steps)
        if ok:
            extras_error = self._run_post_action_scripts(pending_rows)
            if extras_error:
                ok, message = False, extras_error
        GLib.idle_add(self._on_batch_done, ok, message, pending_rows)

    def _run_post_action_scripts(self, pending_rows):
        """Run any unprivileged post_install/post_remove_script for rows
        just installed/removed.

        Runs as the regular user (no pkexec) since these only touch the
        user's own home directory. Returns an error message, or None.
        """
        for row in pending_rows:
            action = row.pending_action()
            if action == "install":
                script = row.app.get("post_install_script")
                args = ["python3", script] if script else None
                verb, gerund = "installed", "setup"
            elif action == "remove":
                script = row.app.get("post_remove_script")
                args = ["python3", script, "remove"] if script else None
                verb, gerund = "removed", "cleanup"
            else:
                continue
            if not args:
                continue
            proc = subprocess.run(args, capture_output=True, text=True, timeout=120)
            if proc.returncode != 0:
                detail = (proc.stderr or proc.stdout or "").strip()
                return f"{row.app['name']} {verb}, but {gerund} failed: {detail}"
        return None

    def _on_batch_done(self, ok, message, pending_rows):
        log_entries = []
        for row in pending_rows:
            pre_installed = row.installed
            desired = row.pending_action()
            row.set_busy(False)
            row.sync_to_actual()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if desired == "install" and not pre_installed and row.installed:
                log_entries.append(f"{timestamp}  Installed {row.app['name']}")
            elif desired == "remove" and pre_installed and not row.installed:
                log_entries.append(f"{timestamp}  Removed {row.app['name']}")

        if log_entries:
            append_log(log_entries)
            self.rebuild_log()

        self.installed_only_switch.set_sensitive(True)
        self.rebuild_tasks()
        self.set_status(message, is_error=not ok)
        return False


class PackagesWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Cyberbeest Package Manager")
        self.set_default_size(760, 380)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("destroy", Gtk.main_quit)
        self.add(PackagesPage(self))


def main():
    _load_terminal_css()
    win = PackagesWindow()
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
