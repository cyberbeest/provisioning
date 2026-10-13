#!/usr/bin/env python3
"""Dictate GUI — PyQt6 tray app for voice dictation via Groq Whisper."""
import fcntl
import logging
import math
import os
import sys
import threading
import time

import numpy as np
from PyQt6.QtCore import Qt, QObject, QPoint, QPointF, QRect, QRectF, QTimer, QLibraryInfo, QLocale, QTranslator, pyqtSignal, pyqtSlot
from PyQt6.QtDBus import QDBusConnection
from PyQt6.QtGui import (QAction, QActionGroup, QBitmap, QColor, QCursor, QFont, QFontMetrics, QIcon, QImage,
                         QPainter, QPixmap, QRegion)
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu,
    QMessageBox, QPushButton, QSpinBox, QSystemTrayIcon, QTextEdit,
    QVBoxLayout, QWidget,
)
from pynput import keyboard

import core
from i18n import _, set_language


def _make_listener(on_press, on_release):
    """Prefer evdev (works on Wayland+Xorg); fall back to pynput on failure."""
    try:
        import evdev_listener
        l = evdev_listener.Listener(on_press=on_press, on_release=on_release)
        l.start()
        print("keyboard listener: evdev", file=sys.stderr)
        return l
    except Exception as e:
        print(f"evdev unavailable ({e}); falling back to pynput", file=sys.stderr)
        l = keyboard.Listener(on_press=on_press, on_release=on_release)
        l.daemon = True
        l.start()
        return l


class Bridge(QObject):
    hotkey_press = pyqtSignal()
    hotkey_release = pyqtSignal()
    other_press = pyqtSignal()
    transcribed = pyqtSignal(str, object)   # text, window to type into (see core.paste_target)
    error = pyqtSignal(str)
    paste_failed = pyqtSignal(str)
    model_progress = pyqtSignal(str)
    model_done = pyqtSignal(bool, str)


