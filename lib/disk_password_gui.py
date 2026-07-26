#!/usr/bin/env python3
"""Simple GUI to change the machine's passwords.

There are two distinct passwords on this machine:

  * Master password - the normal LUKS passphrase that unlocks the disk
                       at startup (LUKS key slot 0).
  * Short password   - the everyday cyberbeest login/admin password
                       (a regular Linux account password).

The master password uses pkexec (cryptsetup needs root) so the user gets
a normal graphical authentication prompt instead of needing a terminal.
The short password is changed via a real `passwd` run as the user
themselves, no root needed -- see change_user_password() for why.
"""

import argparse
import os
import pty
import secrets
import select
import subprocess
import termios
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib, Gtk

DEVICE = "/dev/sda3"
CRYPTSETUP = "/sbin/cryptsetup"
PASSWD = "/usr/bin/passwd"
LOGO_PATH = os.path.expanduser("~/Pictures/Cyberbeest-black.png")
LOGO_SIZE = 96
WORDLISTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wordlists")


def detect_language():
    """Pick 'de' or 'en' based on the system locale (only those two are supported)."""
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if value and value.lower().startswith("de"):
            return "de"
    return "en"


def load_wordlist(lang):
    path = os.path.join(WORDLISTS_DIR, f"wordlist_{lang}.txt")
    words = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split(maxsplit=1)
            if len(parts) == 2:
                words.append(parts[1])
    return words


def generate_passphrase(wordlist, word_count):
    return "-".join(secrets.choice(wordlist) for _ in range(word_count))


LANGUAGES = [("en", "English"), ("de", "Deutsch")]


