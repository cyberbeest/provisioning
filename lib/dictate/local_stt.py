"""Local speech-to-text via sherpa-onnx (NeMo transducers, int8, CPU-only).

Offline transducer. Loads once at first use. Not thread-safe over a single
recognizer instance — we serialize decode calls with a lock; for single-user
dictation that is fine.
"""
import collections
import ctypes
import gc
import hashlib
import queue
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


# ---------------------------------------------------------------------------
# Silence trimming. The speech model's decoding time grows with the length of
# the audio, so pauses cost real time. A voice activity detector (Silero VAD,
# silero_vad.onnx next to this file) finds the speech; the silence around and
# between the phrases is cut, long pauses are shortened to a short gap (kept
# so the model still hears phrase boundaries), and the model decodes the rest
# as one piece. The text stays the same, the decoding takes ~40% less.
VAD_MODEL = Path(__file__).resolve().with_name("silero_vad.onnx")
VAD_FRAME = 320            # 20 ms: the unit of a speech mask
VAD_WINDOW = 512           # samples per step the detector takes
VAD_THRESHOLD = 0.5
VAD_MIN_SILENCE_S = 0.25   # a quieter stretch this long ends a segment
VAD_PAD_BEFORE_S = 0.30    # context kept before each segment: the detector places a soft first word late
VAD_PAD_AFTER_S = 0.16     # ... and after it
VAD_MAX_GAP_S = 0.4        # silence between segments longer than this ...
VAD_KEEP_GAP_S = 0.15      # ... is shortened to this
STREAM_TRUST_PEAK = 0.1    # -20 dBFS: streamed VAD results are trusted above this peak
NO_SPEECH_DECODE_S = 2.0   # no speech found: shorter clips are still decoded (a lone short word)
VAD_HIGHPASS_HZ = 150      # the detector hears the audio without anything below this (mains hum drowns quiet speech for it)
_trim_enabled = True
_vad_highpass = True


def set_trim(on: bool) -> None:
    global _trim_enabled
    _trim_enabled = bool(on)


def set_vad_highpass(on: bool) -> None:
    global _vad_highpass
    _vad_highpass = bool(on)


class _HighPass:
    """2nd-order Butterworth high-pass (RBJ biquad); the state carries over between blocks."""

    def __init__(self, hz: float = VAD_HIGHPASS_HZ, sr: int = 16000):
        w = 2 * np.pi * hz / sr
        al = np.sin(w) / np.sqrt(2)
        c = np.cos(w)
        a0 = 1 + al
        self.b = ((1 + c) / 2 / a0, -(1 + c) / a0, (1 + c) / 2 / a0)
        self.a = (-2 * c / a0, (1 - al) / a0)
        self.z1 = self.z2 = 0.0

    def __call__(self, x: np.ndarray) -> np.ndarray:
        b0, b1, b2 = self.b
        a1, a2 = self.a
        z1, z2 = self.z1, self.z2
        out = []
        for v in x.tolist():
            y = b0 * v + z1
            z1 = b1 * v - a1 * y + z2
            z2 = b2 * v - a2 * y
            out.append(y)
        self.z1, self.z2 = z1, z2
        return np.asarray(out, np.float32)


def _vad_filter():
    """A fresh high-pass for one stretch of audio, or None when the setting is off."""
    return _HighPass(VAD_HIGHPASS_HZ, TARGET_SR) if _vad_highpass else None


def trim_active() -> bool:
    return _trim_enabled and VAD_MODEL.exists()


def _vad_detector(max_s: float):
    import sherpa_onnx
    cfg = sherpa_onnx.VadModelConfig()
    cfg.silero_vad.model = str(VAD_MODEL)
    cfg.silero_vad.threshold = VAD_THRESHOLD
    cfg.silero_vad.min_silence_duration = VAD_MIN_SILENCE_S
    cfg.silero_vad.min_speech_duration = 0.1
    cfg.silero_vad.window_size = VAD_WINDOW
    cfg.sample_rate = TARGET_SR
    cfg.num_threads = 1
    return sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=max_s)


def _boost(audio: np.ndarray) -> np.ndarray:
    """The quiet-input boost the decoder applies, so the detector hears what the model hears."""
    peak = float(np.abs(audio).max()) if len(audio) else 0.0
    return audio * min(TARGET_PEAK / peak, MAX_GAIN) if 0.0 < peak < TARGET_PEAK else audio


