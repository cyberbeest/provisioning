#!/usr/bin/env python3
"""Live K.I.T.T.-style voice-box view of the Silero VAD that Dictate uses.

A gated volume meter: while the VAD (Dictate's settings, threshold 0.5) hears
speech, the bars show the audio level; otherwise there are no bars. Audio goes
straight from the microphone into the detector, no normalization or boost.

The verdict for a stretch of audio arrives ~100 ms after it was spoken, so the
bars are replayed with a fixed delay (--delay, default 140 ms): every window
is drawn at its capture time + delay, which lets the whole utterance show from
its first window instead of from when the VAD caught on.
"""
import argparse
import collections
import queue
import sys
import threading
import time
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import QApplication, QCheckBox, QWidget

DICTATE = Path(__file__).resolve().parents[1] / "lib/dictate"
VAD_MODEL = DICTATE / "silero_vad.onnx"
sys.path.insert(0, str(DICTATE))
import local_stt  # Dictate's own high-pass, so the viewer filters exactly like it does
SR, WINDOW = 16000, 512
VAD_THRESHOLD = 0.5
BACKFILL_WINDOWS = 3  # when the VAD turns on, the windows just before it count as speech too (it recognizes onsets late)
ROWS = 21  # odd: one middle row, bars grow outward from it
DB_FLOOR, DB_CEIL = -50.0, -10.0  # fixed level range mapped onto the bars (normalization off)
NORM_SPEECH_S = 3.0               # floating normalization: the last this-many seconds of VAD-yes audio ...
NORM_PERCENTILE = 90.0            # ... its 90th-percentile loudness is the reference
NORM_TOP_DB, NORM_SPAN_DB = 3.0, 30.0  # top of the bars sits 3 dB above the reference, 30 dB of range
NORM_MIN_WINDOWS = 15             # fewer speech windows than this: fall back to the fixed range
NORM_ATTACK_S, NORM_RELEASE_S = 0.3, 1.0  # the reference moves slowly: it follows louder speech sooner than quieter
RELEASE_DB_S = 100.0            # center column falls this fast, like a studio meter
SIDE_SCALE = 0.5                # side columns are half the middle one, as on the original
ATTACK_S = 0.025                # time constant of the rise


class Detector:
    def __init__(self):
        import sherpa_onnx
        c = sherpa_onnx.VadModelConfig()
        c.silero_vad.model = str(VAD_MODEL)
        c.silero_vad.threshold = VAD_THRESHOLD
        c.silero_vad.window_size = WINDOW
        c.sample_rate = SR
        c.num_threads = 1
        self.model = sherpa_onnx.VadModel.create(c)
        self.mic_ms = 0.0      # input device latency, set once the stream is open
        self.window_ms = 1000 * WINDOW / SR
        self.compute_ms = 0.0  # callback -> verdict
        self.live_db = -90.0   # newest window, for the small reference meter
        self.peak_db = -90.0
        self.events = collections.deque()  # (capture time, speech, level dB, top, span), oldest first
        self.lock = threading.Lock()
        self.prev_speech = False
        self.q: "queue.SimpleQueue" = queue.SimpleQueue()
        self.buf = np.zeros(0, np.float32)
        self.hp = local_stt._HighPass(local_stt.VAD_HIGHPASS_HZ, SR)
        self.filter_on = True  # the VAD and the level meter hear the high-passed audio
        self.norm = True
        self.speech_db = collections.deque(maxlen=int(NORM_SPEECH_S * SR / WINDOW))
        self.ref_db = None  # smoothed 90th percentile of the speech windows
        threading.Thread(target=self._run, daemon=True).start()

    def feed(self, indata, *_):
        self.q.put((time.monotonic(), indata[:, 0].astype(np.float32) / 32768.0))

    def _run(self):
        while True:
            t0, block = self.q.get()
            self.buf = np.concatenate((self.buf, block))
            while len(self.buf) >= WINDOW:
                x, self.buf = self.buf[:WINDOW], self.buf[WINDOW:]
                h = self.hp(x)  # always run, so the filter state is right when it is switched on
                heard = h if self.filter_on else x
                speech = bool(self.model.is_speech(heard))
                db = 20 * np.log10(max(float(np.sqrt(np.mean(heard * heard))), 1e-5))
                self.live_db = db
                self.peak_db = max(db, self.peak_db - 0.6)
                if speech:
                    self.speech_db.append(db)
                    self._update_ref()
                if self.norm and self.ref_db is not None:
                    hi, span = self.ref_db + NORM_TOP_DB, NORM_SPAN_DB
                else:
                    hi, span = DB_CEIL, DB_CEIL - DB_FLOOR
                with self.lock:
                    if speech and not self.prev_speech:
                        # the VAD only noticed the onset now: the replay is delayed, so the
                        # windows just before it that are still queued can be corrected
                        for j in range(max(0, len(self.events) - BACKFILL_WINDOWS), len(self.events)):
                            t, _sp, d_, hi_, sp_ = self.events[j]
                            self.events[j] = (t, True, d_, hi_, sp_)
                    self.events.append((t0, speech, db, hi, span))
                self.prev_speech = speech
                ms = 1000 * (time.monotonic() - t0)
                self.compute_ms = ms if self.compute_ms == 0 else self.compute_ms * 0.9 + ms * 0.1

    def set_filter(self, on):
        """Switch the mains-hum filter. The levels change scale, so the normalization starts over."""
        with self.lock:
            self.filter_on = on
            self.speech_db.clear()
            self.ref_db = None
            self.model.reset()
            self.prev_speech = False

    def _update_ref(self):
        if len(self.speech_db) < NORM_MIN_WINDOWS:
            return
        p = float(np.percentile(self.speech_db, NORM_PERCENTILE))
        if self.ref_db is None:
            self.ref_db = p
            return
        tc = NORM_ATTACK_S if p > self.ref_db else NORM_RELEASE_S
        self.ref_db += (p - self.ref_db) * min(1.0, (WINDOW / SR) / tc)

    @property
    def latency_ms(self):
        return self.mic_ms + self.window_ms + self.compute_ms

    def due(self, until):
        """Pops and returns the events captured at or before `until`."""
        out = []
        with self.lock:
            while self.events and self.events[0][0] <= until:
                out.append(self.events.popleft())
        return out


