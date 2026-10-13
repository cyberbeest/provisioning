"""Window for the last recording: waveform, what the speech detector heard, and
the take's timing, to find out where the start of a dictation got lost.

Time runs from the key press / click that asked for the recording. Whatever
happened before the stream delivered audio (model checks, choosing the
microphone, opening the device) is drawn as the red "not recorded" part."""
import json
import wave

import numpy as np
from PyQt6.QtCore import Qt, QRectF, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

import core
from i18n import _

VAD_FRAME = 320   # samples per speech-mask frame (20 ms at 16 kHz), as in local_stt


def load_last_clip():
    """(int16 samples, sample rate, info dict) of the last clip, or None."""
    try:
        with wave.open(str(core.LAST_CLIP), "rb") as w:
            sr = w.getframerate()
            audio = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    except (OSError, wave.Error):
        return None
    try:
        info = json.loads(core.LAST_CLIP_INFO.read_text())
    except (OSError, ValueError):
        info = {}
    return audio, sr, info


def runs_to_mask(runs, n_frames):
    mask = np.zeros(n_frames, bool)
    for a, b in runs:
        mask[a:b] = True
    return mask


def dbfs(x):
    x = np.asarray(x, np.float32) / 32768.0
    rms = float(np.sqrt(np.mean(x * x))) if len(x) else 0.0
    return 20 * np.log10(rms) if rms > 0 else -120.0


