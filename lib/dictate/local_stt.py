"""Local speech-to-text via sherpa-onnx (NeMo transducers, int8, CPU-only).

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

_MODELS_ROOT = Path.home() / ".local" / "share" / "dictate" / "models"

# The two speech models Dictate can use. Both are sherpa-onnx NeMo
# transducers (int8, CPU-only) and both are fetched from our own server first,
# every file checked against the SHA-256 below, so a changed or tampered
# upstream/mirror file is rejected rather than loaded. Keys are what the
# config's "model" setting holds; the first one is the default.
MODELS = {
    # German only: ~5x less computation per second of audio, ~140 MB.
    "nemo-de-fastconformer-int8": {
        "size_mb": 140,
        "dir": _MODELS_ROOT / "nemo-de-fastconformer-onnx",
        "mirror": "https://cyberbeest.com/models/nemo-de-fastconformer-onnx/int8-2026-05",
        # NVIDIA stt_de_fastconformer_hybrid_large_pc, CC-BY-4.0, as packaged by sherpa-onnx.
        "tar_url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
                   "sherpa-onnx-nemo-transducer-stt_de_fastconformer_hybrid_large_pc-int8.tar.bz2",
        "sha256": {
            "encoder.int8.onnx": "10fbb959c36c461afb02ea87c109119eb001f30e91a130663bd6d5bbcba74ba9",
            "decoder.int8.onnx": "4633a4b0a3f21f7ace4df02e772f5b5e63d45f84a71ee1e2660998fc4beb46ad",
            "joiner.int8.onnx":  "bac3af36a9bd66bfcad2ae6a35f17c7853e034e497134a8b0cbe48a8e954bd9f",
            "tokens.txt":        "abb1136142604d6d1766ad5060bd4f4b1048d7a096cd094b2d40eec3e666be9f",
        },
    },
    # German and other European languages: ~650 MB.
    "parakeet-primeline-int8": {
        "size_mb": 640,
        "dir": _MODELS_ROOT / "parakeet-primeline-onnx",
        "mirror": "https://cyberbeest.com/models/parakeet-primeline-onnx/d548e25b9bfe",
        "hf_repo": "flozen1981/parakeet-primeline-onnx",
        # Pin the revision so users always get the exact bits we tested against.
        "hf_revision": "d548e25b9bfe559aa274f361892dc4ed5d64743a",
        "sha256": {
            "encoder.int8.onnx":      "d4232f86718da0330167fb10789d1a35cffe6a60cd58239957943a8d9bc24c63",
            "encoder.int8.onnx.data": "d3b0d27912043d38a3c2ce4f2c03124be30bc1ff57d976302908954b2e8fe7bb",  # the weight blob, must sit next to encoder.int8.onnx
            "decoder.int8.onnx":      "fb4ddefe200706cabb27ee3fc1c81efa50555a4c8a8e00b663cc795216fb9369",
            "joiner.int8.onnx":       "8220c0d117d81bdd0d8c770881932ac340f1ce4b36932941d561d11ad1aaffce",
            "tokens.txt":             "ba8e4007c65f4bb4358ffe2ecc13d9ccc7a10351151065242b5c3a943e685742",
        },
    },
}
DEFAULT_MODEL = "nemo-de-fastconformer-int8"
_model_id = DEFAULT_MODEL


def select_model(model_id: str) -> str:
    """Make `model_id` the model every function below works on (unknown ids
    fall back to the default). Returns the id actually selected."""
    global _model_id
    _model_id = model_id if model_id in MODELS else DEFAULT_MODEL
    return _model_id


def _spec(model_id: Optional[str] = None) -> dict:
    return MODELS[model_id or _model_id]


def model_dir(model_id: Optional[str] = None) -> Path:
    return _spec(model_id)["dir"]


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


def model_installed(model_id: Optional[str] = None) -> bool:
    """Whether the given model (default: the selected one) is on disk."""
    return all((model_dir(model_id) / f).exists() for f in _spec(model_id)["sha256"])


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _download_from_mirror(progress_cb, model_id=None) -> None:
    import requests
    spec = _spec(model_id)
    for name, want in spec["sha256"].items():
        dest = model_dir(model_id) / name
        if dest.exists() and _sha256(dest) == want:
            continue
        part = dest.with_name(name + ".part")
        url = f"{spec['mirror']}/{name}"
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
        if _sha256(part) != want:
            part.unlink()
            raise RuntimeError(f"{name}: checksum mismatch")
        part.replace(dest)


def _download_fallback(progress_cb, model_id=None) -> None:
    """Second source if our own server did not deliver: Hugging Face for the
    multi-language model, the sherpa-onnx release archive for the German one."""
    spec = _spec(model_id)
    if "hf_repo" in spec:
        try:
            from huggingface_hub import snapshot_download
        except ImportError as e:
            raise RuntimeError("huggingface_hub is not installed") from e
        snapshot_download(
            repo_id=spec["hf_repo"],
            revision=spec["hf_revision"],
            local_dir=str(model_dir(model_id)),
            allow_patterns=list(spec["sha256"]),
        )
    else:
        import requests
        import tarfile
        import tempfile
        with tempfile.TemporaryFile() as tmp:
            with requests.get(spec["tar_url"], stream=True, timeout=30) as r:
                r.raise_for_status()
                for block in r.iter_content(1 << 20):
                    tmp.write(block)
            tmp.seek(0)
            with tarfile.open(fileobj=tmp, mode="r:bz2") as tar:
                for member in tar.getmembers():
                    name = Path(member.name).name
                    if member.isfile() and name in spec["sha256"]:
                        # Written under our own name only, never the archive's path.
                        (model_dir(model_id) / name).write_bytes(tar.extractfile(member).read())
    for name, want in spec["sha256"].items():
        if _sha256(model_dir(model_id) / name) != want:
            (model_dir(model_id) / name).unlink()
            raise RuntimeError(f"{name}: checksum mismatch after fallback download")


def download_model(progress_cb: Optional[Callable[[str], None]] = None,
                   model_id: Optional[str] = None) -> None:
    """Download the selected model into its folder, checksum-verified.

    Tries our own server first (resumable), then the fallback source. Blocks.
    Raises RuntimeError on failure. `progress_cb(msg)` gets short status
    strings for GUI display.
    """
    model_dir(model_id).mkdir(parents=True, exist_ok=True)
    if progress_cb:
        progress_cb(_("Downloading model (about {mb} MB, one-time) ...").format(mb=_spec(model_id)["size_mb"]))
    try:
        _download_from_mirror(progress_cb, model_id)
    except Exception as mirror_err:
        if progress_cb:
            progress_cb(_("Our server did not deliver the model, trying another source ..."))
        try:
            _download_fallback(progress_cb, model_id)
        except Exception as e:
            raise RuntimeError(f"download failed ({mirror_err}); fallback failed too ({e})") from e
    if progress_cb:
        progress_cb(_("Model downloaded."))


class LocalRecognizer:
    """Wraps sherpa_onnx.OfflineRecognizer with async load + decode lock."""

    def __init__(self, num_threads: int):
        self.num_threads = num_threads
        self.model_id = _model_id
        self._dir = model_dir()
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
                encoder=str(self._dir / "encoder.int8.onnx"),
                decoder=str(self._dir / "decoder.int8.onnx"),
                joiner=str(self._dir / "joiner.int8.onnx"),
                tokens=str(self._dir / "tokens.txt"),
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
        if inst is None or inst.model_id != _model_id:
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
        if (_instance is None or _instance.num_threads != num_threads
                or _instance.model_id != _model_id):
            _instance = LocalRecognizer(num_threads)
        _instance.last_used = time.monotonic()
        _arm_idle_timer()
        return _instance


def preload(num_threads: int = DEFAULT_THREADS, idle_s: float = DEFAULT_IDLE_S) -> LocalRecognizer:
    """Kick off the model load in the background so the first real decode is fast."""
    return get_recognizer(num_threads, idle_s)

