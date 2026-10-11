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

# A hotkey press shorter than this is an accidental tap, not a dictation (push-to-talk).
MIN_HOLD_S = 0.5

DEFAULT_CONFIG = {
    "mode":                  "ptt",
    "key":                   "f9",
    "model":                 "nemo-de-fastconformer-int8",  # local_stt.MODELS key
    "local_stt_num_threads": 4,    # sherpa-onnx CPU thread count
    "hotkey_enabled":        True,    # tray menu switch for the dictation hotkey
    "dictation_notifications": True,   # notification while dictating: Speak now / Transcribing
    "language":              "auto",  # UI language: auto (desktop locale), en, de; no Settings field, provisioning sets the locale
    "input_source":          "",     # PulseAudio source name; empty = automatic
    "trim_silence":          True,   # cut pauses before decoding (local_stt silence trimming); no Settings field
    "recording_meter":       True,   # small level meter while recording (replaces the "Speak now" notification)
    "vad_highpass":          True,   # speech detection ignores hum below 150 Hz (mains buzz hides quiet speech from it)
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
    for k in ("provider", "api_key", "openai_api_key", "yorik_url", "yorik_token", "threshold", "start_hidden"):
        cfg.pop(k, None)
    try:
        import local_stt
        cfg["model"] = local_stt.select_model(cfg.get("model"))
        local_stt.set_trim(cfg.get("trim_silence", True))
        local_stt.set_vad_highpass(cfg.get("vad_highpass", True))
    except ImportError:
        pass
    set_input_source(cfg.get("input_source", ""))
    return cfg


def save_config(cfg):
    set_input_source(cfg.get("input_source", ""))
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


def _gv_str(s):
    """A Python string as a GVariant text-format string literal."""
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def notify_sticky(msg, replace_id=None, body=None, action=None):
    """Show a notification that stays until close_notification(); returns its
    id, or None if it could not be shown. With replace_id, that notification
    changes its text in place. With action, clicking the notification sends
    the daemon's ActionInvoked signal for this id with the key "default".
    (notify-send -A would do that too, but it implies --wait and blocks until
    the notification is gone, which would stall the caller.)"""
    if action:
        try:
            r = subprocess.run(
                ["gdbus", "call", "--session", "--dest", "org.freedesktop.Notifications",
                 "--object-path", "/org/freedesktop/Notifications",
                 "--method", "org.freedesktop.Notifications.Notify",
                 "Dictate", str(replace_id or 0), "", _gv_str(msg), _gv_str(body or ""),
                 "[" + _gv_str("default") + "," + _gv_str(action) + "]", "@a{sv} {}", "0"],
                check=False, capture_output=True, text=True, timeout=5)
            return int(r.stdout.split()[1].rstrip(",)"))
        except (FileNotFoundError, ValueError, IndexError, subprocess.TimeoutExpired):
            return None
    # The text is the summary; without a body there is no "Dictate" heading above it.
    cmd = ["notify-send", "-a", "Dictate", "-p", "-t", "0"]
    if replace_id is not None:
        cmd += ["-r", str(replace_id)]
    cmd.append(msg)
    if body:
        cmd.append(body)
    try:
        r = subprocess.run(cmd, check=False, capture_output=True, text=True)
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


def _on_x11():
    import os
    return os.environ.get("XDG_SESSION_TYPE") == "x11"


def active_window():
    """ID of the focused top-level window, "" if there is none, None if it
    cannot be asked (not X11, xdotool missing)."""
    if not _on_x11():
        return None
    try:
        r = subprocess.run(["xdotool", "getactivewindow"], capture_output=True, text=True, timeout=2)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else ""


def paste_target():
    """Where a dictation started now should be typed. Returns the focused
    window's ID, or "" when that is nowhere to type (no window has focus, or
    the focus is on the desktop or a panel). None means it cannot tell, and
    typing then goes to whatever has focus, as before."""
    wid = active_window()
    if not wid:
        return wid
    try:
        p = subprocess.run(["xprop", "-id", wid, "_NET_WM_WINDOW_TYPE", "WM_CLASS"],
                           capture_output=True, text=True, timeout=2).stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return wid
    if any(t in p for t in ("_NET_WM_WINDOW_TYPE_DESKTOP", "_NET_WM_WINDOW_TYPE_DOCK")):
        return ""
    if any(c in p.lower() for c in ('"xfdesktop"', '"xfce4-panel"')):
        return ""
    return wid


def focus_window(wid):
    """Bring a remembered window back into focus. False if it is gone or
    refuses, in which case nothing may be typed."""
    if active_window() == wid:
        return True
    try:
        r = subprocess.run(["xdotool", "windowactivate", "--sync", wid],
                           capture_output=True, timeout=3)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0 and active_window() == wid


def type_text(text, target=None):
    """Type into the focused window. With a target window ID, first bring that
    window back to the front and type only if it really has focus; returns
    False when it could not be reached, so the caller can keep the text."""
    if not text:
        return True
    if target and not focus_window(target):
        log.warning("window %s is gone or would not take focus, text not typed", target)
        return False
    # xdotool respects the active XKB layout (correct German umlauts, no y/z
    # swap on QWERTZ). Prefer it on X11 where it actually works. On Wayland,
    # native windows ignore XTEST so we must fall back to ydotool, which
    # writes raw US-QWERTY scancodes via /dev/uinput — layout-agnostic and
    # therefore wrong for non-US keyboards, but there is no better option
    # for global typing into native Wayland windows today.
    import os
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
            return r.returncode == 0
        except FileNotFoundError:
            continue
    return False


_input_source = ""


def set_input_source(name):
    """The microphone chosen in Settings; empty means automatic."""
    global _input_source
    _input_source = name or ""


def list_input_sources():
    """Real microphones PulseAudio knows, as [(source name, description)].
    Monitors (what the speakers play) are left out. Empty without pactl."""
    import os
    try:
        out = subprocess.run(["pactl", "list", "sources"], capture_output=True, text=True,
                             timeout=3, env={**os.environ, "LC_ALL": "C"}).stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    sources, name = [], None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("Name:"):
            name = line[5:].strip()
        elif line.startswith("Description:") and name:
            if not name.endswith(".monitor"):
                sources.append((name, line[12:].strip()))
            name = None
    return sources


def _select_microphone():
    """Point PulseAudio clients in this process at the right microphone: the
    one chosen in Settings, else (automatic) the first real input when the
    default source is a monitor. PulseAudio makes the speaker monitor the
    default when the only microphone port is flagged unplugged (laptop jack
    detection), and a monitor records silence. Does nothing on a healthy
    automatic setup, or without pactl."""
    import os
    os.environ.pop("PULSE_SOURCE", None)
    try:
        sources = [n for n, _d in list_input_sources()]
        if _input_source:
            if _input_source in sources:
                os.environ["PULSE_SOURCE"] = _input_source
                return
            log.info("chosen microphone %s is not available, using automatic", _input_source)
        default = subprocess.run(["pactl", "get-default-source"], capture_output=True, text=True,
                                 timeout=2, env={**os.environ, "LC_ALL": "C"}).stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return
    if default.endswith(".monitor") and sources:
        os.environ["PULSE_SOURCE"] = sources[0]
        log.info("default source %s is a monitor, recording from %s", default, sources[0])


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

    def start(self, tap=None):
        """tap: optional callable that gets every audio block (int16), from the audio thread."""
        with self.lock:
            if self._take is not None:
                return
            frames = []
            _select_microphone()
            vad = None
            try:
                import local_stt
                vad = local_stt.StreamingVad() if local_stt.trim_active() else None
            except Exception:
                log.exception("could not start the streaming voice detector")

            def callback(indata, n, time_info, status):
                block = indata.copy()
                frames.append(block)
                if vad is not None:
                    vad.feed(block)
                if tap is not None:
                    tap(block)

            stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                callback=callback,
            )
            stream.start()
            self._take = (stream, frames, vad)

    def detach(self):
        """Non-blocking: give up the current take (or None). Safe on the GUI thread."""
        with self.lock:
            take, self._take = self._take, None
            return take

    @staticmethod
    def finish(take):
        """Close a detached take and return its audio, or None if it has none.
        Blocks for hundreds of ms on PipeWire close — call from a worker."""
        return Recorder.finish_take(take)[0]

    @staticmethod
    def finish_take(take):
        """Like finish(), but returns (audio, speech mask). The mask is what the
        streaming voice detector found while recording, or None when the
        transcription has to find the speech itself."""
        if take is None:
            return None, None
        stream, frames, vad = take
        try:
            stream.stop()
            stream.close()
        except Exception:
            # A vanished mic must not lose what was already captured.
            log.exception("closing input stream failed")
        audio = np.concatenate(frames, axis=0) if frames else None
        mask = vad.finish(len(audio) if audio is not None else 0) if vad is not None else None
        return audio, mask

    def stop(self):
        return self.finish(self.detach())


def transcribe(audio, cfg, speech=None):
    import local_stt
    threads = int(cfg.get("local_stt_num_threads", local_stt.DEFAULT_THREADS))
    idle_s = 60 * float(cfg.get("local_stt_idle_minutes", 5))
    text = local_stt.get_recognizer(num_threads=threads, idle_s=idle_s).transcribe(audio, speech)
    # The model ends every piece with a full stop, even a lone word or number.
    if text.endswith(".") and len(text.split()) == 1:
        text = text[:-1]
    return text