class WaveView(QWidget):
    """Three lanes on one time axis: waveform, speech mask while recording, speech mask over the finished clip."""
    LANES = 3

    def __init__(self, audio, sr, info, clip_mask):
        super().__init__()
        self.setMinimumSize(760, 370)
        self.audio, self.sr = audio, sr
        tm = info.get("timing", {})
        self.tm = tm
        # the clip starts when the stream started; everything before that was never recorded
        self.offset = tm.get("first_block", tm.get("started", 0.0))
        # stretches where the microphone delivered nothing: (samples recorded before the gap, its length in s)
        self.gaps = [(int(a), float(b)) for a, b in tm.get("gaps", [])]
        self.dur = len(audio) / sr + sum(g for _s, g in self.gaps)   # clip length on the wall clock, gaps included
        self.release = tm.get("release")
        self.total = max(self.offset + self.dur, (self.release or 0.0) + 0.2) + 0.1
        n_frames = len(audio) // VAD_FRAME
        runs = info.get("streamed_mask_runs")
        self.streamed = runs_to_mask(runs, n_frames) if runs is not None else None
        self.clip_mask = clip_mask
        self.cursor = None   # playback position in seconds since the clip start
        self._env = None

    def wall(self, i):
        """Seconds since the key press at which sample i was recorded (a gap before i pushes it later)."""
        return self.offset + i / self.sr + sum(g for s, g in self.gaps if s <= i)

    def wall_end(self, i):
        """Same for the end of a stretch that stops at sample i (a gap starting at i comes after it)."""
        return self.offset + i / self.sr + sum(g for s, g in self.gaps if s < i)

    def x_of(self, t):   # seconds since key press -> pixel
        return 100 + (self.width() - 114) * t / self.total

    def envelope(self, a, b, w):
        """Peak level per pixel column for samples a..b."""
        key = (a, b, w)
        if self._env is None:
            self._env = {}
        if key not in self._env:
            x = np.abs(self.audio[a:b].astype(np.float32)) / 32768.0
            edges = np.linspace(0, len(x), w + 1).astype(int)
            self._env[key] = np.array([x[i:j].max() if j > i else 0.0 for i, j in zip(edges[:-1], edges[1:])])
        return self._env[key]

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.fillRect(self.rect(), QColor("#ffffff"))
        small = QFont(self.font())
        small.setPointSizeF(8)
        p.setFont(small)
        top, lane_h, gap = 44, 84, 8
        lanes = [top + i * (lane_h + gap) for i in range(self.LANES)]
        names = [_("Audio"), _("Speech while recording"), _("Speech in the clip")]
        x0, x1 = int(self.x_of(0)), int(self.x_of(self.total))
        for y, name in zip(lanes, names):
            p.fillRect(x0, y, x1 - x0, lane_h, QColor("#f4f4f4"))
            p.setPen(QColor("#555555"))
            p.drawText(QRectF(4, y, 92, lane_h), Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap, name)
        # the time before the stream delivered audio
        xs = int(self.x_of(self.offset))
        if xs > x0:
            for y in lanes:
                p.fillRect(x0, y, xs - x0, lane_h, QColor(255, 80, 80, 70))
        # key still held but no audio coming in
        xe = int(self.x_of(self.offset + self.dur))
        if self.release is not None and self.release - (self.offset + self.dur) > 0.6:
            xr = int(self.x_of(self.release))
            for y in lanes:
                p.fillRect(xe, y, xr - xe, lane_h, QColor(255, 170, 60, 70))
            p.setPen(QColor("#b06a00"))
            p.drawText(QRectF(xe + 4, lanes[0], xr - xe - 8, lane_h), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                       _("no audio arrived"))
        # gaps inside the take
        for s_, g in self.gaps:
            xa, xb = int(self.x_of(self.wall_end(s_))), int(self.x_of(self.wall_end(s_) + g))
            for y in lanes:
                p.fillRect(xa, y, max(xb - xa, 1), lane_h, QColor(255, 170, 60, 110))
            p.setPen(QColor("#b06a00"))
            p.drawText(QRectF(xa - 40, lanes[0] + lane_h - 16, xb - xa + 80, 14), Qt.AlignmentFlag.AlignCenter,
                       _("no audio for {t:.1f} s").format(t=g))
        # waveform, one piece per stretch between the gaps
        mid = lanes[0] + lane_h // 2
        p.setPen(QPen(QColor("#2a6fb0")))
        cuts = [0] + [s_ for s_, _g in self.gaps] + [len(self.audio)]
        for a, b in zip(cuts[:-1], cuts[1:]):
            if b <= a:
                continue
            xa, xb = int(self.x_of(self.wall(a))), int(self.x_of(self.wall_end(b)))
            for i, v in enumerate(self.envelope(a, b, max(xb - xa, 1))):
                h = int(v * lane_h / 2)
                p.drawLine(xa + i, mid - h, xa + i, mid + h)
        # speech masks
        for lane, mask, color in ((1, self.streamed, "#2e9e4f"), (2, self.clip_mask, "#2e9e4f")):
            if mask is None:
                p.setPen(QColor("#999999"))
                p.drawText(QRectF(x0 + 6, lanes[lane], 300, lane_h), Qt.AlignmentFlag.AlignVCenter,
                           _("(not used: the clip was checked afterwards)") if lane == 1 else _("(no speech found)"))
                continue
            for i, on in enumerate(mask):
                if on:
                    a = self.x_of(self.wall(i * VAD_FRAME))
                    b = self.x_of(self.wall_end((i + 1) * VAD_FRAME))
                    p.fillRect(QRectF(a, lanes[lane] + 6, max(b - a, 1), lane_h - 12), QColor(color))
        # markers: key press, stream opened, first audio, release
        marks = [(0.0, _("key"), "#000000"), (self.tm.get("started"), _("stream on"), "#b06a00"),
                 (self.tm.get("first_block"), _("first audio"), "#2a6fb0"), (self.release, _("released"), "#000000")]
        bottom = lanes[-1] + lane_h
        row = 0
        for t, label, color in marks:
            if t is None:
                continue
            x = int(self.x_of(t))
            p.setPen(QPen(QColor(color), 1, Qt.PenStyle.DashLine))
            row_y = 11 + 12 * (row % 3)   # stagger: key, stream on and first audio sit within a few pixels of each other
            p.drawLine(x, row_y + 3, x, bottom)
            p.setPen(QColor(color))
            right = x + 4 + p.fontMetrics().horizontalAdvance(label) > self.width() - 4
            p.drawText(x - 4 - p.fontMetrics().horizontalAdvance(label) if right else x + 4, row_y, label)
            row += 1
        # time axis
        p.setPen(QColor("#555555"))
        step = 0.5 if self.total < 6 else 1.0
        t = 0.0
        while t <= self.total:
            x = int(self.x_of(t))
            p.drawLine(x, bottom, x, bottom + 4)
            p.drawText(x - 10, bottom + 16, f"{t:g}s")
            t += step
        if self.cursor is not None:
            x = int(self.x_of(self.wall(int(self.cursor * self.sr))))
            p.setPen(QPen(QColor("#d00000"), 2))
            p.drawLine(x, top - 6, x, bottom)
        p.end()


