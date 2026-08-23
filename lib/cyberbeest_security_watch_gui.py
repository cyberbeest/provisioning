#!/usr/bin/env python3
"""Cyberbeest Security Watch.

Manually launched (Whisker menu) tabbed window with the latest posts from a
few security feeds, plus this machine's own permanent update history:

  - Debian Security Advisories (relevant: this machine runs Debian)
  - CVE (NVD), filtered to High/Critical severity to keep the noise down
  - Exploit-DB, recent published exploits
  - Update History: local record from log-security-updates.py, with the
    actual changelog/CVE description for each upgrade, not just old->new
    version numbers

No background daemon, no notifications yet (can be added later) -- each
tab fetches fresh data when the window opens, with a Refresh button per
tab. Network fetch failures are shown inline instead of crashing the app.
"""

import datetime
import gzip
import json
import os
import re
import subprocess
import threading
import urllib.request
import xml.etree.ElementTree as ET

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) cyberbeest-security-watch/1.0"
HISTORY_PATH = os.path.expanduser("~/.config/cyberbeest/security-update-history.jsonl")


def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def open_url(url):
    subprocess.Popen(["firefox", url])


class FeedTab(Gtk.Box):
    """A scrollable list of (title, date, link) rows with a Refresh button."""

    def __init__(self, fetch_items_fn, description):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.set_border_width(8)
        self._fetch_items_fn = fetch_items_fn

        info = Gtk.Label(label=description)
        info.set_xalign(0)
        info.set_yalign(0)
        info.set_line_wrap(True)
        info.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        info.set_max_width_chars(1)
        info.set_hexpand(True)
        info.get_style_context().add_class("dim-label")
        self.pack_start(info, False, False, 0)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        refresh = Gtk.Button(label="Refresh")
        refresh.connect("clicked", lambda _b: self.load())
        toolbar.pack_start(refresh, False, False, 0)
        self.status = Gtk.Label(label="")
        self.status.set_xalign(0)
        toolbar.pack_start(self.status, True, True, 0)
        self.pack_start(toolbar, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        scroller.add(self.listbox)
        self.pack_start(scroller, True, True, 0)

    def load(self):
        for child in self.listbox.get_children():
            self.listbox.remove(child)
        self.status.set_text("Loading...")

        def worker():
            try:
                items = self._fetch_items_fn()
                error = None
            except Exception as exc:  # noqa: BLE001 - show any fetch/parse failure inline
                items, error = [], str(exc)
            GLib.idle_add(self._on_loaded, items, error)

        threading.Thread(target=worker, daemon=True).start()

    def _on_loaded(self, items, error):
        if error:
            self.status.set_text(f"Could not load feed: {error}")
            return False
        if not items:
            self.status.set_text("No items found.")
            return False
        self.status.set_text(f"{len(items)} recent item(s)")
        for title, date, link in items:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            box.set_border_width(4)
            date_label = Gtk.Label(label=date)
            date_label.set_width_chars(11)
            date_label.set_xalign(0)
            date_label.get_style_context().add_class("dim-label")
            box.pack_start(date_label, False, False, 0)
            title_widget = Gtk.Label()
            escaped = GLib.markup_escape_text(title)
            if link:
                title_widget.set_markup(f'<a href="{GLib.markup_escape_text(link)}">{escaped}</a>')
            else:
                title_widget.set_text(title)
            title_widget.set_xalign(0)
            title_widget.set_ellipsize(Pango.EllipsizeMode.END)
            title_widget.set_max_width_chars(1)
            title_widget.set_hexpand(True)
            box.pack_start(title_widget, True, True, 0)
            row.add(box)
            self.listbox.add(row)
        self.listbox.show_all()
        return False


def fetch_debian_dsa():
    root = ET.fromstring(fetch("https://www.debian.org/security/dsa.rdf"))
    ns = {"rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#", "": "http://purl.org/rss/1.0/"}
    items = []
    for item in root.findall("{http://purl.org/rss/1.0/}item"):
        title = item.findtext("{http://purl.org/rss/1.0/}title", "")
        date = item.findtext("{http://purl.org/dc/elements/1.1/}date", "")
        link = item.findtext("{http://purl.org/rss/1.0/}link", "")
        items.append((title, date[:10], link))
    return items[:40]


def fetch_nvd_cves():
    end = datetime.datetime.now(datetime.timezone.utc)
    start = end - datetime.timedelta(days=7)
    fmt = "%Y-%m-%dT%H:%M:%S.000"
    url = (
        "https://services.nvd.nist.gov/rest/json/cves/2.0"
        f"?pubStartDate={start.strftime(fmt)}&pubEndDate={end.strftime(fmt)}"
        "&cvssV3Severity=HIGH&resultsPerPage=40"
    )
    data = json.loads(fetch(url, timeout=20))
    items = []
    for v in data.get("vulnerabilities", []):
        cve = v["cve"]
        desc = next((d["value"] for d in cve.get("descriptions", []) if d["lang"] == "en"), "")
        title = f"{cve['id']}: {desc[:100]}"
        date = cve.get("published", "")[:10]
        link = f"https://nvd.nist.gov/vuln/detail/{cve['id']}"
        items.append((title, date, link))
    items.sort(key=lambda t: t[1], reverse=True)
    return items


def fetch_exploitdb():
    root = ET.fromstring(fetch("https://www.exploit-db.com/rss.xml"))
    items = []
    for item in root.findall(".//item"):
        title = item.findtext("title", "")
        link = item.findtext("link", "")
        pub_date = item.findtext("pubDate", "")
        try:
            date = datetime.datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %z").strftime("%Y-%m-%d")
        except ValueError:
            date = pub_date[:16]
        items.append((title, date, link))
    return items[:40]


class UpdateHistoryTab(Gtk.Box):
    """Local security-update-history.jsonl, newest first, with description."""

    DAYS_BACK_OPTIONS = {
        "7 days": 7,
        "30 days": 30,
        "365 days": 365,
        "all": None,
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.set_border_width(8)

        info = Gtk.Label(
            label="Not a feed from the web -- this is this machine's own permanent "
            "record of every package it has actually installed or upgraded, kept "
            "forever even though the underlying system logs get deleted after about "
            "a year. Select a row below to read the real changelog text for that "
            "update, including any CVE numbers it fixed, pulled from the package "
            "itself rather than summarized."
        )
        info.set_xalign(0)
        info.set_yalign(0)
        info.set_line_wrap(True)
        info.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        info.set_max_width_chars(1)
        info.set_hexpand(True)
        info.get_style_context().add_class("dim-label")
        self.pack_start(info, False, False, 0)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        refresh = Gtk.Button(label="Refresh")
        refresh.connect("clicked", lambda _b: self.load())
        toolbar.pack_start(refresh, False, False, 0)
        self.security_only = Gtk.CheckButton(label="Security updates only")
        self.security_only.set_active(True)
        self.security_only.connect("toggled", lambda _b: self.load())
        toolbar.pack_start(self.security_only, False, False, 0)

        toolbar.pack_start(Gtk.Label(label="Show:"), False, False, 0)
        self.days_back = Gtk.ComboBoxText()
        labels = list(self.DAYS_BACK_OPTIONS)
        for label in labels:
            self.days_back.append_text(label)
        self.days_back.set_active(labels.index("30 days"))
        self.days_back.connect("changed", lambda _b: self.load())
        toolbar.pack_start(self.days_back, False, False, 0)

        self.status = Gtk.Label(label="")
        self.status.set_xalign(0)
        toolbar.pack_start(self.status, True, True, 0)
        self.pack_start(toolbar, False, False, 0)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        list_scroller = Gtk.ScrolledWindow()
        list_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-selected", self._on_row_selected)
        list_scroller.add(self.listbox)
        paned.pack1(list_scroller, resize=True, shrink=True)

        detail_scroller = Gtk.ScrolledWindow()
        detail_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.detail_view = Gtk.TextView()
        self.detail_view.set_editable(False)
        self.detail_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self.detail_view.set_border_width(6)
        detail_scroller.add(self.detail_view)
        paned.pack2(detail_scroller, resize=True, shrink=False)
        paned.set_position(470)

        self.pack_start(paned, True, True, 0)
        self._records_by_row = {}

    def load(self):
        for child in self.listbox.get_children():
            self.listbox.remove(child)
        self._records_by_row = {}
        self.detail_view.get_buffer().set_text("")

        if not os.path.exists(HISTORY_PATH):
            self.status.set_text(f"No history log yet at {HISTORY_PATH}")
            return

        records = []
        with open(HISTORY_PATH, "rt") as f:
            for line in f:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        records.sort(key=lambda r: r["start_date"], reverse=True)
        if self.security_only.get_active():
            records = [r for r in records if r.get("security")]

        days = self.DAYS_BACK_OPTIONS[self.days_back.get_active_text()]
        if days is not None:
            cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            records = [r for r in records if r["start_date"] >= cutoff]

        self.status.set_text(f"{len(records)} update(s)")
        for rec in records[:500]:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            box.set_border_width(3)
            date_label = Gtk.Label(label=rec["start_date"][:10])
            date_label.set_width_chars(11)
            date_label.set_xalign(0)
            box.pack_start(date_label, False, False, 0)
            flag = "\U0001F6E1 " if rec.get("security") else "   "
            old = rec.get("old_version") or "(new)"
            summary = f"{flag}{rec['package']}  {old} → {rec['new_version']}"
            label = Gtk.Label(label=summary)
            label.set_xalign(0)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            label.set_width_chars(1)
            box.pack_start(label, True, True, 0)
            row.add(box)
            self.listbox.add(row)
            self._records_by_row[row] = rec
        self.listbox.show_all()

    def _on_row_selected(self, _listbox, row):
        buf = self.detail_view.get_buffer()
        if row is None:
            buf.set_text("")
            return
        rec = self._records_by_row.get(row)
        if not rec:
            return
        header = (
            f"{rec['package']} ({rec.get('arch', '')})\n"
            f"{rec.get('old_version') or '(new install)'} → {rec['new_version']}\n"
            f"Installed: {rec['start_date']}"
            f"{'  [unattended]' if rec.get('unattended') else '  [manual]'}"
            f"{'  [security]' if rec.get('security') else ''}\n\n"
        )
        changelog = rec.get("changelog") or "(no local changelog entry found for this version range)"
        buf.set_text(header + changelog)


class SecurityWatchWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Cyberbeest Security Watch")
        self.set_default_size(760, 560)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("destroy", Gtk.main_quit)

        notebook = Gtk.Notebook()

        dsa_tab = FeedTab(
            fetch_debian_dsa,
            "A Debian Security Advisory (DSA) is Debian's own official announcement "
            "that a specific package had a security flaw and a fix is now available "
            "-- this is the actionable \"update now\" signal, one advisory can cover "
            "several CVEs at once. Feed covers the whole Debian archive, not "
            "filtered to packages installed on this machine.",
        )
        notebook.append_page(dsa_tab, Gtk.Label(label="Debian Security"))

        cve_tab = FeedTab(
            fetch_nvd_cves,
            "A CVE is a standardized ID + description for one specific "
            "vulnerability -- it just documents that a flaw exists, it does not "
            "mean a fix or an attack exists yet. Shown here: newly published "
            "High/Critical severity CVEs from the NVD, across all software (not "
            "filtered to what's installed here, and most CVEs never get exploited "
            "in practice).",
        )
        notebook.append_page(cve_tab, Gtk.Label(label="CVE (High/Critical)"))

        edb_tab = FeedTab(
            fetch_exploitdb,
            "An exploit is actual working code that abuses a vulnerability -- the "
            "step beyond a CVE, this is a real attack tool, not just a "
            "description. Its existence means real attacks are practical, "
            "whether or not a fix exists yet. Feed covers all software, not "
            "filtered to what's installed here.",
        )
        notebook.append_page(edb_tab, Gtk.Label(label="Exploit-DB"))

        history_tab = UpdateHistoryTab()
        notebook.append_page(history_tab, Gtk.Label(label="Update History"))

        self.add(notebook)

        for tab in (dsa_tab, cve_tab, edb_tab):
            tab.load()
        history_tab.load()


def main():
    win = SecurityWatchWindow()
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