def _mask_from_segments(segments, n_samples: int):
    """Frame mask (True = keep) from (start, length) sample spans, padded; None if there is no speech."""
    n = n_samples // VAD_FRAME
    mask = np.zeros(n, bool)
    for start, length in segments:
        mask[start // VAD_FRAME: min((start + length) // VAD_FRAME + 1, n)] = True
    if not mask.any():
        return None
    before = int(VAD_PAD_BEFORE_S * TARGET_SR / VAD_FRAME)
    after = int(VAD_PAD_AFTER_S * TARGET_SR / VAD_FRAME)
    m = mask.astype(int)
    later = np.convolve(m, np.ones(after + 1, int))[:n] > 0
    earlier = np.convolve(m[::-1], np.ones(before + 1, int))[:n][::-1] > 0
    return mask | later | earlier


def _drain(vad, segments: list) -> None:
    while not vad.empty():
        seg = vad.front
        segments.append((seg.start, len(seg.samples)))
        vad.pop()


def speech_mask(audio: np.ndarray):
    """Speech mask of a whole float32 clip, or None if the detector finds no speech."""
    vad = _vad_detector(len(audio) / TARGET_SR + 5)
    hp = _vad_filter()
    if hp is not None:
        audio = hp(audio)
    audio = _boost(audio)
    segments: list = []
    for i in range(0, len(audio) - VAD_WINDOW + 1, VAD_WINDOW):
        vad.accept_waveform(audio[i:i + VAD_WINDOW])
        _drain(vad, segments)
    vad.flush()
    _drain(vad, segments)
    return _mask_from_segments(segments, len(audio))


def trim_audio(audio: np.ndarray, mask) -> np.ndarray:
    """The masked speech runs, with silences over VAD_MAX_GAP_S shortened to VAD_KEEP_GAP_S."""
    edges = np.diff(np.concatenate(([0], mask.astype(np.int8), [0])))
    runs = list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)))
    max_gap = int(VAD_MAX_GAP_S * TARGET_SR / VAD_FRAME)
    keep_gap = int(VAD_KEEP_GAP_S * TARGET_SR / VAD_FRAME)
    out = []
    for k, (s, e) in enumerate(runs):
        out.append(audio[s * VAD_FRAME: e * VAD_FRAME])
        if k + 1 < len(runs):
            gap = runs[k + 1][0] - e
            out.append(np.zeros((keep_gap if gap > max_gap else gap) * VAD_FRAME, np.float32))
    return np.concatenate(out).astype(np.float32)


def _trimmed(audio: np.ndarray, speech) -> np.ndarray:
    """The audio the model should decode: the speech with the silence cut, the
    audio itself when trimming is off or fails, nothing when there is no speech
    (except in a short clip, which may hold a single short word)."""
    if not _trim_enabled or not VAD_MODEL.exists():
        return audio
    try:
        mask = speech if speech is not None and len(speech) == len(audio) // VAD_FRAME else speech_mask(audio)
    except Exception:
        import logging
        logging.getLogger("dictate").exception("silence trimming failed, decoding the full clip")
        return audio
    import logging
    log = logging.getLogger("dictate")
    if mask is None:
        log.info("no speech found in %.1fs of audio", len(audio) / TARGET_SR)
        return audio if len(audio) < NO_SPEECH_DECODE_S * TARGET_SR else audio[:0]
    trimmed = trim_audio(audio, mask)
    log.info("silence trimmed: %.1fs -> %.1fs (%s mask), first speech at %.2fs", len(audio) / TARGET_SR,
             len(trimmed) / TARGET_SR,
             "streamed" if speech is not None and len(speech) == len(audio) // VAD_FRAME else "batch",
             int(np.argmax(mask)) * VAD_FRAME / TARGET_SR)
    return trimmed


class StreamingVad:
    """Runs the detector while a recording is still going, so the speech mask is
    ready the moment the key is released. feed() is cheap and safe to call from
    the audio callback; the work happens on its own thread."""

    def __init__(self):
        self._q: "queue.SimpleQueue" = queue.SimpleQueue()
        self._segments: list = []
        self._peak = 0.0
        self._failed = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def feed(self, block: np.ndarray) -> None:
        self._q.put(block)

    def _run(self) -> None:
        try:
            vad = _vad_detector(60)
            hp = _vad_filter()
            buf = np.zeros(0, np.float32)
            while True:
                block = self._q.get()
                if block is None:
                    break
                x = block.reshape(-1).astype(np.float32) / 32768.0
                self._peak = max(self._peak, float(np.abs(x).max()))
                buf = np.concatenate((buf, x))
                n = len(buf) // VAD_WINDOW * VAD_WINDOW
                for i in range(0, n, VAD_WINDOW):
                    win = buf[i:i + VAD_WINDOW]
                    vad.accept_waveform(hp(win) if hp is not None else win)
                    _drain(vad, self._segments)
                buf = buf[n:]
            vad.flush()
            _drain(vad, self._segments)
        except Exception:
            self._failed = True
            import logging
            logging.getLogger("dictate").exception("streaming VAD failed")

    def finish(self, n_samples: int):
        """The speech mask for the n_samples recorded, or None when the caller should
        run the detector over the finished clip instead (quiet recording, no speech
        found, or a failure)."""
        self._q.put(None)
        self._thread.join(timeout=10)
        if self._thread.is_alive() or self._failed or self._peak < STREAM_TRUST_PEAK:
            return None
        return _mask_from_segments(self._segments, n_samples)


