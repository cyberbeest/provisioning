"""Shared dictation core: config, recording, transcription, typing."""
import json
import re
import logging
import logging.handlers
import os
import subprocess
import threading
import time
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
# Holding the Windows key this long starts a dictation (a shorter press just opens the menu).
SUPER_HOLD_S = 0.3

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
    "apply_corrections":     True,   # replace words by the learned corrections (see "Learned corrections")
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


def active_window_center():
    """(x, y) of the centre of the focused window, or None if it cannot be told."""
    wid = active_window()
    if not wid:
        return None
    try:
        out = subprocess.run(["xdotool", "getwindowgeometry", "--shell", wid],
                             capture_output=True, text=True, timeout=2).stdout
        v = dict(l.split("=", 1) for l in out.split() if "=" in l)
        return int(v["X"]) + int(v["WIDTH"]) // 2, int(v["Y"]) + int(v["HEIGHT"]) // 2
    except (FileNotFoundError, subprocess.TimeoutExpired, KeyError, ValueError):
        return None


WHISKER = "gowhisker"   # paste target: the Go panel's menu, whose search box takes the text


def _gopanel_ask(cmd):
    """Reply of the Go panel's control socket, "" if it does not run."""
    import socket
    path = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "gopanel.sock")
    if not os.path.exists(path):
        return ""
    try:
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(0.5)
            s.connect(path)
            s.sendall(cmd.encode() + b"\n")
            return s.recv(64).decode().strip()
    except OSError:
        return ""


def whisker_open():
    return _gopanel_ask("whisker?") == "open"


def open_whisker_for_hold():
    """Hold-Windows-key dictation: open the Go panel's menu now, so the text lands in its
    search box, and tell cyberbeest-whisker-key.sh to skip the shortcut that fires on release
    (it would toggle the menu shut again)."""
    if whisker_open():
        return
    marker = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "dictate-super-hold")
    try:
        open(marker, "w").close()
    except OSError:
        pass
    _gopanel_ask("menu")
    for _ in range(20):
        if whisker_open():
            return
        time.sleep(0.05)


def paste_target():
    """Where a dictation started now should be typed. Returns the focused
    window's ID, WHISKER when the Go panel's menu is open, or "" when that is nowhere to type (no window has focus, or
    the focus is on the desktop or a panel). None means it cannot tell, and
    typing then goes to whatever has focus, as before."""
    if whisker_open():
        return WHISKER
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


def dismiss_panel_popups():
    """Ask the Go panel (if it runs) to close any open menu or popup. Its popups hold a
    keyboard grab that swallows XTEST keystrokes, so text meant for the window the
    dictation started in would be typed into the popup's search box instead."""
    import os
    import socket
    path = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "gopanel.sock")
    if not os.path.exists(path):
        return
    try:
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(0.5)
            s.connect(path)
            s.sendall(b"dismiss\n")
            s.recv(16)
        time.sleep(0.15)  # let the panel release its grab before we type
    except OSError:
        pass


def type_text(text, target=None):
    """Type into the focused window. With a target window ID, first bring that
    window back to the front and type only if it really has focus; returns
    False when it could not be reached, so the caller can keep the text."""
    if not text:
        return True
    if target == WHISKER:
        # The menu holds the keyboard grab, so XTEST keys land in its search box. If it was
        # closed meanwhile, the keys would hit whatever has focus: keep the text instead.
        if not whisker_open():
            log.warning("the menu was closed, text not typed")
            return False
        target = None
    else:
        dismiss_panel_popups()
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
                notify(_("Typing failed ({tool} exit {code})").format(tool=tool, code=r.returncode), urgency="normal", timeout_ms=5000)   # critical never expires
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


# The last take, kept as a WAV to judge the microphone by ear (menu "Replay last
# recording", `gui.py --replay`). It lives in the runtime directory: tmpfs, private
# to the user, gone at logout or reboot, and only ever the latest one.
LAST_CLIP = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "dictate-last-clip.wav"
_STAMPS = ("enter", "mic_selected", "opened", "started", "first_block", "last_block", "release")
_replay = None   # the running paplay, if any


LAST_CLIP_INFO = LAST_CLIP.with_suffix(".json")