class Kitt(QWidget):
    def __init__(self, det, delay_ms):
        super().__init__()
        self.det, self.delay = det, delay_ms / 1000
        self.setWindowTitle("VAD live view")
        self.resize(380, 560)
        self.setStyleSheet("background:#000")
        self.span = DB_CEIL - DB_FLOOR
        self.target_db = -self.span  # level the replay asks for, in dB below the top of the bars (gate closed = bottom)
        self.speech = False
        self.center_db = -self.span
        self.last = time.monotonic()
        self.frames = collections.deque(maxlen=60)  # paint times, for the FPS readout
        self.filter_box = QCheckBox("Filter mains hum  [F]", self)
        self.filter_box.setChecked(det.filter_on)
        self.filter_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.filter_box.setStyleSheet("QCheckBox { color: #aaa; } QCheckBox::indicator { width: 14px; height: 14px; }")
        self.filter_box.toggled.connect(det.set_filter)
        t = QTimer(self)
        t.timeout.connect(self.tick)
        t.start(16)

    def tick(self):
        now = time.monotonic()
        dt, self.last = now - self.last, now
        for _t, speech, db, hi, span in self.det.due(now - self.delay):
            self.speech, self.span = speech, span
            self.target_db = max(db - hi, -span) if speech else -span
        self.center_db = self._ballistics(self.center_db, self.target_db, dt, ATTACK_S, RELEASE_DB_S)
        self.update()

    @staticmethod
    def _ballistics(cur, target, dt, attack_s, release_db_s):
        """Quick exponential rise, linear-in-dB fall."""
        if target > cur:
            return cur + (target - cur) * min(1.0, dt / attack_s)
        return max(target, cur - release_db_s * dt)

    def fps(self):
        f = self.frames
        return (len(f) - 1) / (f[-1] - f[0]) if len(f) > 2 and f[-1] > f[0] else 0.0

    def resizeEvent(self, _):
        self.filter_box.adjustSize()
        self.filter_box.move(28, self.height() - self.filter_box.height() - 8)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Q):
            self.close()
        elif e.key() == Qt.Key.Key_F:
            self.filter_box.toggle()
        elif e.key() == Qt.Key.Key_N:
            self.det.norm = not self.det.norm

    def paintEvent(self, _):
        self.frames.append(time.monotonic())
        g = QPainter(self)
        g.fillRect(self.rect(), QColor(0, 0, 0))
        w, h = self.width(), self.height()
        foot = 140
        top, bottom = 24, h - foot - 12
        gap, colgap = 4, 22
        colw = (w - 2 * 28 - 2 * colgap) / 3
        rowh = (bottom - top - gap * (ROWS - 1)) / ROWS
        mid = ROWS // 2
        frac_of = lambda db: min(max(1 + db / self.span, 0.0), 1.0)
        mid_col = frac_of(self.center_db)
        side = SIDE_SCALE * mid_col
        for c, lvl in enumerate((side, mid_col, side)):
            x = 28 + c * (colw + colgap)
            lit = lvl * (mid + 0.999)  # rows lit each side of the middle
            for r in range(ROWS):
                dist = abs(r - mid)
                y = top + r * (rowh + gap)
                if dist < lit:
                    k = 1.0 - 0.38 * dist / mid
                    col = QColor(int(255 * k), int(8 * k), int(8 * k))
                else:
                    col = QColor(24, 24, 24)
                g.fillRect(QRectF(x, y, colw, rowh), col)
        d = self.det
        g.setFont(QFont("monospace", 10))
        g.setPen(QColor(255, 60, 60) if self.speech else QColor(110, 110, 110))
        g.drawText(28, h - foot + 6, w - 56, 18, Qt.AlignmentFlag.AlignLeft,
                   "SPEECH" if self.speech else "silence")
        g.setPen(QColor(100, 100, 100))
        g.drawText(28, h - foot + 6, w - 56, 18, Qt.AlignmentFlag.AlignRight,
                   f"level {d.live_db:5.1f} dBFS" + (f" (>{local_stt.VAD_HIGHPASS_HZ} Hz)" if d.filter_on else " (unfiltered)"))
        bx, by, bw, bh = 28, h - foot + 30, w - 56, 6
        g.fillRect(QRectF(bx, by, bw, bh), QColor(28, 28, 28))
        frac = lambda db: min(max((db + 60) / 60, 0.0), 1.0)
        g.fillRect(QRectF(bx, by, bw * frac(d.live_db), bh), QColor(120, 120, 120))
        g.fillRect(QRectF(bx + bw * frac(d.peak_db) - 1, by - 2, 2, bh + 4), QColor(190, 190, 190))
        late = d.latency_ms > self.delay * 1000
        g.setPen(QColor(200, 150, 40) if late else QColor(100, 100, 100))
        g.drawText(28, by + 12, w - 56, 18, Qt.AlignmentFlag.AlignLeft,
                   f"latency {d.latency_ms:3.0f} ms   replay +{self.delay * 1000:.0f} ms"
                   + ("  (too short)" if late else ""))
        g.setFont(QFont("monospace", 8))
        g.setPen(QColor(100, 100, 100))
        g.drawText(28, by + 30, w - 56, 14, Qt.AlignmentFlag.AlignLeft,
                   f"= mic {d.mic_ms:.0f} + window {d.window_ms:.0f} + detect {d.compute_ms:.0f} ms")
        g.drawText(28, by + 30, w - 56, 14, Qt.AlignmentFlag.AlignRight,
                   f"{self.fps():.0f} fps")
        if d.norm and d.ref_db is not None:
            msg = f"normalizing: p90 of last {len(d.speech_db) * WINDOW / SR:.0f} s speech = {d.ref_db:.1f} dBFS"
        elif d.norm:
            msg = "normalizing: waiting for speech (fixed range)"
        else:
            msg = "fixed range -50..-10 dBFS"
        g.drawText(28, by + 46, w - 56, 14, Qt.AlignmentFlag.AlignLeft, msg + "   [N] toggle")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=140, help="replay delay in ms (keep above the latency shown)")
    ap.add_argument("--wav", help="replay a 16 kHz mono clip in real time instead of using the microphone")
    args = ap.parse_args()
    import sounddevice as sd
    import core
    core._select_microphone()
    det = Detector()
    app = QApplication(sys.argv[:1])
    win = Kitt(det, args.delay)
    win.show()
    if args.wav:
        import wave
        w = wave.open(args.wav)
        pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16)

        def play():
            while True:
                for i in range(0, len(pcm) - WINDOW + 1, WINDOW):
                    det.feed(pcm[i:i + WINDOW, None])
                    time.sleep(WINDOW / SR)
                time.sleep(1.0)
        det.mic_ms = 0.0
        threading.Thread(target=play, daemon=True).start()
        app.exec()
        return
    with sd.InputStream(samplerate=SR, channels=1, dtype="int16", blocksize=WINDOW, callback=det.feed) as stream:
        det.mic_ms = 1000 * stream.latency
        app.exec()


if __name__ == "__main__":
    main()
