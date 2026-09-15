#!/usr/bin/env python3
"""Confirm dialog for cyberbeest-update.sh -- not zenity, because zenity's
--question dialog always adds its own Yes/No first internally and stacks
any --extra-button above them (verified against zenity 4.1.90's source and
a live render), with no CLI way to reorder that. That put "Switch to X
instead" -- a rare, destructive action -- visually ahead of the everyday
Yes/No choice. A small dedicated GTK3 dialog (matching cyberbeest-askpass.py
and the rest of Cyberbeest's own dialogs) instead packs it as a secondary
button-box widget, which GTK renders on the opposite side from Yes/No --
there on request, but not competing for attention.

Reads the list of files the pull would change from stdin, as
`git diff --name-status` lines (possibly empty, if the checkout is
already up to date).

Prints exactly one of "yes", "no" or "switch" to stdout and exits 0.
"""
import datetime
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from i18n import t

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Pango

RESPONSE_SWITCH = 100

_STATUS_LABELS = {
    "A": "update.status_added",
    "M": "update.status_modified",
    "D": "update.status_deleted",
    "R": "update.status_renamed",
    "C": "update.status_copied",
}


def parse_changed_files(raw):
    """Turns cyberbeest-update.sh's enriched `git diff --name-status` lines
    into (status, display_path, date, lookup_paths) rows.

    Rename/copy lines carry a similarity percentage after the letter
    (e.g. "R100") and two paths (old, new); every other status is a
    single letter and one path. cyberbeest-update.sh appends the date of
    the newest incoming commit touching that path as a trailing field.
    lookup_paths is what a per-file `git diff -- <paths>` needs: both
    paths for a rename/copy (the old one only exists in HEAD's tree, the
    new one only in the incoming tree), one path otherwise.
    """
    rows = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        date = fields[-1]
        fields = fields[:-1]
        code = fields[0][0]
        label = t(_STATUS_LABELS.get(code, "update.status_other")).format(code=fields[0])
        if code in ("R", "C") and len(fields) >= 3:
            path = f"{fields[1]} → {fields[2]}"
            lookup_paths = [fields[1], fields[2]]
        else:
            path = fields[-1]
            lookup_paths = [fields[-1]]
        rows.append((label, path, date, lookup_paths))
    return rows


_RELATIVE_UNITS = (
    ("year", 31536000), ("month", 2592000), ("day", 86400),
    ("hour", 3600), ("minute", 60),
)


