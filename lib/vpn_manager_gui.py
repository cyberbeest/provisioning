#!/usr/bin/env python3
"""Cyberbeest VPN.

Replaces the bare "Import VPN Profile" Whisker entry with a proper landing
page: current connection status, a list of VPN providers known to work well
with this machine (native-app providers get a button that launches their
own proprietary client; config-only providers get a sign-up link plus the
Import button below), and the generic WireGuard profile import flow.

Written as a self-contained Gtk.Box page (VPNManagerPage) so it can later be
dropped into a unified Cyberbeest Settings dialog as a tab, matching every
other Cyberbeest config dialog (see PowerSettingsPage in
cyberbeest_power_settings_gui.py).

Provider sign-up URLs below are each vendor's real public page, not yet
affiliate links -- swap PROVIDERS[*]["signup_url"] for the real affiliate
URLs once those exist, nothing else in this file needs to change.
"""

import datetime
import os
import subprocess

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

BIN = os.path.join(os.path.expanduser("~"), ".local", "bin")
STATE_DIR = os.path.expanduser("~/.config/cyberbeest")
ACTIVE_FILE = os.path.join(STATE_DIR, "vpn_active")
PROFILES_FILE = os.path.join(STATE_DIR, "vpn_profiles")

TODAY = datetime.date.today().strftime("%B %-d, %Y")

# "native_app": has a Linux app available via Cyberbeest Package Manager
#   (not installed by default -- these run a persistent background daemon,
#   which only belongs on the machine once the user explicitly opts in).
#   Button launches it if installed, otherwise opens Package Manager.
# "config_only": no Linux app worth bundling -- button just opens the
#   provider's sign-up page; the user then imports the .conf they download
#   from that account via the Import button below.
PROVIDERS = [
    {
        "name": "Mullvad",
        "kind": "native_app",
        "desktop_id": "mullvad-vpn.desktop",
        "check_pkg": "mullvad-vpn",
        "pkg_manager_id": "mullvad",
        "note": "Account-number login, no email needed. Install via Cyberbeest "
                "Package Manager — opt-in because it runs its own background "
                "service once installed.",
        "signup_url": "https://mullvad.net/en/account/create",
        "no_log_badge": "No-log, audited",
        "no_log_detail": "Mullvad (Sweden) publishes a no-logs policy and has had "
                "it independently verified by outside auditors (Cure53, Assured AB). "
                "Signup needs no email or personal info at all — just a generated "
                "account number — so there's less to log even in principle.",
    },
    {
        "name": "Proton VPN",
        "kind": "native_app",
        "desktop_id": "protonvpn.desktop",  # unverified -- not installed on this machine yet; confirm actual .desktop id once it is
        "check_pkg": "proton-vpn-gnome-desktop",
        "pkg_manager_id": "protonvpn",
        "note": "Install via Cyberbeest Package Manager — same opt-in reasoning "
                "as Mullvad. Officially targets GNOME; still works on this "
                "Xfce machine.",
        "signup_url": "https://protonvpn.com/pricing",
        "no_log_badge": "No-log, audited",
        "no_log_detail": "Proton VPN (Switzerland) publishes a no-logs policy, "
                "independently audited by SEC Consult in 2022. Same parent company "
                "as Proton Mail.",
    },
    {
        "name": "IVPN",
        "kind": "config_only",
        "note": "No graphical Linux app. Sign up, download a WireGuard config, "
                "then Import it below.",
        "signup_url": "https://www.ivpn.net/pricing/",
        "no_log_badge": "No-log, audited",
        "no_log_detail": "IVPN (Gibraltar) publishes a no-logs policy, publishes "
                "its own third-party audit results, and maintains a warrant canary "
                "(a regularly-updated statement confirming it hasn't received a "
                "secret legal order — if it stops updating, that's the signal).",
    },
    {
        "name": "AirVPN",
        "kind": "config_only",
        "note": "No graphical Linux app. Sign up, generate a WireGuard config, "
                "then Import it below.",
        "signup_url": "https://airvpn.org/plans/",
        "no_log_badge": "No-log, unaudited",
        "no_log_detail": "AirVPN (Italy) claims a no-logs policy and has a solid "
                "reputation in the privacy community, but — unlike the three "
                "above — hasn't published an independent third-party audit "
                "confirming it. Italy is also an EU jurisdiction, considered a "
                "somewhat weaker legal shield than Sweden/Switzerland/Gibraltar "
                "by some privacy advocates, though this matters less if there's "
                "genuinely nothing logged to hand over.",
    },
]

PACKAGE_MANAGER_SCRIPT = "__PACKAGE_MANAGER_SCRIPT__"


def launch(*args):
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_url(url):
    launch("firefox", "--new-window", url)


def read_active():
    try:
        with open(ACTIVE_FILE) as f:
            name = f.read().strip()
            return name or None
    except FileNotFoundError:
        return None


def profile_count():
    try:
        with open(PROFILES_FILE) as f:
            return len([line for line in f if line.strip()])
    except FileNotFoundError:
        return 0