# ---------------------------------------------------------------------------
# Live level meter shown while recording. The detector says speech or not for
# every 32 ms window (the same model and threshold as the trimming) and the
# level is measured on the same hum-filtered audio, so the bars show what the
# detector hears: they stay empty unless it hears speech. The loudness
# reference is the 90th percentile of the last few seconds of speech, so the
# bars use their range whatever the microphone level.
METER_DB_FLOOR, METER_DB_CEIL = -50.0, -10.0   # fixed range until there is speech to normalize on
METER_NORM_S = 3.0
METER_NORM_PERCENTILE = 90.0
METER_NORM_TOP_DB, METER_NORM_SPAN_DB = 3.0, 30.0
METER_NORM_MIN_WINDOWS = 15
METER_REF_ATTACK_S, METER_REF_RELEASE_S = 0.3, 1.0


class LiveMeter:
    """feed() int16 blocks from the audio callback; read speech / level_db / scale() any time.
    Runs on its own thread; close() ends it."""

    _last_ref = None   # the reference the previous dictation ended with: a good start for the next one

    def __init__(self):
        self._q: "queue.SimpleQueue" = queue.SimpleQueue()
        self.speech = False
        self.level_db = -90.0
        self.ref_db = LiveMeter._last_ref
        self._speech_db: "collections.deque" = collections.deque(maxlen=int(METER_NORM_S * TARGET_SR / VAD_WINDOW))
        threading.Thread(target=self._run, daemon=True).start()

    def feed(self, block: np.ndarray) -> None:
        self._q.put(block)

    def close(self) -> None:
        self._q.put(None)

    def scale(self):
        """(top, span): dBFS of the top of the bars and the dB range below it."""
        if self.ref_db is not None:
            return self.ref_db + METER_NORM_TOP_DB, METER_NORM_SPAN_DB
        return METER_DB_CEIL, METER_DB_CEIL - METER_DB_FLOOR

    def _update_ref(self) -> None:
        if len(self._speech_db) < METER_NORM_MIN_WINDOWS:
            return   # too little speech yet: the starting reference stays
        p = float(np.percentile(self._speech_db, METER_NORM_PERCENTILE))
        if self.ref_db is None:
            self.ref_db = p
        else:
            tc = METER_REF_ATTACK_S if p > self.ref_db else METER_REF_RELEASE_S
            self.ref_db += (p - self.ref_db) * min(1.0, (VAD_WINDOW / TARGET_SR) / tc)
        LiveMeter._last_ref = self.ref_db

    def _run(self) -> None:
        try:
            import sherpa_onnx
            c = sherpa_onnx.VadModelConfig()
            c.silero_vad.model = str(VAD_MODEL)
            c.silero_vad.threshold = VAD_THRESHOLD
            c.silero_vad.window_size = VAD_WINDOW
            c.sample_rate = TARGET_SR
            c.num_threads = 1
            model = sherpa_onnx.VadModel.create(c)
            hp = _vad_filter()
            buf = np.zeros(0, np.float32)
            while True:
                block = self._q.get()
                if block is None:
                    break
                buf = np.concatenate((buf, block.reshape(-1).astype(np.float32) / 32768.0))
                while len(buf) >= VAD_WINDOW:
                    x, buf = buf[:VAD_WINDOW], buf[VAD_WINDOW:]
                    heard = hp(x) if hp is not None else x
                    self.speech = bool(model.is_speech(heard))
                    self.level_db = 20 * np.log10(max(float(np.sqrt(np.mean(heard * heard))), 1e-5))
                    if self.speech:
                        self._speech_db.append(self.level_db)
                        self._update_ref()
        except Exception:
            import logging
            logging.getLogger("dictate").exception("level meter failed")


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

    def transcribe(self, audio: np.ndarray, speech=None) -> str:
        """Take int16 mono 16 kHz audio (shape (N,) or (N, 1)), return text.
        speech: the clip's speech mask if it was already found while recording."""
        self._ready.wait()
        if self._recognizer is None:
            raise RuntimeError(f"local recognizer failed to load: {self._load_error}")
        if audio.ndim > 1:
            audio = audio.squeeze()
        # sherpa-onnx wants float32 in [-1, 1]
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32) / 32768.0
        audio = _trimmed(audio, speech)
        if len(audio) == 0:
            return ""
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


def status() -> str:
    """'not_loaded', 'loading' or 'loaded' for the selected model."""
    with _instance_lock:
        inst = _instance
        if inst is None or inst.model_id != _model_id:
            return "not_loaded"
        if not inst._ready.is_set():
            return "loading"
        return "loaded" if inst._recognizer is not None else "not_loaded"


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