def relative_time(when):
    seconds = (datetime.datetime.now() - when).total_seconds()
    for unit, unit_seconds in _RELATIVE_UNITS:
        n = int(seconds // unit_seconds)
        if n >= 1:
            key = f"relative.{unit}_ago" if n == 1 else f"relative.{unit}s_ago"
            return t(key).format(n=n)
    return t("relative.just_now")


def last_pull_text(repo_dir):
    # git touches .git/FETCH_HEAD on every fetch (including the fetch this
    # tool's own "Yes" does), so its mtime is a reliable "last pull" marker
    # without needing a separate state file.
    fetch_head = os.path.join(repo_dir, ".git", "FETCH_HEAD")
    try:
        when = datetime.datetime.fromtimestamp(os.path.getmtime(fetch_head))
    except OSError:
        return t("update.last_pull_never")
    return t("update.last_pull_message").format(
        when=when.strftime("%Y-%m-%d %H:%M"), relative=relative_time(when)
    )


def build_diff_rows(diff_text):
    """Turns a unified diff into (left, right, left_kind, right_kind) rows
    for side-by-side display.

    Consecutive removed/added lines within a hunk are paired up in order
    (line N removed with line N added) -- a naive alignment, not a real
    word-level diff, but it's what most side-by-side diff views do and it's
    enough to see what changed without reading +/- prefixes.
    """
    rows = []
    pending_removed = []
    pending_added = []

    def flush():
        n = max(len(pending_removed), len(pending_added))
        for i in range(n):
            left = pending_removed[i] if i < len(pending_removed) else None
            right = pending_added[i] if i < len(pending_added) else None
            rows.append((
                left or "", right or "",
                "change" if left is not None else "empty",
                "change" if right is not None else "empty",
            ))
        pending_removed.clear()
        pending_added.clear()

    in_hunk = False
    for line in diff_text.splitlines():
        if line.startswith("@@"):
            flush()
            if rows:
                rows.append(("⋯", "⋯", "sep", "sep"))
            in_hunk = True
        elif not in_hunk:
            continue  # skip "diff --git" / "index" / "---" / "+++" headers
        elif line.startswith(" "):
            flush()
            rows.append((line[1:], line[1:], "context", "context"))
        elif line.startswith("-"):
            if pending_added:
                # A second removed/added block right after the first (no
                # context line between them) -- flush so the two blocks
                # don't get paired against each other.
                flush()
            pending_removed.append(line[1:])
        elif line.startswith("+"):
            pending_added.append(line[1:])
        elif not line.startswith("\\"):  # "\ No newline at end of file"
            flush()
    flush()
    return rows


def _diff_cell_data_func(is_left):
    kind_col = 2 if is_left else 3

    def cell_data_func(_column, cell, model, tree_iter, _data):
        kind = model[tree_iter][kind_col]
        if kind == "sep":
            cell.set_property("cell-background-set", False)
            cell.set_property("foreground", "#888888")
            cell.set_property("style", Pango.Style.ITALIC)
            cell.set_property("xalign", 0.5)
        elif kind == "change":
            cell.set_property("style", Pango.Style.NORMAL)
            cell.set_property("xalign", 0.0)
            if is_left:
                cell.set_property("cell-background", "#5c1a1a")
                cell.set_property("foreground", "#ffcccc")
            else:
                cell.set_property("cell-background", "#1a5c1a")
                cell.set_property("foreground", "#ccffcc")
        else:  # context or empty
            cell.set_property("cell-background-set", False)
            cell.set_property("foreground-set", False)
            cell.set_property("style", Pango.Style.NORMAL)
            cell.set_property("xalign", 0.0)

    return cell_data_func


def fetch_changed_files(repo_dir, revision):
    """Re-fetches origin and recomputes the (label, path, date, lookup_paths)
    rows against `revision` (e.g. "origin/main"), for the reload button.

    Mirrors cyberbeest-update.sh's own fetch + `git diff --name-status` +
    per-path newest-commit-date enrichment, so a manual recheck from inside
    the dialog sees exactly what a fresh run of the whole script would have.
    Returns None if the fetch itself fails (network hiccup, GitHub
    unreachable) -- the caller keeps showing the previous rows in that case.
    """
    remote = revision.split("/", 1)[0]
    fetch = subprocess.run(
        ["git", "-C", repo_dir, "fetch", remote], capture_output=True, text=True, check=False
    )
    if fetch.returncode != 0:
        return None

    diff_text = subprocess.run(
        ["git", "-C", repo_dir, "diff", "--name-status", "HEAD", revision],
        capture_output=True, text=True, check=False,
    ).stdout

    raw_lines = []
    for line in diff_text.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        path = fields[-1]
        date = subprocess.run(
            ["git", "-C", repo_dir, "log", "-1", "--format=%ad", "--date=short",
             f"HEAD..{revision}", "--", path],
            capture_output=True, text=True, check=False,
        ).stdout.strip()
        raw_lines.append("\t".join(fields) + "\t" + date)

    return parse_changed_files("\n".join(raw_lines))


def show_diff_dialog(parent, repo_dir, revision, lookup_paths, display_path, date):
    result = subprocess.run(
        ["git", "-C", repo_dir, "diff", "HEAD", revision, "--", *lookup_paths],
        capture_output=True, text=True, check=False,
    )
    rows_data = build_diff_rows(result.stdout)

    diff_dialog = Gtk.Dialog(
        title=t("update.diff_dialog_title").format(path=display_path, date=date),
        transient_for=parent, modal=True,
    )
    diff_dialog.set_default_size(900, 560)
    diff_dialog.add_button(t("update.close_button"), Gtk.ResponseType.CLOSE)

    store = Gtk.ListStore(str, str, str, str)
    for left, right, left_kind, right_kind in rows_data:
        store.append([left, right, left_kind, right_kind])

    tree = Gtk.TreeView(model=store)
    tree.set_grid_lines(Gtk.TreeViewGridLines.VERTICAL)

    for title, text_col, is_left in (
        (t("update.diff_column_before"), 0, True),
        (t("update.diff_column_after"), 1, False),
    ):
        renderer = Gtk.CellRendererText()
        renderer.set_property("family", "monospace")
        column = Gtk.TreeViewColumn(title, renderer, text=text_col)
        column.set_cell_data_func(renderer, _diff_cell_data_func(is_left))
        column.set_resizable(True)
        tree.append_column(column)

    scroller = Gtk.ScrolledWindow()
    scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.ALWAYS)
    scroller.add(tree)

    content = diff_dialog.get_content_area()
    content.set_border_width(6)
    content.pack_start(scroller, True, True, 0)

    diff_dialog.show_all()
    diff_dialog.run()
    diff_dialog.destroy()


