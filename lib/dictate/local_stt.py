"""Local German STT via sherpa-onnx + parakeet-primeline (int8, CPU-only).

Offline transducer. Loads once at first use. Not thread-safe over a single
recognizer instance — we serialize decode calls with a lock; for single-user
dictation that is fine.
"""
import ctypes
import gc
import hashlib
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from i18n import _

MODEL_DIR = Path.home() / ".local" / "share" / "dictate" / "models" / "parakeet-primeline-onnx"
MODEL_REPO = "flozen1981/parakeet-primeline-onnx"
# Pin the revision so users always get the exact bits we tested against.
MODEL_REVISION = "d548e25b9bfe559aa274f361892dc4ed5d64743a"
MODEL_FILES = [
    "encoder.int8.onnx",
    "encoder.int8.onnx.data",   # the 621 MB weight blob — MUST be next to encoder.int8.onnx
    "decoder.int8.onnx",
    "joiner.int8.onnx",
    "tokens.txt",
]
TARGET_SR = 16000
DEFAULT_THREADS = 4
DEFAULT_IDLE_S = 300  # unload the model after this long without a dictation; 0 = never
TARGET_PEAK = 0.5   # quiet pieces are raised to this peak before decoding
MAX_GAIN = 30.0     # but never amplified more than this, so room noise stays noise


# Idle unloading only happens when memory is short: with at least this much
# available (MemAvailable already excludes what the model itself holds) the
# model stays resident, so the next dictation starts instantly.
KEEP_LOADED_MIN_AVAILABLE_MB = 1500
RAM_RECHECK_S = 60


def _ram_comfortable() -> bool:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024 >= KEEP_LOADED_MIN_AVAILABLE_MB
    except (OSError, ValueError, IndexError):
        pass
    return False  # cannot tell: fall back to the plain idle timeout


def model_installed() -> bool:
    return all((MODEL_DIR / f).exists() for f in MODEL_FILES)


