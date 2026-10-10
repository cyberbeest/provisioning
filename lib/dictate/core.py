"""Shared dictation core: config, recording, transcription, typing."""
import io
import json
import logging
import logging.handlers
import subprocess
import threading
import wave
from pathlib import Path

import numpy as np
import requests
import sounddevice as sd
import sys
from pynput import keyboard

from i18n import _

SAMPLE_RATE = 16000
CHANNELS = 1

PROVIDERS = {
    "groq": {
        "label":         "Groq",
        "url":           "https://api.groq.com/openai/v1/audio/transcriptions",
        "models_url":    "https://api.groq.com/openai/v1/models",
        "key_field":     "api_key",
        "key_prefix":    "gsk_",
        "default_model": "whisper-large-v3-turbo",
        "models": [
            ("whisper-large-v3-turbo (fastest)",   "whisper-large-v3-turbo"),
            ("whisper-large-v3 (most accurate)",    "whisper-large-v3"),
        ],
        "is_local":      False,
    },
    "openai": {
        "label":         "OpenAI",
        "url":           "https://api.openai.com/v1/audio/transcriptions",
        "models_url":    "https://api.openai.com/v1/models",
        "key_field":     "openai_api_key",
        "key_prefix":    "sk-",
        "default_model": "gpt-4o-mini-transcribe",
        "models": [
            ("gpt-4o-mini-transcribe (fast · cheap)", "gpt-4o-mini-transcribe"),
            ("gpt-4o-transcribe (best quality)",      "gpt-4o-transcribe"),
            ("whisper-1 (classic)",                   "whisper-1"),
        ],
        "is_local":      False,
    },
    "yorik": {
        "label":         "Yorik (home server)",
        "url":           "http://127.0.0.1:8000/v1/audio/transcriptions",
        "models_url":    None,
        "key_field":     "yorik_token",
        "key_prefix":    "yk_",
        "default_model": "parakeet",
        "models": [("Yorik's configured engine (Parakeet, CPU)", "parakeet")],
        "is_local":      False,
        "url_field":     "yorik_url",   # base URL, editable in Settings
    },
    "parakeet_local": {
        "label":         "Local (Parakeet DE, CPU offline)",
        "url":           None,
        "models_url":    None,
        "key_field":     None,
        "key_prefix":    None,
        "default_model": "parakeet-primeline-int8",
        "models": [("parakeet-primeline (German, int8)", "parakeet-primeline-int8")],
        "is_local":      True,
    },
}

# Backward-compat aliases used elsewhere in the codebase.
DEFAULT_PROVIDER = "groq"
DEFAULT_MODEL    = PROVIDERS[DEFAULT_PROVIDER]["default_model"]
GROQ_URL         = PROVIDERS["groq"]["url"]
GROQ_MODELS_URL  = PROVIDERS["groq"]["models_url"]

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
    "provider":              DEFAULT_PROVIDER,
    "api_key":               "",   # Groq key (kept name for backward compat)
    "openai_api_key":        "",   # OpenAI key
    "mode":                  "ptt",
    "key":                   "f9",
    "model":                 DEFAULT_MODEL,
    "threshold":             0.0,
    "local_stt_num_threads": 4,    # sherpa-onnx CPU thread count for parakeet_local
    "start_hidden":          True,    # start as a panel icon only, no window (needs a tray)
    "language":              "auto",  # UI language: auto (desktop locale), en, de
    "local_stt_idle_minutes": 5,   # unload the local model after this long idle (0 = keep loaded)
    "yorik_url":             "http://127.0.0.1:8000",  # Yorik base URL (provider "yorik")
    "yorik_token":           "",   # personal API token from Yorik Settings → API tokens
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


def provider_url(cfg, p):
    """Endpoint URL for an HTTP provider; Yorik's comes from the config."""
    if p.get("url_field"):
        base = (cfg.get(p["url_field"]) or "").strip().rstrip("/")
        if base:
            return base + "/v1/audio/transcriptions"
    return p["url"]


def provider_key(cfg):
    """Return a truthy value iff the selected provider is ready to use.

    HTTP providers need an API key. The local provider is 'ready' when the
    ONNX model files have been downloaded — no key, no network.
    """
    provider = cfg.get("provider", DEFAULT_PROVIDER)
    p = PROVIDERS.get(provider, PROVIDERS[DEFAULT_PROVIDER])
    if p.get("is_local"):
        try:
            import local_stt
            return "installed" if local_stt.model_installed() else ""
        except ImportError:
            return ""
    return cfg.get(p["key_field"], "")


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text()))
        except Exception:
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


def to_wav_bytes(audio):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())
    buf.seek(0)
    return buf


FAILED_DIR = LOG_PATH.parent / "failed"
FAILED_KEEP = 3


def keep_failed_audio(audio):
    """Save a recording that held sound but came back empty, so the failure
    can be replayed. Only the newest FAILED_KEEP files are kept."""
    try:
        import time
        FAILED_DIR.mkdir(parents=True, exist_ok=True)
        path = FAILED_DIR / time.strftime("%Y%m%d-%H%M%S.wav")
        path.write_bytes(to_wav_bytes(audio).getvalue())
        for old in sorted(FAILED_DIR.glob("*.wav"))[:-FAILED_KEEP]:
            old.unlink()
        log.info("kept failed recording as %s", path)
    except Exception:
        log.exception("could not keep failed recording")


def transcribe(audio, cfg):
    provider = cfg.get("provider", DEFAULT_PROVIDER)
    p = PROVIDERS.get(provider, PROVIDERS[DEFAULT_PROVIDER])
    if p.get("is_local"):
        import local_stt
        threads = int(cfg.get("local_stt_num_threads", local_stt.DEFAULT_THREADS))
        idle_s = 60 * float(cfg.get("local_stt_idle_minutes", 5))
        text = local_stt.get_recognizer(num_threads=threads, idle_s=idle_s).transcribe(audio)
        # The model ends every piece with a full stop, even a lone word or number.
        if text.endswith(".") and len(text.split()) == 1:
            text = text[:-1]
        return text
    # HTTP providers
    key = cfg.get(p["key_field"], "")
    model = cfg.get("model") or p["default_model"]
    wav = to_wav_bytes(audio)
    files = {"file": ("audio.wav", wav, "audio/wav")}
    data = {"model": model, "response_format": "text"}
    headers = {"Authorization": f"Bearer {key}"}
    r = requests.post(provider_url(cfg, p), files=files, data=data, headers=headers, timeout=30)
    r.raise_for_status()
    return r.text.strip()


def test_api_key(api_key, provider=DEFAULT_PROVIDER, cfg=None):
    p = PROVIDERS.get(provider, PROVIDERS[DEFAULT_PROVIDER])
    if provider == "yorik":
        # A token is valid when Yorik lists the caller's tokens with it.
        base = ((cfg or {}).get("yorik_url") or DEFAULT_CONFIG["yorik_url"]).strip().rstrip("/")
        try:
            r = requests.get(base + "/api/tokens", headers={"Authorization": f"Bearer {api_key}"}, timeout=10)
            return r.status_code == 200
        except Exception:
            return False
    if p.get("is_local") or not p.get("models_url"):
        return False  # no key to test — caller should not have called this
    try:
        r = requests.get(
            p["models_url"],
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=5,
        )
        return r.status_code == 200
    except Exception:
        return False