def save_last_clip(audio, timing=None, speech=None):
    """Keep `audio` (int16 mono, SAMPLE_RATE) as the last clip, replacing the previous one.
    Next to it goes a small JSON file for the clip viewer: the take's timing stamps
    (seconds since the key press / click) and the streamed speech mask, if there was one."""
    import wave
    tmp = LAST_CLIP.with_suffix(".tmp")
    try:
        info = {"sample_rate": SAMPLE_RATE, "samples": int(len(audio))}
        if timing:
            t0 = timing.get("requested", timing.get("enter", 0.0))
            info["timing"] = {k: (round(v - t0, 4) if k in _STAMPS else v) for k, v in timing.items() if k != "requested"}
        if speech is not None:
            edges = np.diff(np.concatenate(([0], np.asarray(speech).astype(np.int8), [0])))
            info["streamed_mask_runs"] = [[int(a), int(b)] for a, b in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1))]
        itmp = LAST_CLIP_INFO.with_suffix(".tmp")
        fd = os.open(itmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(info, f)
        os.replace(itmp, LAST_CLIP_INFO)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f, wave.open(f, "wb") as w:
            w.setnchannels(CHANNELS)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(np.ascontiguousarray(audio, dtype="<i2").tobytes())
        os.replace(tmp, LAST_CLIP)
    except OSError:
        log.exception("could not keep the last clip")


def replay_last_clip(wait=False):
    """Play the last clip through PulseAudio, replacing a replay still running.
    Returns False when there is no clip (or no paplay)."""
    global _replay
    if not LAST_CLIP.exists():
        return False
    if _replay is not None and _replay.poll() is None:
        _replay.terminate()
    try:
        _replay = subprocess.Popen(["paplay", str(LAST_CLIP)])
    except FileNotFoundError:
        return False
    if wait:
        _replay.wait()
    return True


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


STREAM_CLOSE_TIMEOUT_S = 3.0   # a healthy stop()+close() takes hundreds of ms
FIRST_FRAME_TIMEOUT_S = 0.5    # a healthy stream delivers a block every ~5-30 ms; this long without one is a stall
WATCHDOG_MAX_S = 600.0         # a take is never watched longer than this


def _stall_snapshot():
    """One line of machine state for the log when the microphone stalls, to find out what the stalls have in common."""
    def read(path, default="?"):
        try:
            return Path(path).read_text().strip()
        except OSError:
            return default
    def pcm_status():
        st = {}
        for line in read("/proc/asound/card0/pcm0c/sub0/status", "").splitlines():
            k, _sep, v = line.partition(":")
            st[k.strip()] = v.strip()
        return st
    status = pcm_status()
    time.sleep(0.25)
    # frozen = the driver/codec stopped capturing; moving = the hardware runs and PulseAudio/ALSA reading is stuck
    moving = "?" if "hw_ptr" not in status else ("yes" if pcm_status().get("hw_ptr") != status["hw_ptr"] else "NO (frozen)")
    temps = []
    for z in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
        t = read(z / "temp", "")
        if t.isdigit():
            temps.append("%s=%d" % (read(z / "type"), int(t) // 1000))
    meminfo = {l.split(":")[0]: l.split()[1] for l in read("/proc/meminfo", "").splitlines() if ":" in l}
    return ("pcm %s hw_ptr=%s avail=%s hw_ptr moving: %s | audio device runtime pm: %s/%s | load %s | avail mem %s MB | %s" % (
        status.get("state", "closed"), status.get("hw_ptr", "?"), status.get("avail", "?"), moving,
        read("/sys/bus/pci/devices/0000:00:0e.0/power/control"), read("/sys/bus/pci/devices/0000:00:0e.0/power/runtime_status"),
        read("/proc/loadavg").split(" ")[0], int(meminfo.get("MemAvailable", "0")) // 1024, " ".join(temps)))


def _heal_silent_microphone(frames, source):
    """Watchdog for one take. The laptop's SOF/es8336 capture can stall (the PCM
    stays RUNNING but its pointer freezes, the source latency grows by the
    second), at the start of a take or in the middle of one. Then no more audio
    arrives and PortAudio's stop() hangs (seen 2026-10-13: one take got 3.9 s of
    a 10 s dictation). Suspending and resuming the source makes PulseAudio
    reopen the device, and the stream already attached to it carries on, so a
    nudge a second after the audio stops usually saves the rest of the take.
    `source` is the chosen source name, or None for the default."""
    tm = frames.timing
    nudges = 0
    deadline = time.monotonic() + WATCHDOG_MAX_S
    time.sleep(FIRST_FRAME_TIMEOUT_S)
    while not frames.closed and nudges < 3 and time.monotonic() < deadline:
        last = tm.get("last_block")
        stalled = (not frames) if last is None else time.monotonic() - last > FIRST_FRAME_TIMEOUT_S
        if not stalled:
            time.sleep(0.3)
            continue
        nudges += 1
        try:
            name = source or subprocess.run(["pactl", "get-default-source"], capture_output=True, text=True,
                                            timeout=2, env={**os.environ, "LC_ALL": "C"}).stdout.strip()
            if not name:
                return
            log.warning("microphone %s delivered no audio for %.1fs (%d blocks, %.1fs into the take), restarting it",
                        name, FIRST_FRAME_TIMEOUT_S, len(frames), time.monotonic() - tm.get("started", time.monotonic()))
            log.warning("stall state: %s", _stall_snapshot())
            seen = tm["blocks"]
            subprocess.run(["pactl", "suspend-source", name, "1"], timeout=3, check=False)
            # How long the source stays suspended matters: with 0.2 s the restart failed three times
            # in a row (2026-10-13), 0.5 s worked before. Each retry waits longer.
            time.sleep((0.5, 1.0, 2.0)[min(nudges, 3) - 1])
            subprocess.run(["pactl", "suspend-source", name, "0"], timeout=3, check=False)
            time.sleep(1.0)
            if tm["blocks"] > seen:
                log.info("microphone is delivering audio again (%d blocks)", len(frames))
            else:
                log.warning("microphone still delivers nothing after the restart")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return


class _Frames(list):
    """The audio blocks of one take. `closed` tells the callback of an abandoned stream to stop touching them.
    `timing` (time.monotonic() stamps and counters) is what the clip viewer uses to show where a take lost its start."""
    closed = False

    def __init__(self):
        super().__init__()
        self.timing = {"blocks": 0, "overflows": 0, "max_gap": 0.0, "gaps": [], "samples": 0}


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

    def start(self, tap=None, requested=None):
        """tap: optional callable that gets every audio block (int16), from the audio thread.
        requested: time.monotonic() of the key press / click that asked for this take."""
        with self.lock:
            if self._take is not None:
                return
            frames = _Frames()
            tm = frames.timing
            tm["requested"] = requested if requested is not None else time.monotonic()
            tm["enter"] = time.monotonic()
            _select_microphone()
            tm["mic_selected"] = time.monotonic()
            vad = None
            try:
                import local_stt
                vad = local_stt.StreamingVad() if local_stt.trim_active() else None
            except Exception:
                log.exception("could not start the streaming voice detector")

            def callback(indata, n, time_info, status):
                if frames.closed:
                    return
                now = time.monotonic()
                if tm["blocks"] == 0:
                    tm["first_block"] = now
                else:
                    tm["max_gap"] = max(tm["max_gap"], now - tm["last_block"])
                    if now - tm["last_block"] > 0.25:   # [samples recorded before the gap, its length in s]
                        tm["gaps"].append([tm["samples"], round(now - tm["last_block"], 3)])
                tm["samples"] += len(indata)
                tm["last_block"] = now
                tm["blocks"] += 1
                if status:
                    tm["overflows"] += 1
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
            tm["opened"] = time.monotonic()
            stream.start()
            tm["started"] = time.monotonic()
            self._take = (stream, frames, vad)
            threading.Thread(target=_heal_silent_microphone,
                             args=(frames, os.environ.get("PULSE_SOURCE")), daemon=True).start()

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

        def close():
            try:
                stream.stop()
                stream.close()
            except Exception:
                # A vanished mic must not lose what was already captured.
                log.exception("closing input stream failed")

        # PortAudio's stop() can hang for good when its capture thread gets stuck
        # polling a broken Pulse stream (seen 2026-10-13: the take stayed in
        # "Transcribing" forever). The audio is already in memory, so give the
        # close a few seconds and go on without it; the stream is abandoned.
        closer = threading.Thread(target=close, daemon=True)
        closer.start()
        closer.join(STREAM_CLOSE_TIMEOUT_S)
        if closer.is_alive():
            log.warning("closing the input stream hung for %.0fs; going on with the %d blocks already captured",
                        STREAM_CLOSE_TIMEOUT_S, len(frames))
        frames.closed = True
        frames = list(frames)
        audio = np.concatenate(frames, axis=0) if frames else None
        mask = vad.finish(len(audio) if audio is not None else 0) if vad is not None else None
        return audio, mask

    def stop(self):
        return self.finish(self.detach())


# -- learned word corrections -------------------------------------------------
# "cloud code" -> "Claude Code". The source of truth is CORRECTION_LOG_PATH: every hand
# correction (what the model heard, what the user made of it). The rules are rebuilt from
# that log after each new entry. A candidate replacement (a phrase of 1..MAX_RULE_WORDS words)
# is scored on how often the phrase was changed against how often it appeared at all; the
# sentences where it stayed untouched count against it. It becomes a rule when it was changed
# at least MIN_SUPPORT times and in at least MIN_PRECISION of its appearances. A changed word
# is also tried together with the word before or after it, so "cloud" can stay alone-safe
# while "cloud code" is a rule.
CORRECTIONS_PATH = CONFIG_DIR / "corrections.json"
CORRECTION_LOG_PATH = CONFIG_DIR / "correction-log.jsonl"
MIN_SUPPORT = 2
MIN_PRECISION = 0.8
MAX_CHANGE_WORDS = 3   # a changed span of up to this many words on each side
MAX_RULE_WORDS = 4


def _load_corrections():
    try:
        d = json.loads(CORRECTIONS_PATH.read_text())
        if d.get("version") == 2:
            return d
    except Exception:
        pass
    return {"version": 2, "rules": {}, "stats": {}, "blocked": []}


def _save_corrections(d):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CORRECTIONS_PATH.write_text(json.dumps(d, indent=2, ensure_ascii=False))
    try:
        CORRECTIONS_PATH.chmod(0o600)
    except Exception:
        pass


def log_correction(raw, edited, model=""):
    """Append one hand correction (what the model heard, what the user made of it) to a
    local log. Never written when nothing was changed."""
    if raw == edited or not raw.strip():
        return
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    new = not CORRECTION_LOG_PATH.exists()
    with open(CORRECTION_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "model": model,
                            "heard": raw, "corrected": edited}, ensure_ascii=False) + "\n")
    if new:
        try:
            CORRECTION_LOG_PATH.chmod(0o600)
        except Exception:
            pass


def _read_log():
    out = []
    try:
        with open(CORRECTION_LOG_PATH, encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                    out.append((e["heard"], e["corrected"]))
                except Exception:
                    pass
    except OSError:
        pass
    return out


def _rule_regex(src):
    return re.compile(r"(?<!\w)" + r"\s+".join(re.escape(w) for w in src.split()) + r"(?!\w)", re.IGNORECASE)


def _apply(text, rules):
    for src in sorted(rules, key=lambda k: -len(k)):
        dst = rules[src]

        def sub(m, dst=dst):
            return dst[:1].upper() + dst[1:] if m.group(0)[:1].isupper() else dst
        text = _rule_regex(src).sub(sub, text)
    return text


def apply_corrections(text):
    """Text with the learned replacements applied (longest phrases first)."""
    return _apply(text, _load_corrections()["rules"])


def _words(text):
    """(display word, comparison word) pairs: punctuation stripped from the ends."""
    out = []
    for w in text.split():
        core_w = w.strip(".,;:!?\"'()[]{}„“”‚‘’»«")
        if core_w:
            out.append((core_w, core_w.lower()))
    return out


def _candidates(a, b):
    """Yield (src words, dst words, is_core) for every span the user replaced in a -> b:
    the span itself (is_core), and the span with the neighbouring word on either side."""
    import difflib
    if a and b and a[0][1] == b[0][1]:
        b = [a[0]] + b[1:]   # a capital letter at the start of the sentence is not a correction
    sm = difflib.SequenceMatcher(None, [w for w, _ in a], [w for w, _ in b], autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "replace" or not (1 <= i2 - i1 <= MAX_CHANGE_WORDS and 1 <= j2 - j1 <= MAX_CHANGE_WORDS):
            continue
        if i2 - i1 == 1 and j2 - j1 == 1 and a[i1][1] == b[j1][1]:
            continue   # a lone capital letter (sentence start) is not a recognition error
        for left in (0, 1):
            for right in (0, 1):
                if left and (i1 == 0 or j1 == 0 or a[i1 - 1][0] != b[j1 - 1][0]):
                    continue
                if right and (i2 >= len(a) or j2 >= len(b) or a[i2][0] != b[j2][0]):
                    continue
                src = ([a[i1 - 1][1]] if left else []) + [w for _, w in a[i1:i2]] + ([a[i2][1]] if right else [])
                dst = ([b[j1 - 1][0]] if left else []) + [w for w, _ in b[j1:j2]] + ([b[j2][0]] if right else [])
                if len(src) <= MAX_RULE_WORDS:
                    yield tuple(src), tuple(dst), not (left or right)


def rebuild_corrections():
    """Rebuild the rules from the correction log. Returns (added, removed) rule pairs."""
    from collections import Counter
    d = _load_corrections()
    old = dict(d["rules"])
    blocked = {tuple(x) for x in d["blocked"]}
    changed, core, appeared = Counter(), set(), Counter()
    for heard, corrected in _read_log():
        a, b = _words(heard), _words(corrected)
        low = [w for _, w in a]
        for n in range(1, MAX_RULE_WORDS + 1):
            appeared.update(tuple(low[i:i + n]) for i in range(len(low) - n + 1))
        for src, dst, is_core in _candidates(a, b):
            changed[(src, dst)] += 1
            if is_core:
                core.add((src, dst))
    rules, stats = {}, {}
    ranked = sorted(changed.items(), key=lambda kv: (len(kv[0][0]), -kv[1]))
    for (src, dst), n in ranked:
        s_txt, d_txt = " ".join(src), " ".join(dst)
        seen = appeared[src]
        if (src, dst) in core:
            stats[s_txt + "\t" + d_txt] = [n, seen]
        if n < MIN_SUPPORT or n / seen < MIN_PRECISION or [s_txt, d_txt] in d["blocked"]:
            continue
        if s_txt in rules or _apply(s_txt, rules) == d_txt:
            continue   # the src already has a better rule, or shorter rules already do this
        rules[s_txt] = d_txt
        stats[s_txt + "\t" + d_txt] = [n, seen]
    d["rules"], d["stats"] = rules, stats
    _save_corrections(d)
    return ([(k, v) for k, v in rules.items() if old.get(k) != v],
            [(k, v) for k, v in old.items() if rules.get(k) != v])


def list_corrections():
    """(rules, pending): lists of (src, dst, times changed, times the phrase appeared).
    Pending ones were changed but do not (yet) qualify as a rule."""
    d = _load_corrections()
    rules, pending = [], []
    for key, (n, seen) in d["stats"].items():
        src, dst = key.split("\t", 1)
        if d["rules"].get(src) == dst:
            rules.append((src, dst, n, seen))
        elif [src, dst] not in d["blocked"] and _apply(src, d["rules"]) != dst:
            pending.append((src, dst, n, seen))
    return sorted(rules), sorted(pending, key=lambda r: (-r[2], r[0]))


def remove_correction(src, dst):
    """Take a pair back for good: it is not learned again from the log."""
    d = _load_corrections()
    if [src, dst] not in d["blocked"]:
        d["blocked"].append([src, dst])
    _save_corrections(d)
    rebuild_corrections()


def transcribe(audio, cfg, speech=None, cancel=None):
    import local_stt
    threads = int(cfg.get("local_stt_num_threads", local_stt.DEFAULT_THREADS))
    idle_s = 60 * float(cfg.get("local_stt_idle_minutes", 5))
    text = local_stt.get_recognizer(num_threads=threads, idle_s=idle_s).transcribe(audio, speech, cancel)
    # The model ends every piece with a full stop, even a lone word or number.
    if text.endswith(".") and len(text.split()) == 1:
        text = text[:-1]
    return text
