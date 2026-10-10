"""Shared dictation core: config, recording, transcription, typing."""
import json
import logging
import logging.handlers
import subprocess
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd
import sys
from pynput import keyboard

from i18n import _

SAMPLE_RATE = 16000
CHANNELS = 1


CONFIG_DIR = Path.home() / ".config" / "dictate"
CONFIG_PATH = CONFIG_DIR / "config.json"
LOG_PATH = Path.home() / ".local" / "state" / "dictate" / "dictate.log"

log = logging.getLogger("dictate")


def setup_logging():
    """Every recording leaves one line in LOG_PATH, so a dictation that went
    nowhere can be traced afterwards. Never logs transcribed text."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    h = logging.handlers.RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=2)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)

KEY_MAP = {f"f{i}": {getattr(keyboard.Key, f"f{i}")} for i in range(1, 13)}
KEY_MAP.update({
    "pause":       {keyboard.Key.pause},
    "scroll_lock": {keyboard.Key.scroll_lock},
    "insert":      {keyboard.Key.insert},
    "home":        {keyboard.Key.home},
    "end":         {keyboard.Key.end},
    "page_up":     {keyboard.Key.page_up},
    "page_down":   {keyboard.Key.page_down},
    "caps_lock":   {keyboard.Key.caps_lock},
    "ctrl":        {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r},
    "ctrl_l":      {keyboard.Key.ctrl_l},
    "ctrl_r":      {keyboard.Key.ctrl_r},
    "alt":         {keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r},
    "alt_l":       {keyboard.Key.alt_l},
    "alt_r":       {keyboard.Key.alt_r, keyboard.Key.alt_gr},
    "shift":       {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r},
    "super":       {keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r},
    # Mouse-side buttons. Sentinels are tuples emitted by evdev_listener;
    # pynput won't see these (mouse events go through a separate listener) —
    # so these hotkeys only work when the evdev backend is active.
    "mouse_back":    {("mouse", "back")},
    "mouse_forward": {("mouse", "forward")},
    "mouse_side":    {("mouse", "side")},
    "mouse_extra":   {("mouse", "extra")},
    "mouse_task":    {("mouse", "task")},
})

DEFAULT_CONFIG = {
    "mode":                  "ptt",
    "key":                   "f9",
    "model":                 "nemo-de-fastconformer-int8",  # local_stt.MODELS key
    "threshold":             0.0,
    "local_stt_num_threads": 4,    # sherpa-onnx CPU thread count
    "start_hidden":          True,    # start as a panel icon only, no window (needs a tray)
    "language":              "auto",  # UI language: auto (desktop locale), en, de; no Settings field, provisioning sets the locale
    "local_stt_idle_minutes": 5,   # unload the model after this long idle when RAM is short (0 = keep loaded)
}


AUTOSTART_PATH = Path.home() / ".config" / "autostart" / "dictate.desktop"


def autostart_enabled():
    return AUTOSTART_PATH.exists()


def set_autostart(on):
    """Start Dictate at login (XDG autostart entry)."""
    if not on:
        AUTOSTART_PATH.unlink(missing_ok=True)
        return
    gui = Path(__file__).resolve().with_name("gui.py")
    AUTOSTART_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUTOSTART_PATH.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Dictate\n"
        "Comment=Voice dictation to keyboard\n"
        f"Exec={sys.executable} {gui}\n"
        "Icon=audio-input-microphone\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )


def model_ready():
    """True once the selected speech model has been downloaded."""
    try:
        import local_stt
        return local_stt.model_installed()
    except ImportError:
        return False


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text()))
        except Exception:
            pass
    # Settings from versions that also offered cloud providers are dropped.
    for k in ("provider", "api_key", "openai_api_key", "yorik_url", "yorik_token"):
        cfg.pop(k, None)
    try:
        import local_stt
        cfg["model"] = local_stt.select_model(cfg.get("model"))
    except ImportError:
        pass
    return cfg


def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    try:
        CONFIG_PATH.chmod(0o600)
    except Exception:
        pass


def notify(msg, urgency="normal", timeout_ms=1500):
    try:
        subprocess.run(
            ["notify-send", "-u", urgency, "-t", str(timeout_ms), "Dictate", msg],
            check=False,
        )
    except FileNotFoundError:
        pass


def notify_sticky(msg):
    """Show a notification that stays until close_notification(); returns its
    id, or None if it could not be shown."""
    try:
        r = subprocess.run(["notify-send", "-p", "-t", "0", "Dictate", msg],
                           check=False, capture_output=True, text=True)
        return int(r.stdout.strip())
    except (FileNotFoundError, ValueError):
        return None


def close_notification(nid):
    if nid is None:
        return
    try:
        subprocess.run(
            ["gdbus", "call", "--session", "--dest", "org.freedesktop.Notifications",
             "--object-path", "/org/freedesktop/Notifications",
             "--method", "org.freedesktop.Notifications.CloseNotification", str(nid)],
            check=False, capture_output=True)
    except FileNotFoundError:
        pass


def _xdotool_segments(text):
    """Split text into (segment, is_special) pieces for xdotool.

    Non-ASCII characters (é, ç, ü, ...) need xdotool to remap a spare key or
    use a modifier; typed with no delay, apps read the key before that lands
    and drop or mangle the character. So plain runs go out at
    full speed and each such character is typed on its own, slowly.
    """
    segs, run = [], ""
    for c in text:
        if ord(c) < 128:
            run += c
            continue
        if run:
            segs.append((run, False))
            run = ""
        segs.append((c, True))
    if run:
        segs.append((run, False))
    return segs


def _xdotool_type(text):
    import time
    r = None
    for seg, special in _xdotool_segments(text):
        if not special:
            r = subprocess.run(["xdotool", "type", "--delay", "0", "--", seg], check=False)
        else:
            time.sleep(0.05)  # let clients settle before the keymap changes
            if seg.isupper():
                # A remapped key carries a single keysym, which clients read as
                # its lowercase form unless Shift is held (É would come out é).
                r = subprocess.run(["xdotool", "keydown", "shift"], check=False)
                time.sleep(0.03)
                r = subprocess.run(["xdotool", "key", "--delay", "25", f"U{ord(seg):04X}"], check=False)
                time.sleep(0.03)
                subprocess.run(["xdotool", "keyup", "shift"], check=False)
            else:
                r = subprocess.run(["xdotool", "type", "--delay", "25", "--", seg], check=False)
            time.sleep(0.05)  # let clients pick up the restored keymap
        if r.returncode != 0:
            return r
    return r


def type_text(text):
    if not text:
        return
    # xdotool respects the active XKB layout (correct German umlauts, no y/z
    # swap on QWERTZ). Prefer it on X11 where it actually works. On Wayland,
    # native windows ignore XTEST so we must fall back to ydotool, which
    # writes raw US-QWERTY scancodes via /dev/uinput — layout-agnostic and
    # therefore wrong for non-US keyboards, but there is no better option
    # for global typing into native Wayland windows today.
    import os
    if os.name == "nt" or sys.platform == "darwin":
        # Windows / macOS: no xdotool or ydotool; pynput types through the
        # OS input API and respects the active keyboard layout.
        keyboard.Controller().type(text)
        return
    on_x11 = os.environ.get("XDG_SESSION_TYPE") == "x11"
    tools = ["xdotool", "ydotool"] if on_x11 else ["ydotool", "xdotool"]
    for tool in tools:
        try:
            if tool == "xdotool":
                r = _xdotool_type(text)
            else:
                r = subprocess.run(
                    ["ydotool", "type", "--key-delay", "0", "--", text],
                    check=False,
                    stderr=subprocess.DEVNULL,
                )
            if r.returncode != 0:
                log.error("%s exited with %s — text not typed", tool, r.returncode)
                notify(_("Typing failed ({tool} exit {code})").format(tool=tool, code=r.returncode), urgency="critical", timeout_ms=5000)
            return
        except FileNotFoundError:
            continue


class Recorder:
    """Each recording is a "take" (stream + its frames). detach() hands the
    current take to the caller without touching PipeWire, so a new start()
    can never collide with a take that is still being finished on a worker
    thread (trailing buffer + slow PipeWire close)."""

    def __init__(self):
        self._take = None
        self.lock = threading.Lock()

    @property
    def recording(self):
        return self._take is not None

    def start(self):
        with self.lock:
            if self._take is not None:
                return
            frames = []

            def callback(indata, n, time_info, status):
                frames.append(indata.copy())

            stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                callback=callback,
            )
            stream.start()
            self._take = (stream, frames)

    def detach(self):
        """Non-blocking: give up the current take (or None). Safe on the GUI thread."""
        with self.lock:
            take, self._take = self._take, None
            return take

    @staticmethod
    def finish(take):
        """Close a detached take and return its audio, or None if it has none.
        Blocks for hundreds of ms on PipeWire close — call from a worker."""
        if take is None:
            return None
        stream, frames = take
        try:
            stream.stop()
            stream.close()
        except Exception:
            # A vanished mic must not lose what was already captured.
            log.exception("closing input stream failed")
        if not frames:
            return None
        return np.concatenate(frames, axis=0)

    def stop(self):
        return self.finish(self.detach())


def transcribe(audio, cfg):
    import local_stt
    threads = int(cfg.get("local_stt_num_threads", local_stt.DEFAULT_THREADS))
    idle_s = 60 * float(cfg.get("local_stt_idle_minutes", 5))
    text = local_stt.get_recognizer(num_threads=threads, idle_s=idle_s).transcribe(audio)
    # The model ends every piece with a full stop, even a lone word or number.
    if text.endswith(".") and len(text.split()) == 1:
        text = text[:-1]
    return text