def change_luks_passphrase(device, slot, old_password, new_password):
    """Run cryptsetup luksChangeKey via pkexec, feeding passwords on stdin.

    Returns (success, message).
    """
    try:
        proc = subprocess.Popen(
            ["pkexec", CRYPTSETUP, "luksChangeKey", device, "-S", str(slot)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as e:
        return False, f"Could not start pkexec: {e}"

    stdin_data = f"{old_password}\n{new_password}\n"
    stdout, stderr = proc.communicate(input=stdin_data)

    if proc.returncode == 0:
        return True, "The password was changed successfully."

    if proc.returncode in (126, 127):
        return False, "Authentication was cancelled, so the password was not changed."

    detail = (stderr or stdout or "").strip()
    if "No key available" in detail or "incorrect" in detail.lower():
        return False, "The current password you entered was not correct."

    return False, f"The password could not be changed.\n\nDetails: {detail or 'unknown error'}"


def change_user_password(current_password, new_password):
    """Change the login password by running `passwd` in a pty, as the
    current user -- no root needed.

    Going through `passwd`/PAM normally (instead of resetting the hash
    directly as root) matters because pam_gnome_keyring only re-wraps
    the login keyring with the new password when it sees both the old
    and new password during a real password-change auth flow. A root
    reset skips that, silently leaving the keyring encrypted with the
    now-gone old password until you delete it and let it regenerate.

    `passwd`'s three prompts (current, new, retype) aren't fed blindly:
    each response is sent only once the pty has gone quiet for a beat,
    since that's what "waiting on you" looks like regardless of the
    exact prompt wording. Uses pty.fork() (not Popen + openpty) so the
    child gets a real controlling terminal, matching what an
    interactive password prompt expects.

    Returns (success, message).
    """
    try:
        pid, master_fd = pty.fork()
    except OSError as e:
        return False, f"Could not open a pty: {e}"

    if pid == 0:
        try:
            os.execvp(PASSWD, [PASSWD])
        finally:
            os._exit(127)

    try:
        attrs = termios.tcgetattr(master_fd)
        attrs[3] &= ~termios.ECHO
        termios.tcsetattr(master_fd, termios.TCSANOW, attrs)
    except termios.error:
        pass

    responses = [current_password, new_password, new_password]
    sent = 0
    deadline = time.monotonic() + 20

    while time.monotonic() < deadline:
        quiet_timeout = 0.3 if sent < len(responses) else 5
        try:
            ready, _, _ = select.select([master_fd], [], [], quiet_timeout)
        except OSError:
            break

        if ready:
            try:
                chunk = os.read(master_fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            continue

        if sent >= len(responses):
            break
        try:
            os.write(master_fd, f"{responses[sent]}\n".encode())
        except OSError:
            break
        sent += 1

    try:
        os.close(master_fd)
    except OSError:
        pass

    try:
        _, status = os.waitpid(pid, 0)
        returncode = os.waitstatus_to_exitcode(status)
    except ChildProcessError:
        returncode = -1

    if returncode == 0:
        return True, "The password was changed successfully."

    return False, (
        "The password could not be changed. This usually means the current "
        "password was incorrect."
    )


PASSWORD_TYPES = {
    "master": {
        "title": "Master password",
        "description": "The password used to decrypt your hard drive at startup.",
        "requires_current": True,
        "change": lambda old, new: change_luks_passphrase(DEVICE, 0, old, new),
        "word_count": 4,
        "min_length": 12,
    },
    "short": {
        "title": "Short password",
        "description": "The password used to enter your desktop or unlock the screen. Both passwords are required to start the device.",
        "requires_current": True,
        "change": change_user_password,
        "word_count": 2,
        "min_length": 8,
    },
}

PASSWORD_ORDER = ["master", "short"]


class PasswordWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Cyberbeest Change Password")
        self.set_border_width(16)
        self.set_resizable(False)
        self.set_default_size(520, -1)
        self.set_position(Gtk.WindowPosition.CENTER)

        self.active_type = PASSWORD_ORDER[0]

        outer_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        self.add(outer_box)

        logo = self._load_logo()
        if logo is not None:
            logo_image = Gtk.Image.new_from_pixbuf(logo)
            logo_image.set_valign(Gtk.Align.START)
            outer_box.pack_start(logo_image, False, False, 0)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content.set_hexpand(True)
        outer_box.pack_start(content, True, True, 0)

        self.notebook = Gtk.Notebook()
        for key in PASSWORD_ORDER:
            self.notebook.append_page(Gtk.Box(), Gtk.Label(label=PASSWORD_TYPES[key]["title"]))
        self.notebook.connect("switch-page", self.on_tab_switched)
        content.pack_start(self.notebook, False, False, 0)

        self.language_selector = Gtk.ComboBoxText()
        for code, name in LANGUAGES:
            self.language_selector.append(code, name)
        self.language_selector.set_active_id(detect_language())
        self.language_selector.connect("changed", self.on_language_changed)

        self.wordlist = load_wordlist(self.language_selector.get_active_id())

        self.description_label = Gtk.Label(label="", wrap=True, xalign=0)
        content.pack_start(self.description_label, False, False, 0)

        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        grid.set_hexpand(True)
        content.pack_start(grid, False, False, 0)

        self.current_label, self.current_entry = self._add_row(grid, 0, "Current password:")
        self._add_row_widgets(grid, 1, "New password:")
        self.new_entry = self._last_entry
        self._add_row_widgets(grid, 2, "Confirm new password:")
        self.confirm_entry = self._last_entry

        self.generate_button = Gtk.Button(label="Generate")
        self.generate_button.connect("clicked", self.on_generate_clicked)
        grid.attach(self.generate_button, 2, 2, 1, 1)
        grid.attach(self.language_selector, 3, 2, 1, 1)

        self.status_label = Gtk.Label(label="", wrap=True, xalign=0)
        self.status_label.set_no_show_all(True)
        content.pack_start(self.status_label, False, False, 0)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        content.pack_start(button_box, False, False, 0)

        self.change_button = Gtk.Button(label="Change Password")
        self.change_button.connect("clicked", self.on_change_clicked)
        button_box.pack_end(self.change_button, False, False, 0)

        cancel_button = Gtk.Button(label="Cancel")
        cancel_button.connect("clicked", lambda _b: Gtk.main_quit())
        button_box.pack_end(cancel_button, False, False, 0)

        self.connect("destroy", Gtk.main_quit)

        self._apply_type(self.active_type)

    def _load_logo(self):
        if not os.path.exists(LOGO_PATH):
            return None
        try:
            return GdkPixbuf.Pixbuf.new_from_file_at_scale(
                LOGO_PATH, LOGO_SIZE, LOGO_SIZE, True
            )
        except GLib.Error:
            return None

    def _add_row(self, grid, row, label_text):
        self._add_row_widgets(grid, row, label_text)
        return self._last_label, self._last_entry

    def _add_row_widgets(self, grid, row, label_text):
        label = Gtk.Label(label=label_text, xalign=0)
        entry = Gtk.Entry(visibility=False, hexpand=True)
        entry.set_width_chars(34)
        entry.set_activates_default(True)
        entry.connect("icon-press", self.on_toggle_password_visibility)
        self._set_entry_visibility(entry, False)
        grid.attach(label, 0, row, 1, 1)
        grid.attach(entry, 1, row, 1, 1)
        self._last_label = label
        self._last_entry = entry

    def _set_entry_visibility(self, entry, visible):
        entry.set_visibility(visible)
        icon = "view-conceal-symbolic" if visible else "view-reveal-symbolic"
        tooltip = "Hide password" if visible else "Show password"
        entry.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, icon)
        entry.set_icon_activatable(Gtk.EntryIconPosition.SECONDARY, True)
        entry.set_icon_tooltip_text(Gtk.EntryIconPosition.SECONDARY, tooltip)

    def on_toggle_password_visibility(self, entry, icon_pos, _event):
        if icon_pos != Gtk.EntryIconPosition.SECONDARY:
            return
        self._set_entry_visibility(entry, not entry.get_visibility())

    def on_language_changed(self, _combo):
        self.wordlist = load_wordlist(self.language_selector.get_active_id())

    def on_generate_clicked(self, _button):
        info = PASSWORD_TYPES[self.active_type]
        passphrase = generate_passphrase(self.wordlist, info["word_count"])
        self._set_entry_visibility(self.new_entry, True)
        self._set_entry_visibility(self.confirm_entry, True)
        self.new_entry.set_text(passphrase)
        self.confirm_entry.set_text(passphrase)
        self.set_status("Generated a new passphrase below — write it down or memorize it before changing the password.", is_error=False)

    def on_tab_switched(self, _notebook, _page, page_num):
        self._apply_type(PASSWORD_ORDER[page_num])

    def _apply_type(self, type_key):
        self.active_type = type_key
        info = PASSWORD_TYPES[type_key]

        self.description_label.set_text(
            f"{info['description']}\nRecommended format: {info['word_count']} random words"
            f" (minimum length: {info['min_length']} characters)"
        )

        self.current_entry.set_text("")
        self.new_entry.set_text("")
        self.confirm_entry.set_text("")
        self._set_entry_visibility(self.new_entry, False)
        self._set_entry_visibility(self.confirm_entry, False)
        self.status_label.set_no_show_all(True)
        self.status_label.hide()

        if info["requires_current"]:
            self.current_label.show()
            self.current_entry.show()
        else:
            self.current_label.hide()
            self.current_entry.hide()

    def set_status(self, text, is_error=True):
        self.status_label.set_markup(
            f'<span foreground="{"red" if is_error else "green"}">{GLib.markup_escape_text(text)}</span>'
        )
        self.status_label.set_no_show_all(False)
        self.status_label.show()

    def on_change_clicked(self, _button):
        info = PASSWORD_TYPES[self.active_type]
        current = self.current_entry.get_text()
        new = self.new_entry.get_text()
        confirm = self.confirm_entry.get_text()

        if info["requires_current"] and not current:
            self.set_status("Please fill in all fields.")
            return
        if not new:
            self.set_status("Please fill in all fields.")
            return
        if new != confirm:
            self.set_status("The new password and confirmation do not match.")
            return
        if len(new) < info["min_length"]:
            self.set_status(f"The new password should be at least {info['min_length']} characters long.")
            return

        if not self._confirm_written_down(info["title"], new):
            return

        self.change_button.set_sensitive(False)
        self.set_status("Waiting for authentication...", is_error=False)

        # Run on a background thread so the pkexec prompt doesn't freeze the window.
        threading.Thread(
            target=self._run_change, args=(info["change"], current, new), daemon=True
        ).start()

    def _confirm_written_down(self, title, new_password):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.YES_NO,
            text="DID YOU REALLY WRITE THIS DOWN OR MEMORIZE IT?",
        )
        word = title.split()[0].upper()
        dialog.format_secondary_text(f"My Cyberbeest {word} password is: {new_password}")
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.YES

    def _run_change(self, change_fn, current, new):
        success, message = change_fn(current, new)
        GLib.idle_add(self._on_change_done, success, message)

    def _on_change_done(self, success, message):
        self.set_status(message, is_error=not success)
        self.change_button.set_sensitive(True)
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tab", choices=PASSWORD_ORDER, help="Open with this password type's tab preselected"
    )
    args = parser.parse_args()

    win = PasswordWindow()
    if args.tab:
        win.notebook.set_current_page(PASSWORD_ORDER.index(args.tab))
        win._apply_type(args.tab)
    win.show_all()
    win._apply_type(win.active_type)
    Gtk.main()


if __name__ == "__main__":
    main()