class SettingsDialog(QDialog):
    # Bridge signals for the background model-download thread.
    _dl_status = pyqtSignal(str)
    _dl_done = pyqtSignal(bool, str)

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Dictate — Settings"))
        self.setMinimumWidth(460)
        self.cfg = dict(cfg)

        self.form = QFormLayout()

        self.mode_box = QComboBox()
        self.mode_box.addItem(_("Push-to-talk (hold key)"), "ptt")
        self.mode_box.addItem(_("Toggle (tap to start, tap to stop)"), "toggle")
        i = self.mode_box.findData(self.cfg.get("mode", "ptt"))
        self.mode_box.setCurrentIndex(max(i, 0))
        self.form.addRow(_("Mode:"), self.mode_box)

        self.key_box = QComboBox()
        for k in core.KEY_MAP:
            self.key_box.addItem(k.upper().replace("_", " "), k)
        i = self.key_box.findData(self.cfg.get("key", "f9"))
        self.key_box.setCurrentIndex(max(i, 0))
        self.form.addRow(_("Hotkey:"), self.key_box)

        self.input_box = QComboBox()
        self.input_box.addItem(_("Automatic"), "")
        for name, desc in core.list_input_sources():
            self.input_box.addItem(desc, name)
        i = self.input_box.findData(self.cfg.get("input_source", ""))
        if i < 0:   # chosen microphone is unplugged right now: keep the choice visible
            self.input_box.addItem(_("{name} (not connected)").format(name=self.cfg["input_source"]), self.cfg["input_source"])
            i = self.input_box.count() - 1
        self.input_box.setCurrentIndex(i)
        self.form.addRow(_("Microphone:"), self.input_box)

        import local_stt
        self.model_box = QComboBox()
        self.model_box.addItem(_("German only (faster)"), "nemo-de-fastconformer-int8")
        self.model_box.addItem(_("Multi-language (slower)"), "parakeet-primeline-int8")
        i = self.model_box.findData(self.cfg.get("model", local_stt.DEFAULT_MODEL))
        self.model_box.setCurrentIndex(max(i, 0))
        self.model_box.currentIndexChanged.connect(self._refresh_local_status)
        self.form.addRow(_("Speech model:"), self.model_box)

        import os as _os
        cpu_max = max(1, _os.cpu_count() or 1)
        self.local_status_label = QLabel()
        self.form.addRow(_("Local model:"), self.local_status_label)
        self.local_download_btn = QPushButton()
        self.local_download_btn.clicked.connect(self.on_download_model)
        self.form.addRow("", self.local_download_btn)
        self.local_threads_box = QSpinBox()
        self.local_threads_box.setRange(1, cpu_max)
        self.local_threads_box.setValue(int(self.cfg.get("local_stt_num_threads", min(4, cpu_max))))
        self.local_threads_box.setToolTip(_(
            "sherpa-onnx CPU thread count. 4 = best latency/resource balance on\n"
            "this system; more brings little. Changing this rebuilds the recognizer."
        ))
        self.form.addRow(_("CPU threads:"), self.local_threads_box)
        self.local_idle_box = QSpinBox()
        self.local_idle_box.setRange(0, 240)
        self.local_idle_box.setSuffix(_(" min"))
        self.local_idle_box.setSpecialValueText(_("Never"))
        self.local_idle_box.setValue(int(self.cfg.get("local_stt_idle_minutes", 5)))
        self.local_idle_box.setToolTip(_(
            "Unload the model after this long without a dictation to free about\n"
            "800 MB of RAM. It reloads (about 10 s on a slow CPU) when you next\n"
            "press the hotkey, while you are speaking."
        ))
        self.form.addRow(_("Unload when idle:"), self.local_idle_box)

        self.meter_box = QCheckBox(_("Show a level meter while dictating"))
        self.meter_box.setChecked(bool(self.cfg.get("recording_meter", True)))
        self.meter_box.setToolTip(_("A small meter in the top right corner that moves while the program hears you speak.\nClick it to stop dictating."))
        self.form.addRow("", self.meter_box)
        self.notify_box = QCheckBox(_("Show a notification while dictating"))
        self.notify_box.setChecked(bool(self.cfg.get("dictation_notifications", True)))
        self.notify_box.setToolTip(_("\"Speak now\" while you hold the key, then \"Transcribing\" until the text is typed."))
        self.form.addRow("", self.notify_box)
        self.hum_box = QCheckBox(_("Filter mains hum"))
        self.hum_box.setChecked(bool(self.cfg.get("vad_highpass", True)))
        self.hum_box.setToolTip(_(
            "Mains hum (a low buzz, often from the charger) can hide quiet words from the\n"
            "speech detector, so they get cut out. This hides everything below 150 Hz from the\n"
            "detector only; the recording itself is not changed."
        ))
        self.form.addRow("", self.hum_box)
        self.autostart_box = QCheckBox(_("Start Dictate when I log in"))
        self.autostart_box.setChecked(core.autostart_enabled())
        self.form.addRow("", self.autostart_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(self.form)

        self.hint = QLabel(_(
            "Runs entirely on this computer: your voice is never sent anywhere. "
            "German only: NVIDIA stt_de_fastconformer_hybrid_large_pc. "
            "Multi-language: primeline parakeet, based on NVIDIA Parakeet. Both CC-BY-4.0, "
            "converted to ONNX int8 and run with "
            "<a href='https://github.com/k2-fsa/sherpa-onnx'>sherpa-onnx</a>."
        ))
        self.hint.setOpenExternalLinks(True)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #777; padding: 6px 0;")
        layout.addWidget(self.hint)

        layout.addWidget(buttons)

        # Wire the download-worker bridge, then show the selected model's state.
        self._dl_status.connect(self.local_status_label.setText)
        self._dl_done.connect(self._on_download_done)
        self._refresh_local_status()

    def _selected_model(self):
        return self.model_box.currentData()

    def _refresh_local_status(self):
        import local_stt
        mid = self._selected_model()
        mb = local_stt._spec(mid)["size_mb"]
        self.local_download_btn.setText(_("Download model (~{mb} MB)").format(mb=mb))
        if local_stt.model_installed(mid):
            self.local_status_label.setText(_("Installed and ready."))
            self.local_download_btn.setEnabled(False)
        else:
            self.local_status_label.setText(_("Not installed. It is downloaded when you first dictate."))
            self.local_download_btn.setEnabled(True)

    def on_download_model(self):
        self.local_download_btn.setEnabled(False)
        self.local_download_btn.setText(_("Downloading..."))
        self.local_status_label.setText(_("Starting download..."))
        self._download_model_id = self._selected_model()
        threading.Thread(target=self._download_worker, daemon=True).start()

    def _download_worker(self):
        try:
            import local_stt
            local_stt.download_model(progress_cb=lambda m: self._dl_status.emit(m),
                                     model_id=self._download_model_id)
            self._dl_done.emit(True, _("Installed."))
        except Exception as e:
            self._dl_done.emit(False, _("Download failed: {err}").format(err=e))

    def _on_download_done(self, ok, msg):
        self.local_status_label.setText(msg)
        self._refresh_local_status()
        if not ok:
            self.local_download_btn.setText(_("Retry download"))

    def values(self):
        return {
            "mode":                  self.mode_box.currentData(),
            "key":                   self.key_box.currentData(),
            "input_source":          self.input_box.currentData(),
            "model":                 self.model_box.currentData(),
            "local_stt_num_threads": int(self.local_threads_box.value()),
            "local_stt_idle_minutes": int(self.local_idle_box.value()),
            "dictation_notifications": self.notify_box.isChecked(),
            "recording_meter":       self.meter_box.isChecked(),
            "vad_highpass":          self.hum_box.isChecked(),
            "autostart":             self.autostart_box.isChecked(),
        }


def make_mic_icon(color="#2b2b2b", outline=False, ring=None):
    """Microphone icon: solid body, or just an outline when `outline` is set.

    `ring` (0..1) adds a fading circle around the body, expanding as it grows;
    cycling it gives the pulse shown while recording or transcribing.
    """
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if ring is not None:
        halo = QColor(color)
        halo.setAlphaF(0.85 * (1.0 - ring))
        halo_pen = p.pen()
        halo_pen.setColor(halo)
        halo_pen.setWidth(4)
        p.setPen(halo_pen)
        p.setBrush(Qt.GlobalColor.transparent)
        r = 12 + 18 * ring
        p.drawEllipse(QPointF(32, 30), r, r)
    if outline:
        p.setBrush(Qt.GlobalColor.transparent)
        body_pen = p.pen()
        body_pen.setColor(QColor(color))
        body_pen.setWidth(4)
        p.setPen(body_pen)
        p.drawRoundedRect(24, 10, 16, 28, 8, 8)
    else:
        p.setBrush(QColor(color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(22, 8, 20, 32, 10, 10)
    p.setPen(QColor(color))
    p.setBrush(Qt.GlobalColor.transparent)
    pen = p.pen()
    pen.setWidth(4)
    p.setPen(pen)
    p.drawArc(16, 28, 32, 24, 0, -180 * 16)
    p.drawLine(32, 50, 32, 58)
    p.drawLine(22, 58, 42, 58)
    p.end()
    return QIcon(pix)


# The base NVIDIA Parakeet TDT 0.6B v3 model's languages (the multi-language
# model is a German-optimised fine-tune of it); translated as one string so
# each language has its own alphabetical order.
LANGUAGE_LIST_EN = ("Supported languages: Bulgarian, Croatian, Czech, Danish, Dutch, English, "
                    "Estonian, Finnish, French, German, Greek, Hungarian, Italian, Latvian, "
                    "Lithuanian, Maltese, Polish, Portuguese, Romanian, Russian, Slovak, "
                    "Slovenian, Spanish, Swedish, Ukrainian")


LAST_TRANSCRIPT_MINUTES = 5


CANCELLED = object()   # stands in for the target window of a dictation the user cancelled


class DictationNote:
    """One notification that follows a dictation: "Speak now" while the key is
    held, then "Transcribing ...", closed when the text is ready. Showing it
    runs on a thread so pressing the hotkey never waits for the notification
    daemon; update() and close() must not be called from the GUI thread."""

    active = {}   # notification id -> DictationNote, so a click can find its dictation

    def __init__(self, msg):
        self.id = None
        self.cancelled = threading.Event()   # the user clicked: do not paste this dictation
        self._thread = threading.Thread(target=self._show, args=(msg,), daemon=True)
        self._thread.start()

    def _show(self, msg):
        self.id = core.notify_sticky(msg)

    def update(self, msg, cancellable=False):
        """cancellable: the notification can be clicked to cancel the pasting."""
        self._thread.join()
        if self.cancelled.is_set():
            return   # the user dismissed it: it must not come back
        self.id = core.notify_sticky(
            msg, replace_id=self.id, action=_("Cancel") if cancellable else None)
        if self.id is not None:
            DictationNote.active[self.id] = self

    def close(self):
        self._thread.join()
        DictationNote.active.pop(self.id, None)
        core.close_notification(self.id)



class MeterWindow(QWidget):
    """Small K.I.T.T.-style window while recording: "Speak now" and a level meter.
    The window has exactly the shape of what is drawn (a window mask: a pixel is there
    or it is not, no partial transparency, which would need a compositor): every letter
    and every lit LED has a one pixel outline and the desktop shows through everywhere
    else. LEDs that are not lit are not there at all (SHOW_UNLIT).
    Three columns of red LEDs grow from the middle; they stay empty unless the voice
    detector hears speech, and then follow the loudness. Never takes the keyboard focus
    (the text goes to the window that had it). After a click on the tray icon it sits
    right under the icon and has a Stop button; after the hotkey it sits in the top
    right corner and a click on it stops the dictation."""

    ROWS = 11
    ATTACK_S = 0.025
    RELEASE_DB_S = 100.0
    SIDE_SCALE = 0.5
    SHOW_UNLIT = False
    LED_W, LED_H, PITCH, COL_GAP = 14, 7, 10, 6   # LED size inside its outline, row pitch, gap between columns
    LABEL_H = 34
    MIN_WIDTH = 112
    LABEL_PT = 15
    PULSE_S = 1.1                       # one slow pulse of the label's red
    PULSE_DARK, PULSE_LIGHT = QColor(185, 15, 15), QColor(255, 85, 60)
    METER_H = 2 + ROWS * PITCH + 4
    OUTLINE = QColor(240, 240, 240)     # around the letters
    LED_OUTLINE = QColor(0, 0, 0)       # around the LEDs

    def __init__(self, on_click):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._w = self.MIN_WIDTH
        self.setFixedSize(self._w, self.LABEL_H + self.METER_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(_("Click to stop dictating"))
        self._on_click = on_click
        self._with_button = False
        self.stop_btn = QPushButton(_("Stop"), self)
        self.stop_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.stop_btn.setStyleSheet("QPushButton { background: #b01010; color: white; border: none; padding: 3px 0; }"
                                    "QPushButton:hover { background: #d32f2f; }")
        self.stop_btn.clicked.connect(on_click)
        self.stop_btn.hide()
        self._meter = None
        self._level = 0.0     # dB below the top of the bars
        self._span = 40.0
        self._last = 0.0
        self._label = None    # (text, image, region): the outlined "Speak now"
        self._label_images = {}   # pulse step -> image
        self._mask_key = None
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    # -- shapes ---------------------------------------------------------------
    def _render_label(self, text, color):
        font = QFont(self.font())
        font.setPointSize(self.LABEL_PT)
        font.setBold(True)
        fm = QFontMetrics(font)
        w, h = fm.horizontalAdvance(text) + 8, fm.height() + 4
        img = QImage(w, h, QImage.Format.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        p.setFont(font)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, False)   # crisp glyphs: every pixel is in or out
        box = QRect(4, 2, w - 8, h - 4)
        p.setPen(self.OUTLINE)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx or dy:
                    p.drawText(box.translated(dx, dy), Qt.AlignmentFlag.AlignCenter, text)
        p.setPen(color)
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        p.end()
        return img

    def _label_parts(self):
        """(text, image, region) of the outlined label; the region does not depend on the colour."""
        text = _("Speak now")
        if self._label is None or self._label[0] != text:
            img = self._render_label(text, self.PULSE_DARK)
            self._label = (text, img, QRegion(QBitmap.fromImage(img.createAlphaMask())))
            self._label_images = {}
        return self._label

    PULSE_STEPS = 12

    def _label_image(self):
        """The label in the current colour of its pulse (images cached per step)."""
        text = self._label_parts()[0]
        phase = 0.5 - 0.5 * math.cos(2 * math.pi * time.monotonic() / self.PULSE_S)
        step = int(phase * (self.PULSE_STEPS - 1) + 0.5)
        img = self._label_images.get(step)
        if img is None:
            k, d, l = step / (self.PULSE_STEPS - 1), self.PULSE_DARK, self.PULSE_LIGHT
            img = self._render_label(text, QColor(*(int(d.getRgb()[i] + (l.getRgb()[i] - d.getRgb()[i]) * k) for i in range(3))))
            self._label_images[step] = img
        return img

    def _label_pos(self):
        img = self._label_parts()[1]
        return QPoint((self._w - img.width()) // 2, max(0, (self.LABEL_H - img.height()) // 2))

    def _led_rect(self, c, r):
        """Outer rectangle (outline included) of the LED in column c, row r."""
        cw = self.LED_W + 2
        x0 = (self._w - (3 * cw + 2 * self.COL_GAP)) // 2
        return QRect(x0 + c * (cw + self.COL_GAP), self.LABEL_H + 2 + r * self.PITCH, cw, self.LED_H + 2)

    def _lit(self):
        """Number of lit rows on each side of the middle, per column (left, middle, right)."""
        mid = self.ROWS // 2
        frac = min(max(1 + self._level / self._span, 0.0), 1.0)
        out = []
        for lvl in (frac * self.SIDE_SCALE, frac, frac * self.SIDE_SCALE):
            lit = lvl * (mid + 0.999)
            out.append(sum(1 for r in range(self.ROWS) if abs(r - mid) < lit))
        return out

    def _rows_shown(self, count):
        mid = self.ROWS // 2
        n = (count - 1) // 2   # rows lit on each side of the middle row
        if self.SHOW_UNLIT:
            return range(self.ROWS)
        return range(mid - n, mid + n + 1) if count else range(0)

    def _update_mask(self):
        key = (tuple(self._lit()), self._with_button, self._label_parts()[0])
        if key == self._mask_key:
            return
        self._mask_key = key
        region = self._label_parts()[2].translated(self._label_pos())
        for c, count in enumerate(self._lit()):
            for r in self._rows_shown(count):
                region = region.united(QRegion(self._led_rect(c, r)))
        if self._with_button:
            region = region.united(QRegion(self.stop_btn.geometry()))
        self.setMask(region)

    # -- show / hide ------------------------------------------------------------
    def start(self, meter, with_button=False, below=None):
        """with_button: also show a Stop button under the bars (a dictation started by a click).
        below: the tray icon's rectangle (or the click position) to sit under; None = top right corner."""
        self._meter = meter
        self._level = -meter.scale()[1]
        self._span = meter.scale()[1]
        self._last = time.monotonic()
        self._with_button = with_button
        self._mask_key = None
        self._w = max(self.MIN_WIDTH, self._label_parts()[1].width() + 12)
        self.setFixedSize(self._w, self.LABEL_H + self.METER_H + (30 if with_button else 0))
        self.stop_btn.setVisible(with_button)
        self.stop_btn.setGeometry(8, self.LABEL_H + self.METER_H, self.width() - 16, 22)
        self._update_mask()
        self._place(below)
        self.show()
        self._timer.start()

    def stop(self):
        self._timer.stop()
        self._meter = None
        self.hide()

    def _place(self, below):
        """Under the icon, centred on it (above it if the icon is in the lower half of the screen);
        without an icon position, the top right corner."""
        screen = (QApplication.screenAt(below.center()) if below is not None else None) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        if below is None:
            self.move(area.right() - self.width() - 16, area.top() + 16)
            return
        x = below.center().x() - self.width() // 2
        if below.center().y() < area.center().y():
            y = below.bottom() + 4
        else:
            y = below.top() - self.height() - 4
        self.move(min(max(x, area.left() + 4), area.right() - self.width() - 4),
                  min(max(y, area.top() + 4), area.bottom() - self.height() - 4))

    def _tick(self):
        m = self._meter
        if m is None:
            return
        now = time.monotonic()
        dt, self._last = now - self._last, now
        top, span = m.scale()
        target = max(m.level_db - top, -span) if m.speech else -span
        if target > self._level:
            self._level += (target - self._level) * min(1.0, dt / self.ATTACK_S)
        else:
            self._level = max(target, self._level - self.RELEASE_DB_S * dt)
        self._span = span
        self._update_mask()
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and not self._with_button:
            self._on_click()

    def paintEvent(self, event):
        g = QPainter(self)
        g.fillRect(self.rect(), self.LED_OUTLINE)   # what the mask keeps and nothing draws over is an LED's outline
        # The label's own area is filled with its outline color first: the mask can keep pixels
        # the text image leaves clear, and those must not turn up as black specks.
        g.save()
        g.setClipRegion(self._label_parts()[2].translated(self._label_pos()))
        g.fillRect(self.rect(), self.OUTLINE)
        g.restore()
        g.drawImage(self._label_pos(), self._label_image())
        mid = self.ROWS // 2
        for c, count in enumerate(self._lit()):
            for r in self._rows_shown(count):
                dist = abs(r - mid)
                if (count - 1) // 2 >= dist and count:
                    k = 1.0 - 0.38 * dist / mid
                    col = QColor(int(255 * k), int(8 * k), int(8 * k))
                else:
                    col = QColor(30, 30, 30)
                g.fillRect(self._led_rect(c, r).adjusted(1, 1, -1, -1), col)


class TestDictationDialog(QDialog):
    """A focused text box to try dictation in, with the hotkey instructions."""

    def __init__(self, help_lines, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Dictate — Test dictation"))
        self.setMinimumSize(460, 260)
        layout = QVBoxLayout(self)
        hint = QLabel("\n".join(help_lines))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.edit = QTextEdit()
        self.edit.setPlaceholderText(_("Your dictation appears here."))
        layout.addWidget(self.edit)
        row = QHBoxLayout()
        row.addStretch()
        clear_btn = QPushButton(_("Clear"))
        close_btn = QPushButton(_("Close"))
        # xdotool types into the focused window; if that is this one, a space
        # or Enter in the dictated text would "press" a focused button.
        for b in (clear_btn, close_btn):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            row.addWidget(b)
        clear_btn.clicked.connect(self.edit.clear)
        close_btn.clicked.connect(self.close)
        layout.addLayout(row)


class LastTranscriptDialog(QDialog):
    """The most recent dictation, for copying when it landed in the wrong place."""

    def __init__(self, text, on_clear, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Dictate — Last transcript"))
        self.setMinimumSize(460, 220)
        layout = QVBoxLayout(self)
        # Editable, so a misheard word can be fixed before copying the text out.
        self.edit = QTextEdit()
        self.edit.setPlainText(text)
        layout.addWidget(self.edit)
        row = QHBoxLayout()
        row.addStretch()
        copy_btn = QPushButton(_("Copy"))
        clear_btn = QPushButton(_("Clear"))
        close_btn = QPushButton(_("Close"))
        # xdotool types into the focused window; if that is this one, a space
        # or Enter in the dictated text would "press" a focused button.
        for b in (copy_btn, clear_btn, close_btn):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            row.addWidget(b)
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(self.edit.toPlainText()))
        clear_btn.clicked.connect(on_clear)
        close_btn.clicked.connect(self.close)
        layout.addLayout(row)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dictate")
        self.setWindowIcon(make_mic_icon())

        self.cfg = core.load_config()
        self.recorder = core.Recorder()
        self.bridge = Bridge()
        self.bridge.hotkey_press.connect(self.on_press)
        self.bridge.hotkey_release.connect(self.on_release)
        self.bridge.other_press.connect(self.on_other_press)
        self.bridge.transcribed.connect(self.on_transcribed)
        self.bridge.error.connect(self.on_error)
        QDBusConnection.sessionBus().connect(
            "org.freedesktop.Notifications", "/org/freedesktop/Notifications",
            "org.freedesktop.Notifications", "ActionInvoked", self.on_notification_action)
        self.bridge.paste_failed.connect(self.keep_in_test_window)
        self.bridge.model_progress.connect(lambda m: self.set_status("transcribing", m))
        self.bridge.model_done.connect(self.on_model_done)
        self._model_downloading = False
        self._download_event = None     # set when the running download has finished
        self._waiting_dictations = 0    # recordings waiting for that download
        self.key_held = False
        self.combo = False
        self.recording_active = False
        self.listener = None
        self._target_keys = set()
        self._last_other = None

        self.press_time = 0.0

        self._meter = None           # LiveMeter feeding the meter window while recording
        self._meter_window = MeterWindow(self.stop_by_click)
        self._click_session = False  # the recording was started by clicking the icon
        self._note = None            # DictationNote of the dictation in progress
        self._target = None          # window the dictation in progress belongs to
        self.last_text = ""          # most recent dictation, kept in memory only
        self._last_dialog = None
        # For privacy the last transcript is forgotten after a while.
        self._clear_timer = QTimer(self)
        self._clear_timer.setSingleShot(True)
        self._clear_timer.setInterval(LAST_TRANSCRIPT_MINUTES * 60 * 1000)
        self._clear_timer.timeout.connect(self.clear_last_transcript)

        self.tray = None
        self._status = ("ready", _("Ready"))
        self._tray_icons = {}
        self._tray_icon_key = None
        self._anim_frame = 0
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(120)
        self._anim_timer.timeout.connect(self._animate_tray)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(make_mic_icon(), self)
            self.tray.setToolTip("Dictate")
            menu = QMenu()
            self.a_hotkey = QAction("", self)
            self.a_hotkey.setCheckable(True)
            self.a_hotkey.triggered.connect(self.set_hotkey_enabled)
            self.a_last = QAction(_("Show last transcript"), self)
            self.a_last.triggered.connect(self.show_last_transcript)
            self.a_replay = QAction(_("Replay last recording"), self)
            self.a_replay.triggered.connect(self.replay_last_recording)
            self.a_test = QAction(_("Test dictation"), self)
            self.a_test.triggered.connect(self.show_test_dictation)
            a_settings = QAction(_("Dictation settings"), self)
            a_settings.triggered.connect(self.open_settings)
            self.a_load = QAction(_("Load dictation model"), self)
            self.a_load.triggered.connect(self.load_model_now)
            self.a_unload = QAction(_("Unload dictation model"), self)
            self.a_unload.triggered.connect(self.unload_model_now)
            a_quit = QAction(_("Quit"), self)
            a_quit.triggered.connect(QApplication.quit)
            menu.addAction(self.a_hotkey)
            menu.addAction(self.a_last)
            menu.addAction(self.a_replay)
            menu.addAction(self.a_test)
            menu.addSeparator()
            menu.addAction(a_settings)
            menu.addSeparator()
            self._model_actions = {}
            group = QActionGroup(self)
            for mid, name in (("nemo-de-fastconformer-int8", _("German only (faster)")),
                              ("parakeet-primeline-int8", _("Multi-language (slower)"))):
                act = QAction(name, self)
                act.setCheckable(True)
                act.setActionGroup(group)
                act.triggered.connect(lambda _checked, m=mid: self.set_model(m))
                menu.addAction(act)
                self._model_actions[mid] = act
            menu.addSeparator()
            menu.addAction(self.a_load)
            menu.addAction(self.a_unload)
            menu.addSeparator()
            menu.addAction(a_quit)
            menu.aboutToShow.connect(self._update_menu)
            self.menu = menu
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(self.on_tray)
            self.tray.show()
            self._tray_timer = QTimer(self)
            self._tray_timer.timeout.connect(self._refresh_tray)
            self._tray_timer.start(2000)

        self.set_status("ready", _("Ready"))
        self.start_listener()

        if not core.model_ready():
            QTimer.singleShot(250, self.first_run)

    def _local_model_available(self) -> bool:
        return core.model_ready()

    def _preload_local_if_needed(self):
        """Kick off the parakeet recognizer load in the background so the first
        real dictation isn't slowed by the ~0.8s model load."""
        if not core.model_ready():
            return
        import local_stt
        local_stt.preload(
            int(self.cfg.get("local_stt_num_threads", local_stt.DEFAULT_THREADS)),
            60 * float(self.cfg.get("local_stt_idle_minutes", 5)),
        )

    def first_run(self):
        QMessageBox.information(
            self,
            _("Welcome to Dictate"),
            _("Dictate needs a speech model to work. Pick one in Settings; it is "
              "downloaded once and then runs entirely on this computer."),
        )
        self.open_settings()

    def _model_label(self):
        return {"nemo-de-fastconformer-int8": _("German only (faster)"),
                "parakeet-primeline-int8": _("Multi-language (slower)")}.get(self.cfg.get("model"), "?")

    def set_model(self, model_id):
        """Switch the speech model from the tray menu."""
        import local_stt
        if model_id == self.cfg.get("model"):
            return
        local_stt.unload()   # free the old model's memory now
        self.cfg["model"] = local_stt.select_model(model_id)
        core.save_config(self.cfg)
        self._refresh_tray()
        if not local_stt.model_installed():
            self._ensure_model()   # starts the one-time download

    def _update_menu(self):
        key = self.cfg["key"].upper().replace("_", " ")
        self.a_hotkey.setText(_("Hotkey {key} enabled").format(key=key))
        self.a_hotkey.setChecked(self.cfg.get("hotkey_enabled", True))
        self.a_last.setEnabled(bool(self.last_text))
        self.a_replay.setEnabled(core.LAST_CLIP.exists())
        for mid, act in self._model_actions.items():
            act.setChecked(mid == self.cfg.get("model"))
        local = self._local_model_available()
        state = "not_loaded"
        if local:
            import local_stt
            state = local_stt.status()
        self.a_load.setVisible(local)
        self.a_unload.setVisible(local)
        self.a_load.setEnabled(state == "not_loaded")
        self.a_unload.setEnabled(state == "loaded")

    def load_model_now(self):
        if self._ensure_model():
            self._preload_local_if_needed()

    def unload_model_now(self):
        import local_stt
        local_stt.unload()
        self._refresh_tray()

    def open_settings(self):
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.cfg.update(dlg.values())
            import local_stt
            if self.cfg["model"] != local_stt._model_id:
                local_stt.unload()
            local_stt.select_model(self.cfg["model"])
            local_stt.set_vad_highpass(self.cfg["vad_highpass"])
            core.set_autostart(self.cfg.pop("autostart"))
            core.save_config(self.cfg)
            self.restart_listener()
            if not local_stt.model_installed():
                self._ensure_model()   # a newly chosen model downloads right away

    def start_listener(self):
        if not self.cfg.get("hotkey_enabled", True):
            return   # hotkey switched off from the tray menu: no key hook at all
        keys = core.KEY_MAP.get(self.cfg["key"])
        if not keys:
            return
        self._target_keys = set(keys)

        def on_press(k):
            try:
                if k in self._target_keys:
                    self.bridge.hotkey_press.emit()
                else:
                    self._last_other = k
                    self.bridge.other_press.emit()
            except Exception:
                pass

        def on_release(k):
            try:
                if k in self._target_keys:
                    self.bridge.hotkey_release.emit()
            except Exception:
                pass

        self.listener = _make_listener(on_press, on_release)

    def set_hotkey_enabled(self, on):
        """Tray menu switch: turns the dictation hotkey on or off."""
        if self.recording_active:
            self._discard_take()
        self.cfg["hotkey_enabled"] = bool(on)
        core.save_config(self.cfg)
        self.restart_listener()
        self.set_status("ready", _("Ready"))

    def clear_last_transcript(self):
        self.last_text = ""
        self._clear_timer.stop()
        if self._last_dialog is not None:
            self._last_dialog.close()
            self._last_dialog = None

    def show_test_dictation(self):
        if getattr(self, "_test_dialog", None) is not None and self._test_dialog.isVisible():
            self._test_dialog.raise_()
            self._test_dialog.activateWindow()
            return
        self._test_dialog = TestDictationDialog(self._help_lines())
        self._test_dialog.show()
        self._test_dialog.raise_()
        self._test_dialog.activateWindow()
        self._test_dialog.edit.setFocus()

    def show_last_transcript(self):
        if not self.last_text:
            return
        if self._last_dialog is not None and self._last_dialog.isVisible():
            self._last_dialog.raise_()
            self._last_dialog.activateWindow()
            return
        self._last_dialog = LastTranscriptDialog(self.last_text, self.clear_last_transcript)
        self._last_dialog.show()
        self._last_dialog.raise_()
        self._last_dialog.activateWindow()

    def replay_last_recording(self):
        """Play the last clip and show it: waveform, what the speech detector heard, and the take's timing."""
        if not core.LAST_CLIP.exists():
            threading.Thread(target=core.notify, args=(_("No recording yet"), "normal", 3000), daemon=True).start()
            return
        import clip_viewer
        if getattr(self, "_clip_viewer", None) is not None:
            self._clip_viewer.close()
        self._clip_viewer = clip_viewer.ClipViewer()
        self._clip_viewer.show()
        self._clip_viewer.raise_()
        self._clip_viewer.activateWindow()

    def restart_listener(self):
        if self.listener:
            self.listener.stop()
            self.listener = None
        self.key_held = False
        self.combo = False
        self.recording_active = False
        self._click_session = False
        self._hide_meter()
        self.start_listener()

    def on_press(self):
        if self.key_held:
            return
        self.key_held = True
        self.combo = False
        if self._click_session and self.recording_active:
            self.stop_by_click()   # started with a click on the icon: the hotkey stops it too
            return
        self.press_time = time.monotonic()
        if self.cfg["mode"] == "ptt":
            if self.start_recording():
                self.recording_active = True
        else:
            if self.recording_active:
                self.stop_and_transcribe()
                self.recording_active = False
            elif self.start_recording():
                self.recording_active = True

    def on_other_press(self):
        if not self.key_held:
            return
        self.combo = True
        # Only abort if this hold started the recording (PTT). In toggle mode
        # a combo while pressing the hotkey shouldn't kill an ongoing session
        # that was started by a previous tap.
        if self.cfg["mode"] == "ptt" and self.recording_active and not self._click_session:
            # Offload PipeWire close to keep the GUI thread responsive.
            self._discard_take()
            self.recording_active = False
            self.set_status("ready", _("Cancelled (combo)"))
            held = time.monotonic() - self.press_time
            core.log.info("cancelled after %.1fs by %s", held, self._last_other)
            # A shortcut like Ctrl+C cancels within a moment and needs no
            # message; a long hold was a dictation that just got thrown away.
            if held >= 1.0:
                core.notify(_("Recording cancelled after {held:.0f}s — another key or mouse button was pressed").format(held=held),
                            urgency="normal", timeout_ms=5000)   # critical never expires

    def on_release(self):
        self.key_held = False
        if self.cfg["mode"] != "ptt":
            return
        if not self.recording_active:
            return
        duration = time.monotonic() - self.press_time
        if duration < core.MIN_HOLD_S:
            # Discard branch also blocks on recorder.stop() → freeze. Offload.
            self._discard_take()
            self.recording_active = False
            self.set_status("ready", _("Discarded (held {duration:.1f}s)").format(duration=duration))
            return
        self.stop_and_transcribe()
        self.recording_active = False

    def _ensure_model(self) -> bool:
        """True if the speech model is on disk. A missing one (profile skipped
        the download, or it failed) is fetched now, once, in the background;
        recordings made meanwhile wait for it and are typed when it arrives."""
        import local_stt
        if local_stt.model_installed():
            return True
        if not self._model_downloading:
            self._model_downloading = True
            self._download_event = threading.Event()
            threading.Thread(target=self._model_download_worker, args=(local_stt,), daemon=True).start()
        return False

    def _model_download_worker(self, local_stt):
        # The notice stays up for the whole download and is taken down at the end.
        note = core.notify_sticky(
            _("Downloading the speech model once (about {mb} MB). Whatever you dictate meanwhile is typed when it is done.").format(
                mb=local_stt._spec()["size_mb"]))
        try:
            local_stt.download_model(progress_cb=self.bridge.model_progress.emit)
            self.bridge.model_done.emit(True, "")
        except Exception as e:
            core.log.exception("model download failed")
            self.bridge.model_done.emit(False, str(e))
        finally:
            core.close_notification(note)
            self._download_event.set()

    def on_model_done(self, ok, err):
        self._model_downloading = False
        if ok:
            if self._waiting_dictations == 0:   # otherwise the typed text says it
                self.set_status("ready", _("Ready"))
                threading.Thread(
                    target=core.notify,
                    args=(_("Speech model ready. Hold {key} and speak.").format(key=self.cfg["key"].upper()),
                          "normal", 4000),
                    daemon=True).start()
        else:
            self.on_error(_("Model download failed: {err}").format(err=err))

    def start_recording(self, click=False) -> bool:
        requested = time.monotonic()
        self._ensure_model()   # a missing model downloads while the user speaks
        # Reload the model if it was unloaded while idle; the load runs while
        # the user speaks. Also restarts the idle countdown.
        self._preload_local_if_needed()
        meter = None
        if self.cfg.get("recording_meter", True) and self._meter_available():
            import local_stt
            meter = local_stt.LiveMeter()
        try:
            self.recorder.start(tap=meter.feed if meter else None, requested=requested)
        except Exception as e:
            core.log.exception("could not open the microphone")
            if meter:
                meter.close()
            self.on_error(_("Microphone: {err}").format(err=e))
            return False
        if meter:
            self._meter = meter   # before the status change below, so the tray tooltip is left alone
            self._meter_window.start(meter, with_button=click, below=self._tray_anchor() if click else None)
        self.set_status("recording", _("Recording..."))
        # The window that has focus now is where this dictation belongs, however
        # long transcribing takes and whatever the user opens or switches to meanwhile.
        self._target = core.paste_target()
        if self.cfg.get("dictation_notifications") and not meter:
            self._note = DictationNote(_("Speak now"))   # with the meter window, "Speak now" is in it
        return True

    def _tray_anchor(self):
        """Rectangle of the tray icon, or of the cursor (it just clicked the icon) when the tray does not tell."""
        r = self.tray.geometry() if self.tray else QRect()
        if r.isValid() and not r.isEmpty():
            return r
        p = QCursor.pos()
        return QRect(p.x() - 12, p.y() - 12, 24, 24)

    def _meter_available(self):
        import local_stt
        return local_stt.VAD_MODEL.exists()

    def _hide_meter(self):
        self._meter_window.stop()
        meter, self._meter = self._meter, None
        if meter:
            meter.close()
            self._refresh_tray()   # the tray tooltip is back

    def stop_by_click(self):
        """Stop the dictation in progress (click on the icon or on the meter, or the hotkey after a click start).
        A second click right on the heels of the first is a double click, not a stop."""
        if not self.recording_active or time.monotonic() - self.press_time < core.MIN_HOLD_S:
            return
        self.stop_and_transcribe()
        self.recording_active = False
        self._click_session = False

    def stop_and_transcribe(self):
        # recorder.stop() can block for hundreds of ms on PipeWire close,
        # which freezes the GUI ("main on_release doesn't return"). Move the
        # whole pipeline (stop + transcribe) onto a worker thread and update
        # status immediately from the main thread instead.
        self.set_status("transcribing", _("Transcribing..."))
        # Detach here, on the GUI thread: the take now belongs to the worker,
        # so pressing the hotkey again right away starts a fresh recording
        # instead of being swallowed by the worker's delayed stop.
        take = self.recorder.detach()
        if take is not None:
            take[1].timing["release"] = time.monotonic()
        note, self._note = self._note, None
        target = self._target
        if note is None and self._meter is not None and self.cfg.get("dictation_notifications"):
            note = DictationNote(self._note_text(target))   # the meter window said "Speak now"; the notification starts here
        self._hide_meter()
        threading.Thread(target=self._stop_and_transcribe_worker, args=(take, note, target), daemon=True).start()

    def _discard_take(self):
        self._hide_meter()
        note, self._note = self._note, None
        if note:
            threading.Thread(target=note.close, daemon=True).start()
        take = self.recorder.detach()
        threading.Thread(target=core.Recorder.finish, args=(take,), daemon=True).start()

    def _note_text(self, target):
        """What the notification says: with a window to type into, the text
        will be pasted; without one it goes to the test window."""
        if not core.model_ready():
            return _("Waiting for the speech model download")
        pasting = target is None or bool(target)
        if self._local_state() == "loaded":
            return _("Transcribing & pasting") if pasting else _("Transcribing")
        return _("Loading speech model, transcribing & pasting") if pasting else _("Loading speech model & transcribing")

    def _stop_and_transcribe_worker(self, take, note, target):
        try:
            self._transcribe_take(take, note, target)
        finally:
            if note:
                note.close()

    def _transcribe_take(self, take, note, target):
        if note:
            note.update(self._note_text(target), cancellable=target != "")   # the key is up: "Speak now" turns into the current step
        # Short trailing buffer: PipeWire has ~50-100ms input latency and
        # people typically finish the last syllable *after* they release the
        # hotkey. Without this the last word tends to get clipped.
        time.sleep(0.25)
        audio, speech = core.Recorder.finish_take(take)
        if audio is None:
            core.log.warning("no audio captured (mic delivered no frames)")
            self.bridge.error.emit(_("No audio captured — check the microphone"))
            return
        core.save_last_clip(audio, take[1].timing, speech)
        secs = len(audio) / core.SAMPLE_RATE
        peak = int(np.abs(audio).max())
        t0 = time.monotonic()
        if not core.model_ready():
            # First use: the model is still downloading. Keep the recording
            # and transcribe it as soon as the download is done.
            self._waiting_dictations += 1
            try:
                if self._download_event is not None:
                    self._download_event.wait()
            finally:
                self._waiting_dictations -= 1
            if not core.model_ready():
                return   # the download failure has already been reported
            if note:
                note.update(self._note_text(target), cancellable=target != "")
        import local_stt
        wait_note = None
        if self._local_model_available() and not note:
            if local_stt.status() != "loaded":
                # Dictation ended before the model finished loading: say why
                # the text is late, and take the message down when it is ready.
                wait_note = core.notify_sticky(
                    _("Loading the speech model, your text follows in a moment..."))
        try:
            text = core.transcribe(audio, self.cfg, speech, note.cancelled if note else None)
        except local_stt.Cancelled:
            core.log.info("transcription of %.1fs audio cancelled after %.1fs", secs, time.monotonic() - t0)
            self.bridge.transcribed.emit("", target)
            return
        except Exception as e:
            core.log.exception("transcribe failed: %.1fs audio, peak %d", secs, peak)
            self.bridge.error.emit(str(e))
            return
        finally:
            core.close_notification(wait_note)
        core.log.info("transcribed %.1fs audio, peak %d, %d chars in %.1fs",
                      secs, peak, len(text or ""), time.monotonic() - t0)
        if not text:
            # Peak is out of 32768; a live mic with speech is in the thousands.
            why = "microphone was silent" if peak < 300 else "no speech recognised"
            core.log.info("nothing transcribed (%.0fs) — %s", secs, why)
            self.bridge.transcribed.emit("", target)
            return
        if note and note.cancelled.is_set():
            target = CANCELLED
        self.bridge.transcribed.emit(text, target)

    def on_transcribed(self, text, target):
        if text and target is CANCELLED:
            self.last_text = text   # kept under "Show last transcript", not pasted
            self._clear_timer.start()
        elif text:
            # A finished sentence gets a trailing space so the next dictation
            # doesn't run into it.
            typed = text + " " if text.endswith((".", "!", "?")) else text
            if target == "":
                self.keep_in_test_window(typed)   # nothing to type into
            else:
                threading.Thread(target=self._paste, args=(typed, target), daemon=True).start()
            self.last_text = text
            self._clear_timer.start()   # restarts the countdown
        self.set_status("ready", _("Ready"))

    @pyqtSlot("uint", "QString")
    def on_notification_action(self, nid, key):
        """The user clicked a Dictate notification: cancel that dictation's pasting."""
        note = DictationNote.active.get(nid)
        if note is not None and key == "default" and not note.cancelled.is_set():
            note.cancelled.set()
            threading.Thread(target=note.close, daemon=True).start()

    def _paste(self, typed, target):
        if not core.type_text(typed, target):
            self.bridge.paste_failed.emit(typed)   # the window is gone: keep the text

    def keep_in_test_window(self, typed):
        """The dictation had nowhere to go: show the test window and put the text there."""
        self.show_test_dictation()
        self._test_dialog.edit.insertPlainText(typed)

    def on_error(self, msg):
        self.set_status("error", _("Error: {msg}").format(msg=msg[:80]))
        # The window is usually hidden in the tray, so the status label alone
        # means the dictation fails without anyone noticing.
        # Normal urgency: notification daemons never expire a "critical" one, whatever -t says.
        threading.Thread(target=core.notify, args=(msg[:200], "normal", 5000), daemon=True).start()

    def set_status(self, state, msg):
        self._status = (state, msg)
        self._refresh_tray()

    def _local_state(self):
        """State of the speech model: not_loaded, loading or loaded."""
        import local_stt
        return local_stt.status()

    def _privacy_line(self):
        """Where the audio goes: the one thing the user must be able to see at a glance."""
        return _("Privacy: local, your voice never leaves this computer")

    def _help_lines(self):
        """How to dictate, as shown in the tooltip and the test window."""
        if not self.cfg.get("hotkey_enabled", True):
            return [_("Dictation is off. Turn the hotkey on in this menu.")]
        key = self.cfg["key"].upper().replace("_", " ")
        german_only = self.cfg.get("model") == "nemo-de-fastconformer-int8"
        if self.cfg.get("mode") == "toggle":
            first = (_("Tap {key} to start and stop dictating in German") if german_only else
                     _("Tap {key} to start and stop dictating in any supported language")).format(key=key)
        else:
            first = (_("Hold {key} to dictate in German") if german_only else
                     _("Hold {key} to dictate in any supported language")).format(key=key)
        lines = [first, _("Or click this icon to start, and click it again to stop")]
        if not german_only:
            import textwrap
            lines += textwrap.wrap(_(LANGUAGE_LIST_EN), width=64)
        return lines

    def _refresh_tray(self):
        if not self.tray:
            return
        state, msg = self._status
        hotkey_on = self.cfg.get("hotkey_enabled", True)
        if not hotkey_on:
            lines = self._help_lines()
        else:
            lines = self._help_lines() if state == "ready" else [_("Dictate — {msg}").format(msg=msg)]
            mstate = self._local_state()
            name = self._model_label()
            if mstate == "loaded":
                lines.append(_("Speech model: {name} (loaded)").format(name=name))
            elif mstate == "loading":
                lines.append(_("Speech model: {name} (loading ...)").format(name=name))
            else:
                lines.append(_("Speech model: {name} (not loaded)").format(name=name))
        lines.append(self._privacy_line())
        # Changing the tooltip text makes the panel show it again, right on top of the meter window
        # that appears under the icon: while the meter is up the text stays as it was.
        if self._meter is None:
            self.tray.setToolTip("\n".join(lines))
        if state in ("recording", "transcribing"):
            icon = "active"
        elif not hotkey_on:
            icon = "off"
        else:
            icon = "idle"
        if icon != self._tray_icon_key:
            self._tray_icon_key = icon
            if icon == "active":
                self._anim_frame = 0
                self._set_active_frame()
                self._anim_timer.start()
            else:
                self._anim_timer.stop()
                if icon not in self._tray_icons:
                    self._tray_icons[icon] = (make_mic_icon("#8a8a8a", outline=True) if icon == "off"
                                              else make_mic_icon())
                self.tray.setIcon(self._tray_icons[icon])

    ANIM_FRAMES = 8

    def _set_active_frame(self):
        key = ("active", self._anim_frame)
        if key not in self._tray_icons:
            self._tray_icons[key] = make_mic_icon("#d32f2f", ring=self._anim_frame / self.ANIM_FRAMES)
        self.tray.setIcon(self._tray_icons[key])

    def _animate_tray(self):
        self._anim_frame = (self._anim_frame + 1) % self.ANIM_FRAMES
        self._set_active_frame()

    def on_tray(self, reason):
        # Left-click starts a dictation and the next left-click stops it; the menu is on right-click.
        if reason != QSystemTrayIcon.ActivationReason.Trigger:
            return
        if self.recording_active:
            self.stop_by_click()
        elif self.start_recording(click=True):
            self.recording_active = True
            self._click_session = True
            self.press_time = time.monotonic()


_LOCK_FD = None


def acquire_single_instance_lock():
    global _LOCK_FD
    core.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = core.CONFIG_DIR / "dictate.lock"
    fd = open(lock_path, "w")
    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fd.close()
        core.notify(_("Dictate is already running"), urgency="low")
        return False
    _LOCK_FD = fd
    return True


def main():
    set_language(core.load_config().get("language", "auto"))
    if "--view-last" in sys.argv[1:]:   # the clip window on its own, without the tray app
        core.load_config()
        app = QApplication(sys.argv)
        import clip_viewer
        win = clip_viewer.ClipViewer()
        win.show()
        sys.exit(app.exec())
    if "--replay" in sys.argv[1:]:   # play the last recording and exit (no GUI, no second instance)
        if not core.replay_last_clip(wait=True):
            print("No recording yet", file=sys.stderr)
            sys.exit(1)
        return
    if not acquire_single_instance_lock():
        sys.exit(0)
    core.setup_logging()
    core.log.info("started")
    # Name the process "dictate" for the kernel (/proc/<pid>/comm, 15 chars max).
    # Resource monitors such as the panel's memory and CPU lists read that name,
    # and for a Python program it would otherwise just be "python".
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").prctl(15, b"dictate", 0, 0, 0)   # 15 = PR_SET_NAME
    except (OSError, AttributeError):
        pass
    # Let Ctrl+C in the terminal actually kill us — Qt's C++ event loop
    # otherwise never yields to Python's SIGINT handler.
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = QApplication(sys.argv)
    app.setApplicationName("Dictate")
    # Qt's own strings (Save/Cancel, ...) follow the chosen UI language.
    import i18n
    qt_tr = QTranslator()
    if i18n._lang != "en" and qt_tr.load(
            QLocale(i18n._lang), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(qt_tr)
    app.setQuitOnLastWindowClosed(False)   # the panel icon is the whole UI
    if not QSystemTrayIcon.isSystemTrayAvailable():
        core.log.warning("no system tray: Dictate works through its hotkey only")
    win = MainWindow()  # noqa: F841 (kept alive by the event loop)
    rc = app.exec()
    # A transcription still running on its worker thread (native onnx code)
    # would keep the process alive through interpreter shutdown, so leave
    # without waiting for it.
    logging.shutdown()
    os._exit(rc)


if __name__ == "__main__":
    main()
