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
import glob
import os
import pty
import secrets
import select
import shutil
import subprocess
import tempfile
import termios
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib, Gtk

from i18n import t

CRYPTSETUP = "/sbin/cryptsetup"
PASSWD = "/usr/bin/passwd"
SET_BOOT_NAME = "/usr/local/sbin/cyberbeest-set-boot-name"
BOOT_NAME_FILE = "/etc/cyberbeest/machine-name"
BOOT_NAME_MAX_LENGTH = 40
SET_BOOT_BRIGHT_MODE = "/usr/local/sbin/cyberbeest-set-boot-bright-mode"
BOOT_BRIGHT_MODE_FILE = "/etc/cyberbeest/plymouth-bright-mode"


def _pictures_dir():
    try:
        return subprocess.check_output(["xdg-user-dir", "PICTURES"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return os.path.expanduser("~/Pictures")


LOGO_PATH = os.path.join(_pictures_dir(), "Cyberbeest-black.png")
LOGO_SIZE = 96
WORDLISTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wordlists")

SET_BOOT_CHIME = "/usr/local/sbin/cyberbeest-set-boot-chime"
SOUNDS_DIR = "/usr/local/share/sounds"
BOOT_CHIME_ACTIVE = f"{SOUNDS_DIR}/cyberbeest-boot-chime.wav"
BOOT_CHIME_DEFAULT = f"{SOUNDS_DIR}/cyberbeest-boot-chime-default.wav"
BOOT_CHIME_HISTORY_DIR = f"{SOUNDS_DIR}/cyberbeest-boot-chime-history"
BOOT_CHIME_STATE_FILE = "/etc/cyberbeest/boot-chime-enabled"
BOOT_CHIME_SELECTED_FILE = "/etc/cyberbeest/boot-chime-selected"

SHUTDOWN_SOUNDS_DIR = os.path.expanduser("~/.local/share/sounds")
SHUTDOWN_CHIME_ACTIVE = f"{SHUTDOWN_SOUNDS_DIR}/cyberbeest-shutdown-chime.wav"
SHUTDOWN_CHIME_DEFAULT = f"{SHUTDOWN_SOUNDS_DIR}/cyberbeest-shutdown-chime-default.wav"
SHUTDOWN_CHIME_HISTORY_DIR = f"{SHUTDOWN_SOUNDS_DIR}/cyberbeest-shutdown-chime-history"
SHUTDOWN_CHIME_STATE_FILE = os.path.expanduser("~/.config/cyberbeest/shutdown-chime-enabled")
SHUTDOWN_CHIME_SELECTED_FILE = os.path.expanduser("~/.config/cyberbeest/shutdown-chime-selected")

# Matches cyberbeest-set-boot-chime.sh's MAX_HISTORY -- kept as separate
# constants (root vs. user-space history pruning happen in different
# places) rather than one shared value, but the number itself should stay
# in sync so both chimes behave the same.
MAX_CHIME_HISTORY = 10

# Rebuilding is update-initramfs -k all, which regenerates one initramfs per
# installed kernel and is slow/CPU-bound enough that the machine feels
# frozen without some explanation of what's actually happening. Per-kernel
# cost measured once (measure-boot-name-rebuild-time.sh: ~54.6s for the 2
# kernels installed on this machine at the time), then scaled by the actual
# current kernel count so the estimate stays roughly honest as kernels come
# and go (e.g. right after an upgrade, before the old one is autoremoved).
BOOT_REBUILD_SECONDS_PER_KERNEL = 27


def count_installed_kernels():
    return len(glob.glob("/boot/vmlinuz-*")) or 1


def estimate_boot_rebuild_seconds():
    return BOOT_REBUILD_SECONDS_PER_KERNEL * count_installed_kernels()


def detect_luks_device():
    """Find the LUKS partition backing the root filesystem.

    Walks up the block-device stack from / (e.g. LVM root -> dm-crypt ->
    physical partition) instead of assuming a fixed path like /dev/sda3 --
    that breaks on NVMe drives, multi-disk machines, or a different
    partition layout from a USB install.
    """
    # -s lists the full dependency chain (root fs -> ... -> physical disk),
    # so root-on-LVM-on-LUKS, root directly on LUKS, or extra layers like
    # mdraid all resolve the same way: find the one line typed crypto_LUKS.
    root_src = subprocess.check_output(["findmnt", "-no", "SOURCE", "/"], text=True).strip()
    chain = subprocess.check_output(["lsblk", "-lpnso", "NAME,FSTYPE", root_src], text=True)
    for line in chain.splitlines():
        name, _, fstype = line.strip().partition(" ")
        if fstype.strip() == "crypto_LUKS":
            return name
    raise RuntimeError("Could not find the LUKS-encrypted device backing the root filesystem")


DEVICE = detect_luks_device()


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
        return False, f"{t('pw.pkexec_error')} {e}"

    stdin_data = f"{old_password}\n{new_password}\n"
    stdout, stderr = proc.communicate(input=stdin_data)

    if proc.returncode == 0:
        return True, t("pw.success")

    if proc.returncode in (126, 127):
        return False, t("pw.auth_cancelled")

    detail = (stderr or stdout or "").strip()
    if "No key available" in detail or "incorrect" in detail.lower():
        return False, t("pw.wrong_current")

    return False, f"{t('pw.change_failed')}\n\n{t('pw.details')}: {detail or t('pw.unknown_error')}"


RECORD_INITIAL_PASSWORD = "/usr/local/sbin/cyberbeest-record-initial-password"


def record_as_temporary(ptype, value):
    """Marks a just-set password as temporary, arming the login-time nag
    (cyberbeest-password-nag.py) to prompt for it to be changed later --
    the same effect as manually running cyberbeest-record-initial-password
    (see 21-default-password-nag.sh), but from the checkbox in this GUI.
    Always tags "weak" (nag-until-changed, no "keep it" option), since this
    checkbox is specifically for passwords you know aren't meant to stick.

    Runs via pkexec since the recorder writes root-only
    /etc/cyberbeest/initial-passwords.conf. Returns (success, message).
    """
    try:
        proc = subprocess.run(
            ["pkexec", RECORD_INITIAL_PASSWORD, ptype, value, "weak"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    if proc.returncode == 0:
        return True, None
    return False, (proc.stderr or proc.stdout).strip() or t("pw.unknown_error")


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
        return False, f"{t('pw.pty_error')} {e}"

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
        return True, t("pw.success")

    return False, t("pw.change_failed_wrong_current")


PASSWORD_TYPES = {
    "master": {
        "title": t("pw.master_title"),
        "description": t("pw.master_desc"),
        "requires_current": True,
        "change": lambda old, new: change_luks_passphrase(DEVICE, 0, old, new),
        "word_count": 3,
        "min_length": 12,
    },
    "short": {
        "title": t("pw.short_title"),
        "description": t("pw.short_desc"),
        "requires_current": True,
        "change": change_user_password,
        "word_count": 2,
        "min_length": 8,
    },
}

PASSWORD_ORDER = ["master", "short"]


def read_boot_name():
    try:
        with open(BOOT_NAME_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def set_boot_name(name):
    """Run cyberbeest-set-boot-name via pkexec to update the machine-name
    line shown above the LUKS unlock prompt, rebuilding the initramfs.

    Returns (success, message).
    """
    try:
        proc = subprocess.run(
            ["pkexec", SET_BOOT_NAME, name],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as e:
        return False, f"{t('pw.pkexec_error')} {e}"

    if proc.returncode == 0:
        return True, t("pw.boot_name_set") if name else t("pw.boot_name_cleared")

    if proc.returncode in (126, 127):
        return False, t("pw.boot_name_auth_cancelled")

    detail = (proc.stderr or proc.stdout or "").strip()
    return False, f"{t('pw.boot_name_failed')}\n\n{t('pw.details')}: {detail or t('pw.unknown_error')}"


def read_boot_bright_mode():
    try:
        with open(BOOT_BRIGHT_MODE_FILE, encoding="utf-8") as f:
            return f.read().strip() == "1"
    except OSError:
        return False


def set_boot_bright_mode(enabled):
    """Run cyberbeest-set-boot-bright-mode via pkexec to toggle a bright
    background at the LUKS unlock prompt, rebuilding the initramfs.

    Returns (success, message).
    """
    try:
        proc = subprocess.run(
            ["pkexec", SET_BOOT_BRIGHT_MODE, "1" if enabled else "0"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as e:
        return False, f"{t('pw.pkexec_error')} {e}"

    if proc.returncode == 0:
        return True, t("pw.boot_bright_mode_on") if enabled else t("pw.boot_bright_mode_off")

    if proc.returncode in (126, 127):
        return False, t("pw.boot_bright_mode_auth_cancelled")

    detail = (proc.stderr or proc.stdout or "").strip()
    return False, f"{t('pw.boot_bright_mode_failed')}\n\n{t('pw.details')}: {detail or t('pw.unknown_error')}"


def convert_to_wav(src_path):
    """Convert an arbitrary wav/mp3/ogg file to a plain 16-bit PCM wav via
    ffmpeg, since that's the one format aplay (boot, no PulseAudio/PipeWire
    session yet) and paplay (shutdown) both play without surprises --
    running every import through ffmpeg regardless of source format also
    normalizes odd wav variants (e.g. float samples) that aplay chokes on.

    Returns (tmp_wav_path, None) on success, or (None, error_message).
    Caller owns the returned temp file and must remove it when done.
    """
    if shutil.which("ffmpeg") is None:
        return None, t("pw.sound_ffmpeg_missing")

    fd, tmp_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", src_path, "-ar", "44100", "-ac", "2", "-sample_fmt", "s16", tmp_path],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None, t("pw.sound_ffmpeg_missing")

    if proc.returncode != 0 or not os.path.getsize(tmp_path):
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return None, t("pw.sound_install_failed")

    return tmp_path, None


class BootChimeBackend:
    """Startup chime storage lives under /usr/local/share (root-owned), so
    every write goes through the cyberbeest-set-boot-chime pkexec helper.
    Reads are plain file access -- the sounds dir and its history/state
    files are all world-readable.
    """

    active_path = BOOT_CHIME_ACTIVE

    def read_enabled(self):
        try:
            with open(BOOT_CHIME_STATE_FILE, encoding="utf-8") as f:
                return f.read().strip() != "0"
        except OSError:
            return True

    def read_selected(self):
        try:
            with open(BOOT_CHIME_SELECTED_FILE, encoding="utf-8") as f:
                return f.read().strip() or "default"
        except OSError:
            return "default"

    def list_history(self):
        try:
            names = os.listdir(BOOT_CHIME_HISTORY_DIR)
        except OSError:
            return []
        names.sort(key=lambda n: os.path.getmtime(os.path.join(BOOT_CHIME_HISTORY_DIR, n)), reverse=True)
        return names

    def _run_pkexec(self, args, success_message, failure_message):
        try:
            proc = subprocess.run(["pkexec", SET_BOOT_CHIME] + args, capture_output=True, text=True)
        except FileNotFoundError as e:
            return False, f"{t('pw.pkexec_error')} {e}"
        if proc.returncode == 0:
            return True, success_message
        if proc.returncode in (126, 127):
            return False, t("pw.auth_cancelled")
        return False, failure_message

    def set_enabled(self, enabled):
        message = t("pw.sound_enabled_on") if enabled else t("pw.sound_enabled_off")
        return self._run_pkexec(
            ["enable" if enabled else "disable"], message, t("pw.sound_toggle_failed")
        )

    def select_sound(self, name):
        return self._run_pkexec(["select", name], t("pw.sound_selected"), t("pw.sound_select_failed"))

    def import_sound(self, tmp_wav_path, basename):
        return self._run_pkexec(
            ["import", tmp_wav_path, basename], t("pw.sound_installed"), t("pw.sound_install_failed")
        )


class ShutdownChimeBackend:
    """Shutdown chime storage lives entirely under the user's home
    directory, so every operation is a plain (no-root) file op.
    """

    active_path = SHUTDOWN_CHIME_ACTIVE

    def read_enabled(self):
        try:
            with open(SHUTDOWN_CHIME_STATE_FILE, encoding="utf-8") as f:
                return f.read().strip() != "0"
        except OSError:
            return True

    def read_selected(self):
        try:
            with open(SHUTDOWN_CHIME_SELECTED_FILE, encoding="utf-8") as f:
                return f.read().strip() or "default"
        except OSError:
            return "default"

    def list_history(self):
        try:
            names = os.listdir(SHUTDOWN_CHIME_HISTORY_DIR)
        except OSError:
            return []
        names.sort(
            key=lambda n: os.path.getmtime(os.path.join(SHUTDOWN_CHIME_HISTORY_DIR, n)), reverse=True
        )
        return names

    def set_enabled(self, enabled):
        try:
            os.makedirs(os.path.dirname(SHUTDOWN_CHIME_STATE_FILE), exist_ok=True)
            with open(SHUTDOWN_CHIME_STATE_FILE, "w", encoding="utf-8") as f:
                f.write("1" if enabled else "0")
        except OSError:
            return False, t("pw.sound_toggle_failed")
        return True, t("pw.sound_enabled_on") if enabled else t("pw.sound_enabled_off")

    def select_sound(self, name):
        src = SHUTDOWN_CHIME_DEFAULT if name == "default" else os.path.join(SHUTDOWN_CHIME_HISTORY_DIR, name)
        if not os.path.isfile(src):
            return False, t("pw.sound_select_failed")
        try:
            shutil.copyfile(src, SHUTDOWN_CHIME_ACTIVE)
            self._write_selected(name)
        except OSError:
            return False, t("pw.sound_select_failed")
        return True, t("pw.sound_selected")

    def import_sound(self, tmp_wav_path, basename):
        try:
            os.makedirs(SHUTDOWN_CHIME_HISTORY_DIR, exist_ok=True)
            safe = "".join(c for c in basename if c.isalnum() or c in "._-") or "sound.wav"
            entry = f"{time.strftime('%Y%m%d-%H%M%S')}-{safe}"
            dest = os.path.join(SHUTDOWN_CHIME_HISTORY_DIR, entry)
            shutil.copyfile(tmp_wav_path, dest)
            shutil.copyfile(tmp_wav_path, SHUTDOWN_CHIME_ACTIVE)
            self._write_selected(entry)
            self._prune_history()
        except OSError:
            return False, t("pw.sound_install_failed")
        return True, t("pw.sound_installed")

    def _write_selected(self, name):
        os.makedirs(os.path.dirname(SHUTDOWN_CHIME_SELECTED_FILE), exist_ok=True)
        with open(SHUTDOWN_CHIME_SELECTED_FILE, "w", encoding="utf-8") as f:
            f.write(name)

    def _prune_history(self):
        names = self.list_history()
        for old in names[MAX_CHIME_HISTORY:]:
            try:
                os.remove(os.path.join(SHUTDOWN_CHIME_HISTORY_DIR, old))
            except OSError:
                pass


class ChimeSection:
    """One startup/shutdown chime control block: enable checkbox, a sound
    picker dropdown (standard chime + recent imports), and choose-file /
    play buttons. Two of these live in the Sound tab, each wired to a
    backend (BootChimeBackend or ShutdownChimeBackend) that actually
    applies changes -- this class only knows about widgets and threading,
    not where the files live or whether pkexec is involved.
    """

    def __init__(self, backend, title, description, parent_window):
        self.backend = backend
        self.parent_window = parent_window

        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        heading = Gtk.Label(label=f"<b>{GLib.markup_escape_text(title)}</b>", use_markup=True, xalign=0)
        self.widget.pack_start(heading, False, False, 0)

        desc = Gtk.Label(label=description, wrap=True, xalign=0)
        self.widget.pack_start(desc, False, False, 0)

        self.enabled_check = Gtk.CheckButton(label=t("pw.sound_enabled"))
        self.enabled_check.connect("toggled", self.on_enabled_toggled)
        self.widget.pack_start(self.enabled_check, False, False, 0)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.widget.pack_start(row, False, False, 0)

        self.combo = Gtk.ComboBoxText()
        self.combo.set_hexpand(True)
        self.combo.connect("changed", self.on_combo_changed)
        row.pack_start(self.combo, True, True, 0)

        play_button = Gtk.Button(label=t("pw.sound_play"))
        play_button.connect("clicked", self.on_play_clicked)
        row.pack_start(play_button, False, False, 0)

        choose_button = Gtk.Button(label=t("pw.sound_choose_file"))
        choose_button.connect("clicked", self.on_choose_file_clicked)
        self.widget.pack_start(choose_button, False, False, 0)

        self.status_label = Gtk.Label(label="", wrap=True, xalign=0)
        self.status_label.set_no_show_all(True)
        self.widget.pack_start(self.status_label, False, False, 0)

        self.refresh()

    def set_status(self, text, is_error=True):
        self.status_label.set_markup(
            f'<span foreground="{"red" if is_error else "green"}">{GLib.markup_escape_text(text)}</span>'
        )
        self.status_label.set_no_show_all(False)
        self.status_label.show()

    def refresh(self):
        self.enabled_check.handler_block_by_func(self.on_enabled_toggled)
        self.enabled_check.set_active(self.backend.read_enabled())
        self.enabled_check.handler_unblock_by_func(self.on_enabled_toggled)

        self.combo.handler_block_by_func(self.on_combo_changed)
        self.combo.remove_all()
        self.combo.append("default", t("pw.sound_standard"))
        for name in self.backend.list_history():
            self.combo.append(name, name)
        selected = self.backend.read_selected()
        self.combo.set_active_id(selected)
        if self.combo.get_active_id() != selected:
            # The previously-selected history entry no longer exists (e.g.
            # it got pruned) -- just reflect the standard chime as shown,
            # without touching what's actually installed as active.
            self.combo.set_active_id("default")
        self.combo.handler_unblock_by_func(self.on_combo_changed)

    def on_enabled_toggled(self, _checkbox):
        enabled = self.enabled_check.get_active()
        self.enabled_check.set_sensitive(False)
        threading.Thread(target=self._run_set_enabled, args=(enabled,), daemon=True).start()

    def _run_set_enabled(self, enabled):
        success, message = self.backend.set_enabled(enabled)
        GLib.idle_add(self._on_set_enabled_done, success, message, enabled)

    def _on_set_enabled_done(self, success, message, enabled):
        self.set_status(message, is_error=not success)
        self.enabled_check.set_sensitive(True)
        if not success:
            self.enabled_check.handler_block_by_func(self.on_enabled_toggled)
            self.enabled_check.set_active(not enabled)
            self.enabled_check.handler_unblock_by_func(self.on_enabled_toggled)
        return False

    def on_combo_changed(self, _combo):
        name = self.combo.get_active_id()
        if not name:
            return
        self.combo.set_sensitive(False)
        threading.Thread(target=self._run_select, args=(name,), daemon=True).start()

    def _run_select(self, name):
        success, message = self.backend.select_sound(name)
        GLib.idle_add(self._on_select_done, success, message)

    def _on_select_done(self, success, message):
        self.set_status(message, is_error=not success)
        self.combo.set_sensitive(True)
        if not success:
            self.refresh()
        return False

    def on_play_clicked(self, _button):
        # Always previews through the desktop audio stack (paplay), even
        # for the startup chime which actually plays via raw ALSA at boot
        # -- that's fine, this button is just "does this sound file sound
        # right", not a faithful boot-time simulation.
        subprocess.Popen(["paplay", self.backend.active_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def on_choose_file_clicked(self, _button):
        dialog = Gtk.FileChooserDialog(
            title=t("pw.sound_choose_file"),
            transient_for=self.parent_window,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons(
            t("pw.cancel"), Gtk.ResponseType.CANCEL,
            t("pw.sound_choose_file"), Gtk.ResponseType.OK,
        )
        file_filter = Gtk.FileFilter()
        file_filter.set_name(t("pw.sound_file_filter"))
        for pattern in ("*.wav", "*.mp3", "*.ogg"):
            file_filter.add_pattern(pattern)
        dialog.add_filter(file_filter)

        response = dialog.run()
        path = dialog.get_filename() if response == Gtk.ResponseType.OK else None
        dialog.destroy()

        if not path:
            return

        self.set_status(t("pw.sound_converting"), is_error=False)
        threading.Thread(target=self._run_import, args=(path,), daemon=True).start()

    def _run_import(self, src_path):
        tmp_wav, error = convert_to_wav(src_path)
        if tmp_wav is None:
            GLib.idle_add(self._on_import_done, False, error)
            return
        try:
            success, message = self.backend.import_sound(tmp_wav, os.path.basename(src_path))
        finally:
            try:
                os.remove(tmp_wav)
            except OSError:
                pass
        GLib.idle_add(self._on_import_done, success, message)

    def _on_import_done(self, success, message):
        self.set_status(message, is_error=not success)
        if success:
            self.refresh()
        return False


class PasswordWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title=t("pw.window_title"))
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
        self.notebook.append_page(Gtk.Box(), Gtk.Label(label=t("pw.boot_screen_tab")))
        self.notebook.append_page(Gtk.Box(), Gtk.Label(label=t("pw.sound_tab")))
        self.notebook.connect("switch-page", self.on_tab_switched)
        content.pack_start(self.notebook, False, False, 0)

        # The notebook above only supplies tab labels/switching; the actual
        # controls for each tab live in these sibling sections below it
        # (password tabs share one dynamically-relabelled section, same as
        # before this tab was added), toggled by on_tab_switched.
        self.password_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content.pack_start(self.password_section, False, False, 0)

        self.boot_name_section = self._build_boot_name_section()
        content.pack_start(self.boot_name_section, False, False, 0)

        self.sound_section = self._build_sound_section()
        content.pack_start(self.sound_section, False, False, 0)

        self.language_selector = Gtk.ComboBoxText()
        for code, name in LANGUAGES:
            self.language_selector.append(code, name)
        self.language_selector.set_active_id(detect_language())
        self.language_selector.connect("changed", self.on_language_changed)

        self.wordlist = load_wordlist(self.language_selector.get_active_id())

        self.description_label = Gtk.Label(label="", wrap=True, xalign=0)
        self.password_section.pack_start(self.description_label, False, False, 0)

        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        grid.set_hexpand(True)
        self.password_section.pack_start(grid, False, False, 0)

        self.current_label, self.current_entry = self._add_row(grid, 0, t("pw.current_password"))
        self._add_row_widgets(grid, 1, t("pw.new_password"))
        self.new_entry = self._last_entry
        self._add_row_widgets(grid, 2, t("pw.confirm_password"))
        self.confirm_entry = self._last_entry

        self.generate_button = Gtk.Button(label=t("pw.generate"))
        self.generate_button.connect("clicked", self.on_generate_clicked)
        grid.attach(self.generate_button, 2, 2, 1, 1)
        grid.attach(self.language_selector, 3, 2, 1, 1)

        self.mark_temp_checkbox = Gtk.CheckButton(label=t("pw.mark_temp_checkbox"))
        self.password_section.pack_start(self.mark_temp_checkbox, False, False, 0)

        self.status_label = Gtk.Label(label="", wrap=True, xalign=0)
        self.status_label.set_no_show_all(True)
        self.password_section.pack_start(self.status_label, False, False, 0)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        content.pack_start(button_box, False, False, 0)

        self.change_button = Gtk.Button(label=t("pw.change_password"))
        self.change_button.connect("clicked", self.on_change_clicked)
        button_box.pack_end(self.change_button, False, False, 0)

        self.save_boot_name_button = Gtk.Button(label=t("pw.save"))
        self.save_boot_name_button.connect("clicked", self.on_save_boot_name_clicked)
        button_box.pack_end(self.save_boot_name_button, False, False, 0)

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

    def _build_boot_name_section(self):
        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        description = Gtk.Label(label=t("pw.boot_name_desc"), wrap=True, xalign=0)
        section.pack_start(description, False, False, 0)

        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        grid.set_hexpand(True)
        section.pack_start(grid, False, False, 0)

        label = Gtk.Label(label=t("pw.boot_name_label"), xalign=0)
        self.boot_name_entry = Gtk.Entry(hexpand=True)
        self.boot_name_entry.set_width_chars(34)
        self.boot_name_entry.set_max_length(BOOT_NAME_MAX_LENGTH)
        self.boot_name_entry.set_activates_default(True)
        grid.attach(label, 0, 0, 1, 1)
        grid.attach(self.boot_name_entry, 1, 0, 1, 1)

        self.boot_name_status_label = Gtk.Label(label="", wrap=True, xalign=0)
        self.boot_name_status_label.set_no_show_all(True)
        section.pack_start(self.boot_name_status_label, False, False, 0)

        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        section.pack_start(separator, False, False, 4)

        self.bright_mode_check = Gtk.CheckButton(label=t("pw.boot_bright_mode_label"))
        self.bright_mode_check.connect("toggled", self.on_bright_mode_toggled)
        section.pack_start(self.bright_mode_check, False, False, 0)

        bright_mode_desc = Gtk.Label(label=t("pw.boot_bright_mode_desc"), wrap=True, xalign=0)
        section.pack_start(bright_mode_desc, False, False, 0)

        self.bright_mode_status_label = Gtk.Label(label="", wrap=True, xalign=0)
        self.bright_mode_status_label.set_no_show_all(True)
        section.pack_start(self.bright_mode_status_label, False, False, 0)

        return section

    def _build_sound_section(self):
        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        self.startup_chime = ChimeSection(
            BootChimeBackend(), t("pw.sound_startup_title"), t("pw.sound_startup_desc"), self
        )
        section.pack_start(self.startup_chime.widget, False, False, 0)

        section.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)

        self.shutdown_chime = ChimeSection(
            ShutdownChimeBackend(), t("pw.sound_shutdown_title"), t("pw.sound_shutdown_desc"), self
        )
        section.pack_start(self.shutdown_chime.widget, False, False, 0)

        return section

    def _apply_boot_name_tab(self):
        self.boot_name_entry.set_text(read_boot_name())
        self.boot_name_status_label.set_no_show_all(True)
        self.boot_name_status_label.hide()

        # Set without triggering on_bright_mode_toggled's save-on-toggle
        # behavior -- this is just reflecting the on-disk state, not a user
        # action to act on.
        self.bright_mode_check.handler_block_by_func(self.on_bright_mode_toggled)
        self.bright_mode_check.set_active(read_boot_bright_mode())
        self.bright_mode_check.handler_unblock_by_func(self.on_bright_mode_toggled)
        self.bright_mode_status_label.set_no_show_all(True)
        self.bright_mode_status_label.hide()

    def set_boot_name_status(self, text, is_error=True):
        self.boot_name_status_label.set_markup(
            f'<span foreground="{"red" if is_error else "green"}">{GLib.markup_escape_text(text)}</span>'
        )
        self.boot_name_status_label.set_no_show_all(False)
        self.boot_name_status_label.show()

    def on_save_boot_name_clicked(self, _button):
        name = self.boot_name_entry.get_text().strip()

        self.save_boot_name_button.set_sensitive(False)
        self.set_boot_name_status(
            t("pw.boot_name_waiting").format(seconds=estimate_boot_rebuild_seconds()),
            is_error=False,
        )

        threading.Thread(target=self._run_save_boot_name, args=(name,), daemon=True).start()

    def _run_save_boot_name(self, name):
        success, message = set_boot_name(name)
        GLib.idle_add(self._on_save_boot_name_done, success, message)

    def _on_save_boot_name_done(self, success, message):
        self.set_boot_name_status(message, is_error=not success)
        self.save_boot_name_button.set_sensitive(True)
        return False

    def set_bright_mode_status(self, text, is_error=True):
        self.bright_mode_status_label.set_markup(
            f'<span foreground="{"red" if is_error else "green"}">{GLib.markup_escape_text(text)}</span>'
        )
        self.bright_mode_status_label.set_no_show_all(False)
        self.bright_mode_status_label.show()

    def on_bright_mode_toggled(self, _checkbox):
        enabled = self.bright_mode_check.get_active()
        self.bright_mode_check.set_sensitive(False)
        self.set_bright_mode_status(
            t("pw.boot_name_waiting").format(seconds=estimate_boot_rebuild_seconds()),
            is_error=False,
        )
        threading.Thread(target=self._run_set_bright_mode, args=(enabled,), daemon=True).start()

    def _run_set_bright_mode(self, enabled):
        success, message = set_boot_bright_mode(enabled)
        GLib.idle_add(self._on_set_bright_mode_done, success, message, enabled)

    def _on_set_bright_mode_done(self, success, message, enabled):
        self.set_bright_mode_status(message, is_error=not success)
        self.bright_mode_check.set_sensitive(True)
        if not success:
            self.bright_mode_check.handler_block_by_func(self.on_bright_mode_toggled)
            self.bright_mode_check.set_active(not enabled)
            self.bright_mode_check.handler_unblock_by_func(self.on_bright_mode_toggled)
        return False

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
        tooltip = t("pw.hide_password") if visible else t("pw.show_password")
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
        self.set_status(t("pw.generated_passphrase"), is_error=False)

    def on_tab_switched(self, _notebook, _page, page_num):
        boot_screen_index = len(PASSWORD_ORDER)

        self.password_section.hide()
        self.boot_name_section.hide()
        self.sound_section.hide()
        self.change_button.hide()
        self.save_boot_name_button.hide()

        if page_num < boot_screen_index:
            self.password_section.show()
            self.change_button.show()
            self._apply_type(PASSWORD_ORDER[page_num])
        elif page_num == boot_screen_index:
            self.boot_name_section.show()
            self.save_boot_name_button.show()
            self._apply_boot_name_tab()
        else:
            self.sound_section.show()
            self.startup_chime.refresh()
            self.shutdown_chime.refresh()

    def _apply_type(self, type_key):
        self.active_type = type_key
        info = PASSWORD_TYPES[type_key]

        self.description_label.set_text(
            f"{info['description']}\n"
            + t("pw.recommended_format").format(
                word_count=info["word_count"], min_length=info["min_length"]
            )
        )

        self.current_entry.set_text("")
        self.new_entry.set_text("")
        self.confirm_entry.set_text("")
        self._set_entry_visibility(self.new_entry, False)
        self._set_entry_visibility(self.confirm_entry, False)
        self.status_label.set_no_show_all(True)
        self.status_label.hide()
        self.mark_temp_checkbox.set_active(False)

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
            self.set_status(t("pw.fill_all_fields"))
            return
        if not new:
            self.set_status(t("pw.fill_all_fields"))
            return
        if new != confirm:
            self.set_status(t("pw.mismatch"))
            return
        if len(new) < info["min_length"]:
            self.set_status(t("pw.too_short").format(min_length=info["min_length"]))
            return

        if not self._confirm_written_down(info["title"], new):
            return

        self.change_button.set_sensitive(False)
        self.set_status(t("pw.waiting_auth"), is_error=False)

        # Run on a background thread so the pkexec prompt doesn't freeze the window.
        threading.Thread(
            target=self._run_change,
            args=(info["change"], current, new, self.active_type, self.mark_temp_checkbox.get_active()),
            daemon=True,
        ).start()

    def _confirm_written_down(self, title, new_password):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.YES_NO,
            text=t("pw.confirm_written_title"),
        )
        dialog.format_secondary_text(
            t("pw.confirm_written_secondary").format(title=title, password=new_password)
        )
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.YES

    def _run_change(self, change_fn, current, new, ptype, mark_temp):
        success, message = change_fn(current, new)
        if success and mark_temp:
            rec_ok, rec_error = record_as_temporary(ptype, new)
            if not rec_ok:
                message = f"{message}\n\n{t('pw.mark_temp_failed')} {rec_error}"
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
    win.show_all()
    # show_all() re-shows everything hidden during __init__ (e.g. the
    # boot-name section), so tab visibility has to be reapplied afterwards.
    win.on_tab_switched(win.notebook, None, win.notebook.get_current_page())
    Gtk.main()


if __name__ == "__main__":
    main()