# Our own copy of the pinned revision, tried first; Hugging Face is the
# fallback. Either way the files must match these hashes, so a changed or
# tampered upstream/mirror file is rejected rather than loaded.
MODEL_MIRROR = "https://cyberbeest.com/models/parakeet-primeline-onnx/d548e25b9bfe"
MODEL_SHA256 = {
    "encoder.int8.onnx":      "d4232f86718da0330167fb10789d1a35cffe6a60cd58239957943a8d9bc24c63",
    "encoder.int8.onnx.data": "d3b0d27912043d38a3c2ce4f2c03124be30bc1ff57d976302908954b2e8fe7bb",
    "decoder.int8.onnx":      "fb4ddefe200706cabb27ee3fc1c81efa50555a4c8a8e00b663cc795216fb9369",
    "joiner.int8.onnx":       "8220c0d117d81bdd0d8c770881932ac340f1ce4b36932941d561d11ad1aaffce",
    "tokens.txt":             "ba8e4007c65f4bb4358ffe2ecc13d9ccc7a10351151065242b5c3a943e685742",
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _download_from_mirror(progress_cb) -> None:
    import requests
    for name in MODEL_FILES:
        dest = MODEL_DIR / name
        if dest.exists() and _sha256(dest) == MODEL_SHA256[name]:
            continue
        part = dest.with_name(name + ".part")
        url = f"{MODEL_MIRROR}/{name}"
        have = part.stat().st_size if part.exists() else 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        with requests.get(url, headers=headers, stream=True, timeout=30) as r:
            if have and r.status_code == 200:   # server ignored the range: start over
                have = 0
            elif r.status_code not in (200, 206):
                raise RuntimeError(f"{url}: HTTP {r.status_code}")
            total = have + int(r.headers.get("content-length", 0))
            done, last = have, 0.0
            with open(part, "ab" if have else "wb") as f:
                for block in r.iter_content(1 << 20):
                    f.write(block)
                    done += len(block)
                    now = time.monotonic()
                    if progress_cb and now - last > 0.5:
                        last = now
                        progress_cb(_("Downloading model: {name} ({done} / {total} MB)").format(
                            name=name, done=done >> 20, total=total >> 20))
        if _sha256(part) != MODEL_SHA256[name]:
            part.unlink()
            raise RuntimeError(f"{name}: checksum mismatch")
        part.replace(dest)


def download_model(progress_cb: Optional[Callable[[str], None]] = None) -> None:
    """Download the pinned model into MODEL_DIR, checksum-verified.

    Tries our own server first (resumable), then Hugging Face. Blocks. Raises
    RuntimeError on failure. `progress_cb(msg)` gets short status strings for
    GUI display.
    """
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if progress_cb:
        progress_cb(_("Downloading model (~640 MB, one-time) ..."))
    try:
        _download_from_mirror(progress_cb)
    except Exception as mirror_err:
        if progress_cb:
            progress_cb(_("Our server did not deliver the model, trying Hugging Face ..."))
        try:
            from huggingface_hub import snapshot_download
        except ImportError as e:
            raise RuntimeError(f"download failed ({mirror_err}) and huggingface_hub is not installed") from e
        snapshot_download(
            repo_id=MODEL_REPO,
            revision=MODEL_REVISION,
            local_dir=str(MODEL_DIR),
            allow_patterns=MODEL_FILES,
        )
        for name in MODEL_FILES:
            if _sha256(MODEL_DIR / name) != MODEL_SHA256[name]:
                (MODEL_DIR / name).unlink()
                raise RuntimeError(f"{name}: checksum mismatch after Hugging Face download")
    if progress_cb:
        progress_cb(_("Model downloaded."))


class LocalRecognizer:
    """Wraps sherpa_onnx.OfflineRecognizer with async load + decode lock."""

    def __init__(self, num_threads: int):
        self.num_threads = num_threads
        self._recognizer = None
        self._decode_lock = threading.Lock()
        self.last_used = time.monotonic()
        self._ready = threading.Event()
        self._load_error: Optional[Exception] = None
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self) -> None:
        try:
            import sherpa_onnx
            rec = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=str(MODEL_DIR / "encoder.int8.onnx"),
                decoder=str(MODEL_DIR / "decoder.int8.onnx"),
                joiner=str(MODEL_DIR / "joiner.int8.onnx"),
                tokens=str(MODEL_DIR / "tokens.txt"),
                model_type="nemo_transducer",
                num_threads=self.num_threads,
                decoding_method="greedy_search",
            )
            self._recognizer = rec
        except Exception as e:
            self._load_error = e
        finally:
            self.last_used = time.monotonic()  # idle time counts from load completion
            self._ready.set()

    def is_ready(self) -> bool:
        return self._ready.is_set() and self._recognizer is not None

    def wait_ready(self, timeout: Optional[float] = None) -> bool:
        return self._ready.wait(timeout)

    def transcribe(self, audio: np.ndarray) -> str:
        """Take int16 mono 16 kHz audio (shape (N,) or (N, 1)), return text."""
        self._ready.wait()
        if self._recognizer is None:
            raise RuntimeError(f"local recognizer failed to load: {self._load_error}")
        if audio.ndim > 1:
            audio = audio.squeeze()
        # sherpa-onnx wants float32 in [-1, 1]
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32) / 32768.0
        parts = []
        with self._decode_lock:
            for chunk in _split(audio):
                text = self._decode(chunk)
                # The model now and then returns nothing for a long piece that
                # clearly holds speech; shorter pieces of the same audio decode.
                if not text and len(chunk) > RETRY_CHUNK_S * TARGET_SR:
                    text = " ".join(t for t in map(self._decode, _split(chunk, RETRY_CHUNK_S)) if t)
                parts.append(text)
        self.last_used = time.monotonic()
        return " ".join(p for p in parts if p)

    def _decode(self, chunk: np.ndarray) -> str:
        # Quiet input (speech around -45 dBFS, peak ~0.03) comes back empty
        # as a whole; the same audio raised to a peak of 0.5 decodes in full.
        peak = float(np.abs(chunk).max()) if len(chunk) else 0.0
        if 0.0 < peak < TARGET_PEAK:
            chunk = chunk * min(TARGET_PEAK / peak, MAX_GAIN)
        s = self._recognizer.create_stream()
        s.accept_waveform(TARGET_SR, chunk)
        self._recognizer.decode_stream(s)
        return s.result.text.strip()