def main():
    track, other_track, repo_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    revision = sys.argv[4] if len(sys.argv) > 4 else None
    changed_files = parse_changed_files(sys.stdin.read())

    dialog = Gtk.Dialog(title=t("update.title"))
    dialog.set_default_size(420, -1)
    dialog.add_buttons(
        t("update.button_no"), Gtk.ResponseType.NO,
        t("update.button_yes"), Gtk.ResponseType.YES,
    )
    dialog.set_default_response(Gtk.ResponseType.YES)
    dialog.get_widget_for_response(Gtk.ResponseType.YES).get_style_context().add_class(
        "suggested-action"
    )

    box = dialog.get_content_area()
    box.set_border_width(12)
    box.set_spacing(8)

    heading = Gtk.Image.new_from_icon_name("dialog-question", Gtk.IconSize.DIALOG)
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    row.pack_start(heading, False, False, 0)
    label = Gtk.Label(xalign=0)
    label.set_markup(t("update.confirm_message").format(track=track))
    label.set_line_wrap(True)
    row.pack_start(label, True, True, 0)
    box.pack_start(row, True, True, 0)

    last_pull_label = Gtk.Label(xalign=0)
    last_pull_label.set_markup(f"<small>{last_pull_text(repo_dir)}</small>")
    box.pack_start(last_pull_label, False, False, 0)

    files_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    files_heading = Gtk.Label(xalign=0)
    files_heading.set_markup(f"<b>{t('update.files_heading')}</b>")
    files_row.pack_start(files_heading, True, True, 0)

    diff_button = None
    reload_button = None
    if revision:
        # Select-then-click rather than a per-row action: GTK3's TreeView has
        # no real embeddable per-row button, and a single button that acts on
        # the current selection is the standard GTK pattern for this anyway.
        diff_button = Gtk.Button(label=t("update.diff_row_button"))
        diff_button.set_sensitive(False)
        files_row.pack_start(diff_button, False, False, 0)

        # Icon-only, right of the diff button: cyberbeest-update.sh's own
        # fetch (before this dialog even opened) can be seconds or minutes
        # stale by the time the user actually looks at this list, so a quick
        # manual recheck beats having to cancel and relaunch the whole thing.
        reload_button = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        reload_button.set_tooltip_text(t("update.recheck_button_tooltip"))
        files_row.pack_start(reload_button, False, False, 0)

    box.pack_start(files_row, False, False, 0)

    # Both the table and the "no changes" label are always built, and
    # visibility toggled between them, rather than only building whichever
    # applies at start -- the reload button can turn an empty list into a
    # non-empty one (or vice versa) without rebuilding the dialog's layout.
    store = Gtk.ListStore(str, str, str)
    tree = Gtk.TreeView(model=store)
    tree.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0))
    path_renderer = Gtk.CellRendererText()
    path_renderer.set_property("family", "monospace")
    path_renderer.set_property("ellipsize", Pango.EllipsizeMode.MIDDLE)
    path_column = Gtk.TreeViewColumn(t("update.column_file"), path_renderer, text=1)
    path_column.set_expand(True)
    tree.append_column(path_column)
    date_renderer = Gtk.CellRendererText()
    date_renderer.set_property("family", "monospace")
    tree.append_column(Gtk.TreeViewColumn(t("update.column_date"), date_renderer, text=2))

    # A ScrolledWindow with a capped height, not an ever-growing list -- a
    # big pull (e.g. switching after months away) can easily touch dozens of
    # files, which would otherwise blow the dialog off-screen.
    scroller = Gtk.ScrolledWindow()
    scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroller.set_shadow_type(Gtk.ShadowType.IN)
    scroller.add(tree)
    box.pack_start(scroller, True, True, 0)

    no_changes_label = Gtk.Label(xalign=0, label=t("update.no_changes_message"))
    no_changes_label.get_style_context().add_class("dim-label")
    box.pack_start(no_changes_label, False, False, 0)

    def populate(rows):
        store.clear()
        for status, path, date, _lookup_paths in rows:
            store.append([status, path, date])
        scroller.set_visible(bool(rows))
        scroller.set_min_content_height(min(28 * len(rows) + 28, 240))
        no_changes_label.set_visible(not rows)
        if diff_button is not None:
            diff_button.set_sensitive(False)

    if diff_button is not None:
        selection = tree.get_selection()
        selection.set_mode(Gtk.SelectionMode.SINGLE)
        selection.connect(
            "changed", lambda sel: diff_button.set_sensitive(sel.count_selected_rows() > 0)
        )

        def on_diff_clicked(_button):
            model, tree_iter = selection.get_selected()
            if tree_iter is None:
                return
            idx = model.get_path(tree_iter).get_indices()[0]
            _status, path, date, lookup_paths = changed_files[idx]
            show_diff_dialog(dialog, repo_dir, revision, lookup_paths, path, date)

        diff_button.connect("clicked", on_diff_clicked)

    if reload_button is not None:

        def on_reload_clicked(_button):
            reload_button.set_sensitive(False)
            reload_button.set_tooltip_text(t("update.recheck_button_tooltip"))
            # Pump the queued redraw before the blocking fetch below so the
            # disabled state is actually visible, not just set in memory.
            while Gtk.events_pending():
                Gtk.main_iteration()

            new_rows = fetch_changed_files(repo_dir, revision)
            if new_rows is None:
                reload_button.set_tooltip_text(t("update.recheck_failed_tooltip"))
            else:
                changed_files[:] = new_rows
                populate(changed_files)
                last_pull_label.set_markup(f"<small>{last_pull_text(repo_dir)}</small>")
            reload_button.set_sensitive(True)

        reload_button.connect("clicked", on_reload_clicked)

    # A MenuButton (same pattern as run-gui.py's "more actions" dropdown)
    # rather than a plain button, so picking "switch" is a deliberate
    # two-click action, not a stray single click next to No/Yes.
    switch_button = Gtk.MenuButton(label=t("update.switch_button"))
    switch_menu = Gtk.Menu()
    switch_item = Gtk.MenuItem(label=t("update.switch_menu_item").format(track=other_track))
    switch_item.connect("activate", lambda _mi: dialog.response(RESPONSE_SWITCH))
    switch_menu.append(switch_item)
    switch_menu.show_all()
    switch_button.set_popup(switch_menu)

    # set_child_secondary puts it on the opposite end of the action area's
    # button box from Yes/No (the same mechanism a dialog's "Help" button
    # uses to sit apart from OK/Cancel) -- this is what actually achieves
    # the ordering zenity couldn't.
    action_area = dialog.get_action_area()
    action_area.pack_start(switch_button, False, False, 0)
    action_area.set_child_secondary(switch_button, True)

    dialog.show_all()
    # Must run after show_all(): it shows every child regardless of prior
    # set_visible() calls, which would otherwise re-reveal whichever of
    # scroller/no_changes_label populate() had just hidden.
    populate(changed_files)
    response = dialog.run()
    dialog.destroy()

    if response == Gtk.ResponseType.YES:
        print("yes")
    elif response == RESPONSE_SWITCH:
        print("switch")
    else:
        print("no")
    return 0


if __name__ == "__main__":
    sys.exit(main())