def clip_mask_of(audio):
    """The speech mask the trimming would use for this clip (checked the way a take without a streamed mask is)."""
    import local_stt
    try:
        return local_stt.speech_mask(audio.astype(np.float32) / 32768.0)
    except Exception:
        core.log.exception("clip viewer: speech detection failed")
        return None


def describe(audio, sr, info, clip_mask):
    """The numbers and a plain-language reading of them."""
    tm = info.get("timing", {})
    ms = lambda v: f"{v * 1000:.0f} ms"
    lines = []
    if "started" in tm:
        lines.append(_("Key press to recording running: {t}  (model check + microphone choice {a}, opening the device {b})").format(
            t=ms(tm.get("first_block", tm["started"])),
            a=ms(tm.get("mic_selected", 0) - 0), b=ms(tm.get("started", 0) - tm.get("mic_selected", 0))))
        lines.append(_("First audio block {a} after the stream started; longest gap between blocks {b}; overflow reports {c}").format(
            a=ms(tm.get("first_block", tm["started"]) - tm["started"]), b=ms(tm.get("max_gap", 0.0)), c=tm.get("overflows", 0)))
    first = int(np.argmax(clip_mask)) * VAD_FRAME / sr if clip_mask is not None and clip_mask.any() else None
    head = dbfs(audio[: int(0.2 * sr)])
    lines.append(_("Clip {d:.1f} s, level of the first 200 ms {h:.0f} dBFS, first speech at {f}").format(
        d=len(audio) / sr, h=head, f=f"{first:.2f} s" if first is not None else _("never")))
    # reading
    lead = tm.get("first_block", tm.get("started", 0.0))
    tail = tm.get("release", 0.0) - tm.get("last_block", 0.0) if "last_block" in tm and "release" in tm else 0.0
    if tail > 0.6:   # the 0.25 s of trailing audio taken after the key is up is normal
        lines.append(_("Reading: audio stopped arriving {t} before the key was released; the microphone stalled and the rest of the take is missing.").format(t=ms(tail)))
    elif lead > 0.35:
        lines.append(_("Reading: recording only started {t} after the key press; words spoken in that time are lost.").format(t=ms(lead)))
    elif first is not None and first < 0.05 and head > -45:
        lines.append(_("Reading: speech is already loud at the very start of the clip, so the first word began before the recording did."))
    elif tm.get("max_gap", 0.0) > 0.3:
        lines.append(_("Reading: the microphone delivered audio with a gap of {t}, so something was missing mid-take.").format(t=ms(tm["max_gap"])))
    else:
        lines.append(_("Reading: the recording itself looks complete; if a word is missing in the text, look at the speech lanes."))
    return lines


class ClipViewer(QWidget):
    def __init__(self, play=True):
        super().__init__()
        self.setWindowTitle(_("Last recording"))
        loaded = load_last_clip()
        lay = QVBoxLayout(self)
        if loaded is None:
            lay.addWidget(QLabel(_("No recording yet")))
            return
        audio, sr, info = loaded
        self.clip_mask = clip_mask_of(audio)
        self.view = WaveView(audio, sr, info, self.clip_mask)
        lay.addWidget(self.view)
        for line in describe(audio, sr, info, self.clip_mask):
            lab = QLabel(line)
            lab.setWordWrap(True)
            lay.addWidget(lab)
        row = QHBoxLayout()
        self.btn = QPushButton(_("Play"))
        self.btn.clicked.connect(self.play)
        close = QPushButton(_("Close"))
        close.clicked.connect(self.close)
        row.addWidget(self.btn)
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)
        self._dur = len(audio) / sr
        self._t = QTimer(self)
        self._t.timeout.connect(self._tick)
        self._elapsed = 0.0
        if play:
            self.play()

    def play(self):
        if core.replay_last_clip():
            self._elapsed = 0.0
            self._t.start(40)

    def _tick(self):
        self._elapsed += 0.04
        if self._elapsed > self._dur:
            self._t.stop()
            self.view.cursor = None
        else:
            self.view.cursor = self._elapsed
        self.view.update()

    def closeEvent(self, event):
        self._t.stop()
        super().closeEvent(event)