def is_active(name):
    try:
        result = subprocess.run(
            ["sudo", "-n", "systemctl", "is-active", "--quiet", f"wg-quick@{name}"],
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def is_pkg_installed(pkg):
    try:
        result = subprocess.run(
            ["dpkg-query", "-W", "-f", "${Status}", pkg],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0 and "install ok installed" in result.stdout
    except Exception:
        return False


class VPNManagerPage(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.set_border_width(16)

        heading = Gtk.Label(xalign=0)
        heading.set_markup("<b>VPN Status</b>")
        self.pack_start(heading, False, False, 0)

        self.status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.pack_start(self.status_box, False, False, 0)

        self.status_label = Gtk.Label(xalign=0)
        self.status_box.pack_start(self.status_label, False, False, 0)

        self.disconnect_button = Gtk.Button(label="Disconnect")
        self.disconnect_button.connect("clicked", self.on_disconnect)
        self.disconnect_button.set_no_show_all(True)
        self.status_box.pack_start(self.disconnect_button, False, False, 0)

        self._refresh_status()
        GLib.timeout_add_seconds(5, self._refresh_status_tick)

        kill_switch_note = Gtk.Label(xalign=0, wrap=True, max_width_chars=48)
        kill_switch_note.set_markup(
            '<span foreground="#3a8f3a"><b>Automatic kill switch:</b></span> '
            "Any VPN config profile you import here gets a kill switch added "
            "automatically if it doesn't already have one — if the tunnel ever "
            "drops unexpectedly, your traffic is blocked instead of silently "
            "falling back to your raw connection."
        )
        self.pack_start(kill_switch_note, False, False, 0)

        self.pack_start(Gtk.Separator(), False, False, 4)

        providers_heading = Gtk.Label(xalign=0)
        providers_heading.set_markup(f"<b>Known-supported VPNs (as of {TODAY})</b>")
        self.pack_start(providers_heading, False, False, 0)

        for provider in PROVIDERS:
            self.pack_start(self._build_provider_row(provider), False, False, 0)

        self.pack_start(Gtk.Separator(), False, False, 4)

        other_heading = Gtk.Label(xalign=0)
        other_heading.set_markup("<b>Any other VPN</b>")
        self.pack_start(other_heading, False, False, 0)

        other_note = Gtk.Label(
            wrap=True, max_width_chars=48, xalign=0,
            label="Any provider that hands out a WireGuard .conf file works, even "
                  "if it's not listed above. Import it here — Cyberbeest adds a "
                  "kill switch automatically if the config doesn't already have one.",
        )
        other_note.get_style_context().add_class("dim-label")
        self.pack_start(other_note, False, False, 0)

        import_button = Gtk.Button(label="Import VPN Profile...")
        import_button.connect("clicked", self.on_import)
        self.pack_start(import_button, False, False, 0)

    def _build_provider_row(self, provider):
        frame = Gtk.Frame()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_border_width(10)
        frame.add(box)

        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.pack_start(top_row, False, False, 0)

        name_label = Gtk.Label(xalign=0)
        name_label.set_markup(f"<b>{GLib.markup_escape_text(provider['name'])}</b>")
        top_row.pack_start(name_label, True, True, 0)

        if provider["kind"] == "native_app":
            if is_pkg_installed(provider["check_pkg"]):
                app_button = Gtk.Button(label=f"Open {provider['name']}")
                app_button.connect("clicked", self.on_open_app, provider["desktop_id"])
            else:
                app_button = Gtk.Button(label="Install...")
                app_button.connect(
                    "clicked", self.on_open_package_manager, provider.get("pkg_manager_id")
                )
            top_row.pack_start(app_button, False, False, 0)

        signup_button = Gtk.Button(label="Sign Up")
        signup_button.connect("clicked", self.on_signup, provider["signup_url"])
        top_row.pack_start(signup_button, False, False, 0)

        badge_text = provider.get("no_log_badge")
        if badge_text:
            color = "#3a8f3a" if "audited" in badge_text and "unaudited" not in badge_text else "#a08000"
            badge = Gtk.Label(xalign=0)
            badge.set_markup(
                f'<span underline="single" foreground="{color}">'
                f'{GLib.markup_escape_text(badge_text)}</span>'
            )
            badge.set_tooltip_text(provider.get("no_log_detail", ""))
            badge_box = Gtk.EventBox()
            badge_box.add(badge)
            box.pack_start(badge_box, False, False, 0)

        note_label = Gtk.Label(
            wrap=True, max_width_chars=48, xalign=0, label=provider["note"]
        )
        note_label.get_style_context().add_class("dim-label")
        box.pack_start(note_label, False, False, 0)

        return frame

    def _refresh_status(self):
        active = read_active()
        if active and is_active(active):
            self.status_label.set_text(f"Connected: {active}")
            self.disconnect_button.set_sensitive(True)
            self.disconnect_button.show()
        else:
            count = profile_count()
            if count == 0:
                self.status_label.set_text("Not connected. No profiles imported yet.")
            else:
                self.status_label.set_text("Not connected.")
            self.disconnect_button.hide()

    def _refresh_status_tick(self):
        self._refresh_status()
        return True  # keep polling

    def on_disconnect(self, _button):
        launch(f"{BIN}/vpn-disconnect.sh")
        GLib.timeout_add_seconds(1, self._refresh_status_tick_once)

    def _refresh_status_tick_once(self):
        self._refresh_status()
        return False

    def on_import(self, _button):
        launch(f"{BIN}/vpn-import.sh")

    def on_open_app(self, _button, desktop_id):
        launch("gtk-launch", desktop_id)

    def on_open_package_manager(self, _button, pkg_manager_id):
        if pkg_manager_id:
            launch(PACKAGE_MANAGER_SCRIPT, f"--select={pkg_manager_id}")
        else:
            launch(PACKAGE_MANAGER_SCRIPT)

    def on_signup(self, _button, url):
        open_url(url)


class VPNManagerWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Cyberbeest VPN")
        self.set_default_size(420, -1)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("destroy", Gtk.main_quit)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.add(VPNManagerPage())
        self.add(scroller)
        self.set_default_size(420, 560)


def main():
    win = VPNManagerWindow()
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