# The encoder fails outright on more than 400 s of audio ("Attempting to
# broadcast an axis ...") and its memory grows quadratically before that
# (180 s ≈ 3.5 GB), so long dictations are decoded in pieces.
MAX_CHUNK_S = 90
RETRY_CHUNK_S = 20  # piece length for the second pass over a piece that came back empty
_SEARCH_S = 15      # look for a pause in the last part of each piece
_WIN_S = 0.4


def _split(audio: np.ndarray, max_s: float = MAX_CHUNK_S):
    """Yield pieces of at most max_s, cut at the quietest spot near the end."""
    search_s = min(_SEARCH_S, max_s / 2)
    max_n, search_n, win_n = (int(x * TARGET_SR) for x in (max_s, search_s, _WIN_S))
    while len(audio) > max_n:
        tail = audio[max_n - search_n:max_n]
        n_win = len(tail) // win_n
        energy = (tail[:n_win * win_n].reshape(n_win, win_n) ** 2).mean(axis=1)
        cut = max_n - search_n + int(energy.argmin()) * win_n + win_n // 2
        yield audio[:cut]
        audio = audio[cut:]
    yield audio


_instance: Optional[LocalRecognizer] = None
_instance_lock = threading.Lock()


_idle_s = 0
_idle_timer: Optional[threading.Timer] = None


def _arm_idle_timer() -> None:
    """(Re)start the countdown to unloading; caller holds _instance_lock."""
    global _idle_timer
    if _idle_timer is not None:
        _idle_timer.cancel()
        _idle_timer = None
    if _idle_s > 0 and _instance is not None:
        _idle_timer = threading.Timer(_idle_s, _unload_if_idle)
        _idle_timer.daemon = True
        _idle_timer.start()


def _unload_if_idle() -> None:
    global _instance, _idle_timer
    with _instance_lock:
        inst = _instance
        if inst is None:
            return
        left = _idle_s - (time.monotonic() - inst.last_used)
        if inst._decode_lock.locked() or not inst._ready.is_set() or left > 0:
            # Used (or still busy) since the timer started: wait out the rest.
            _arm_idle_timer()
            return
        if _ram_comfortable():
            # Plenty of free memory: keep the model, look again in a minute.
            _idle_timer = threading.Timer(RAM_RECHECK_S, _unload_if_idle)
            _idle_timer.daemon = True
            _idle_timer.start()
            return
        _instance = None
    del inst
    _release()


def _release() -> None:
    """Give freed model memory back; callers drop their reference first."""
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)  # hand the freed weights back to the OS
    except OSError:
        pass


def unload() -> bool:
    """Drop the model now (tray menu). False if a dictation is decoding or
    there is nothing to unload."""
    global _instance, _idle_timer
    with _instance_lock:
        inst = _instance
        if inst is None or inst._decode_lock.locked():
            return False
        _instance = None
        if _idle_timer is not None:
            _idle_timer.cancel()
            _idle_timer = None
    del inst
    _release()
    return True


def status():
    """('not_loaded' | 'loading' | 'loaded', seconds until idle unload or None)."""
    with _instance_lock:
        inst = _instance
        if inst is None:
            return "not_loaded", None
        if not inst._ready.is_set():
            return "loading", None
        if inst._recognizer is None:
            return "not_loaded", None
        if _idle_s <= 0 or _ram_comfortable():
            return "loaded", None
        return "loaded", max(0.0, _idle_s - (time.monotonic() - inst.last_used))


def get_recognizer(num_threads: int = DEFAULT_THREADS, idle_s: float = DEFAULT_IDLE_S) -> LocalRecognizer:
    """Get or (re)create the process-wide singleton.

    sherpa-onnx does not let us change num_threads on an existing recognizer,
    so a thread-count change drops the old one and builds a fresh one. The
    caller pays the load cost only when the setting actually changes, or when
    the model was unloaded after idle_s seconds without use (0 = never unload).
    Every call counts as use and restarts the idle countdown.
    """
    global _instance, _idle_s
    with _instance_lock:
        _idle_s = idle_s
        if _instance is None or _instance.num_threads != num_threads:
            _instance = LocalRecognizer(num_threads)
        _instance.last_used = time.monotonic()
        _arm_idle_timer()
        return _instance


def preload(num_threads: int = DEFAULT_THREADS, idle_s: float = DEFAULT_IDLE_S) -> LocalRecognizer:
    """Kick off the model load in the background so the first real decode is fast."""
    return get_recognizer(num_threads, idle_s)

