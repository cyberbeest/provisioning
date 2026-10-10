#!/usr/bin/env python3
"""Dictate GUI — PyQt6 tray app for voice dictation via Groq Whisper."""
import fcntl
import sys
import threading
import time

import numpy as np
from PyQt6.QtCore import Qt, QObject, QPointF, QTimer, QLibraryInfo, QLocale, QTranslator, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu,
    QMessageBox, QPushButton, QSpinBox, QSystemTrayIcon, QTextEdit,
    QVBoxLayout, QWidget,
)
from pynput import keyboard

import core
from i18n import _, LANGUAGES, set_language


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
    transcribed = pyqtSignal(str)
    error = pyqtSignal(str)
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

        # --- Provider selector ---
        self.provider_box = QComboBox()
        for pid, pdef in core.PROVIDERS.items():
            self.provider_box.addItem(pdef["label"], pid)
        i = self.provider_box.findData(self.cfg.get("provider", core.DEFAULT_PROVIDER))
        self.provider_box.setCurrentIndex(max(i, 0))
        self.provider_box.currentIndexChanged.connect(self.on_provider_changed)
        self.form.addRow(_("Provider:"), self.provider_box)

        # --- API key row (hidden when a local provider is selected) ---
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        show_btn = QPushButton(_("show"))
        show_btn.setCheckable(True)
        show_btn.setMaximumWidth(60)
        show_btn.toggled.connect(
            lambda on: self.api_key_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.api_key_edit)
        row.addWidget(show_btn)
        self.api_key_wrap = QWidget()
        self.api_key_wrap.setLayout(row)
        self.api_key_label = QLabel()
        self.form.addRow(self.api_key_label, self.api_key_wrap)

        # --- Yorik URL row (shown only for the Yorik provider) ---
        self.yorik_url_edit = QLineEdit(self.cfg.get("yorik_url", core.DEFAULT_CONFIG["yorik_url"]))
        self.yorik_url_edit.setPlaceholderText("http://yorik.local:8000")
        self.form.addRow(_("Yorik URL:"), self.yorik_url_edit)

        # Per-provider key cache — only providers that actually take a key.
        self._keys = {
            pid: self.cfg.get(pdef["key_field"], "")
            for pid, pdef in core.PROVIDERS.items()
            if pdef.get("key_field")
        }

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

        self.model_box = QComboBox()
        self.form.addRow(_("Model:"), self.model_box)

        # --- Local-STT panel (shown only when a local provider is selected) ---
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

        self.threshold_box = QDoubleSpinBox()
        self.threshold_box.setRange(0.0, 5.0)
        self.threshold_box.setSingleStep(0.1)
        self.threshold_box.setDecimals(1)
        self.threshold_box.setSuffix(" s")
        self.threshold_box.setValue(float(self.cfg.get("threshold", 0.0)))
        self.threshold_box.setToolTip(_(
            "Recording starts immediately on press; release sends for transcription.\n"
            "If you release before this duration, the recording is discarded. 0 =\n"
            "always send. Recommended ~2.0s when bound to Ctrl/Alt/Shift so brief\n"
            "taps and shortcuts don't transcribe."
        ))
        self.form.addRow(_("Min hold to send:"), self.threshold_box)

        self.language_box = QComboBox()
        for code, name in LANGUAGES:
            self.language_box.addItem(_("Automatic") if code == "auto" else name, code)
        i = self.language_box.findData(self.cfg.get("language", "auto"))
        self.language_box.setCurrentIndex(max(i, 0))
        self.language_box.setToolTip(_("Applies after restarting Dictate."))
        self.form.addRow(_("Language:"), self.language_box)

        self.start_hidden_box = QCheckBox(_("Start as a panel icon, without a window"))
        self.start_hidden_box.setChecked(bool(self.cfg.get("start_hidden", True)))
        self.form.addRow("", self.start_hidden_box)
        self.autostart_box = QCheckBox(_("Start Dictate when I log in"))
        self.autostart_box.setChecked(core.autostart_enabled())
        self.form.addRow("", self.autostart_box)

        self.test_btn = QPushButton(_("Test API key"))
        self.test_btn.clicked.connect(self.on_test)
        self.form.addRow("", self.test_btn)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(self.form)

        self.hint = QLabel()
        self.hint.setOpenExternalLinks(True)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #777; padding: 6px 0;")
        layout.addWidget(self.hint)

        layout.addWidget(buttons)

        # Wire the download-worker bridge, then sync UI to current provider.
        self._dl_status.connect(self.local_status_label.setText)
        self._dl_done.connect(self._on_download_done)
        self.refresh_model_box(self.cfg.get("model", core.DEFAULT_MODEL))
        self.on_provider_changed()

    def on_provider_changed(self):
        # Persist edits to the previously-shown provider's key (if any) before
        # swapping the display to the newly selected provider.
        prev = getattr(self, "_shown_provider", None)
        if prev is not None and prev in self._keys:
            self._keys[prev] = self.api_key_edit.text().strip()

        pid = self.provider_box.currentData()
        pdef = core.PROVIDERS[pid]
        self._shown_provider = pid
        is_local = pdef.get("is_local", False)

        # HTTP-provider widgets
        if not is_local:
            self.api_key_label.setText(_("{label} API key:").format(label=pdef["label"]))
            self.api_key_edit.setText(self._keys.get(pid, ""))
            self.api_key_edit.setPlaceholderText(f"{pdef['key_prefix']}...")

        # Toggle row visibility. QFormLayout.setRowVisible(widget, bool) hides
        # both the field and its label.
        self.form.setRowVisible(self.api_key_wrap, not is_local)
        self.form.setRowVisible(self.yorik_url_edit, pid == "yorik")
        self.form.setRowVisible(self.model_box, not is_local)
        self.form.setRowVisible(self.test_btn, not is_local)
        self.form.setRowVisible(self.local_status_label, is_local)
        self.form.setRowVisible(self.local_download_btn, is_local)
        self.form.setRowVisible(self.local_threads_box, is_local)
        self.form.setRowVisible(self.local_idle_box, is_local)

        # Hint text at the bottom of the dialog.
        if is_local:
            self.hint.setText(_(
                "Runs entirely offline on your CPU. Model: parakeet-primeline "
                "(German, ~640 MB, CC-BY-4.0). Attribution: primeline · NVIDIA · "
                "<a href='https://github.com/k2-fsa/sherpa-onnx'>k2-fsa/sherpa-onnx</a>."
            ))
        elif pid == "openai":
            self.hint.setText(_(
                "OpenAI key: <a href='https://platform.openai.com/api-keys'>platform.openai.com/api-keys</a>."
            ))
        else:
            self.hint.setText(_(
                "Get a free Groq API key at <a href='https://console.groq.com'>console.groq.com</a>."
            ))

        self.refresh_model_box(pdef["default_model"])
        if is_local:
            self._refresh_local_status()

    def _refresh_local_status(self):
        try:
            import local_stt
            installed = local_stt.model_installed()
        except ImportError:
            self.local_status_label.setText(_(
                "sherpa-onnx not installed — run: pip install --user sherpa-onnx soundfile"
            ))
            self.local_download_btn.setEnabled(False)
            self.local_download_btn.setText(_("Download model (~640 MB)"))
            return
        if installed:
            self.local_status_label.setText(_("Installed and ready."))
            self.local_download_btn.setEnabled(True)
            self.local_download_btn.setText(_("Re-download model"))
        else:
            self.local_status_label.setText(_("Not installed."))
            self.local_download_btn.setEnabled(True)
            self.local_download_btn.setText(_("Download model (~640 MB)"))

    def on_download_model(self):
        self.local_download_btn.setEnabled(False)
        self.local_download_btn.setText(_("Downloading..."))
        self.local_status_label.setText(_("Starting download..."))
        threading.Thread(target=self._download_worker, daemon=True).start()

    def _download_worker(self):
        try:
            import local_stt
            local_stt.download_model(progress_cb=lambda m: self._dl_status.emit(m))
            self._dl_done.emit(True, _("Installed."))
        except Exception as e:
            self._dl_done.emit(False, _("Download failed: {err}").format(err=e))

    def _on_download_done(self, ok, msg):
        self.local_status_label.setText(msg)
        self.local_download_btn.setEnabled(True)
        self.local_download_btn.setText(_("Re-download model") if ok else _("Retry download"))

    def refresh_model_box(self, preferred_model):
        pid = self.provider_box.currentData()
        pdef = core.PROVIDERS[pid]
        self.model_box.blockSignals(True)
        self.model_box.clear()
        for label, mid in pdef["models"]:
            self.model_box.addItem(label, mid)
        i = self.model_box.findData(preferred_model)
        if i < 0:
            i = self.model_box.findData(pdef["default_model"])
        self.model_box.setCurrentIndex(max(i, 0))
        self.model_box.blockSignals(False)

    def on_test(self):
        key = self.api_key_edit.text().strip()
        if not key:
            QMessageBox.warning(self, "Dictate", _("Enter an API key first."))
            return
        self.test_btn.setEnabled(False)
        self.test_btn.setText(_("Testing..."))
        QApplication.processEvents()
        ok = core.test_api_key(key, self.provider_box.currentData(),
                               cfg={"yorik_url": self.yorik_url_edit.text().strip()})
        self.test_btn.setEnabled(True)
        self.test_btn.setText(_("Test API key"))
        if ok:
            QMessageBox.information(self, "Dictate", _("API key works."))
        else:
            QMessageBox.warning(self, "Dictate", _("API key rejected."))

    def values(self):
        # Sync current field back into the per-provider cache first, but only
        # if the shown provider actually has a key_field (local providers don't).
        pid = self.provider_box.currentData()
        if pid in self._keys:
            self._keys[pid] = self.api_key_edit.text().strip()
        return {
            "provider":              pid,
            "api_key":               self._keys.get("groq", ""),
            "openai_api_key":        self._keys.get("openai", ""),
            "mode":                  self.mode_box.currentData(),
            "key":                   self.key_box.currentData(),
            "model":                 self.model_box.currentData(),
            "threshold":             float(self.threshold_box.value()),
            "local_stt_num_threads": int(self.local_threads_box.value()),
            "local_stt_idle_minutes": int(self.local_idle_box.value()),
            "language":              self.language_box.currentData(),
            "start_hidden":          self.start_hidden_box.isChecked(),
            "autostart":             self.autostart_box.isChecked(),
            "yorik_url":             self.yorik_url_edit.text().strip() or core.DEFAULT_CONFIG["yorik_url"],
            "yorik_token":           self._keys.get("yorik", ""),
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


STATUS_STYLES = {
    "ready":        ("#f3f3f3", "#222"),
    "recording":    ("#fde2e2", "#a00000"),
    "transcribing": ("#fff3cc", "#8a6d00"),
    "error":        ("#ffd6d6", "#9a0000"),
}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dictate")
        self.resize(500, 380)
        self.setWindowIcon(make_mic_icon())

        self.cfg = core.load_config()
        self.recorder = core.Recorder()
        self.bridge = Bridge()
        self.bridge.hotkey_press.connect(self.on_press)
        self.bridge.hotkey_release.connect(self.on_release)
        self.bridge.other_press.connect(self.on_other_press)
        self.bridge.transcribed.connect(self.on_transcribed)
        self.bridge.error.connect(self.on_error)
        self.bridge.model_progress.connect(lambda m: self.set_status("transcribing", m))
        self.bridge.model_done.connect(self.on_model_done)
        self._model_downloading = False
        self.key_held = False
        self.combo = False
        self.recording_active = False
        self.listener = None
        self._target_keys = set()
        self._last_other = None

        self.press_time = 0.0

        central = QWidget()
        self.setCentralWidget(central)
        v = QVBoxLayout(central)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("Dictate")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        header.addWidget(title)
        header.addStretch()
        self.settings_btn = QPushButton(_("Settings"))
        self.settings_btn.clicked.connect(self.open_settings)
        # xdotool types into the focused window; if that is this one, a space
        # or Enter in the dictated text would "press" a focused button.
        self.settings_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header.addWidget(self.settings_btn)
        v.addLayout(header)

        self.status_label = QLabel(_("Ready"))
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.status_label)

        self.info_label = QLabel()
        self.info_label.setStyleSheet("color: #666; padding: 2px 0;")
        v.addWidget(self.info_label)

        v.addWidget(QLabel(_("Last transcription:")))
        self.last = QTextEdit()
        self.last.setReadOnly(True)
        self.last.setMaximumHeight(110)
        self.last.setStyleSheet(
            "QTextEdit { background: #fafafa; border: 1px solid #ddd; border-radius: 6px; padding: 6px; }"
        )
        v.addWidget(self.last)

        v.addStretch()

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
            a_show = QAction(_("Show window"), self)
            a_show.triggered.connect(self.show_window)
            a_quit = QAction(_("Quit"), self)
            a_quit.triggered.connect(QApplication.quit)
            menu.addAction(a_show)
            menu.addSeparator()
            menu.addAction(a_quit)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(self.on_tray)
            self.tray.show()
            self._tray_timer = QTimer(self)
            self._tray_timer.timeout.connect(self._refresh_tray)
            self._tray_timer.start(2000)

        self.set_status("ready", _("Ready"))
        self.update_info()
        self.start_listener()

        if not core.provider_key(self.cfg):
            QTimer.singleShot(250, self.first_run)

    def _preload_local_if_needed(self):
        """Kick off the parakeet recognizer load in the background so the first
        real dictation isn't slowed by the ~0.8s model load + warmup."""
        provider = self.cfg.get("provider")
        pdef = core.PROVIDERS.get(provider, {})
        if not pdef.get("is_local"):
            return
        try:
            import local_stt
        except ImportError:
            return
        if not local_stt.model_installed():
            return
        local_stt.preload(
            int(self.cfg.get("local_stt_num_threads", local_stt.DEFAULT_THREADS)),
            60 * float(self.cfg.get("local_stt_idle_minutes", 5)),
        )

    def first_run(self):
        QMessageBox.information(
            self,
            _("Welcome to Dictate"),
            _("Open Settings to pick a transcription provider:\n\n"
            "  * Groq (cloud, free tier — console.groq.com)\n"
            "  * OpenAI (cloud — platform.openai.com)\n"
            "  * Local (offline, German, CPU — one-time 640 MB download)"),
        )
        self.open_settings()

    def update_info(self):
        mode_name = _("Push-to-talk") if self.cfg["mode"] == "ptt" else _("Toggle")
        thr = float(self.cfg.get("threshold", 0.0))
        thr_str = _("     Min hold: {thr:.1f}s").format(thr=thr) if thr > 0 else ""
        self.info_label.setText(_("Mode: {mode}     Hotkey: {key}     Model: {model}{thr}").format(
            mode=mode_name, key=self.cfg["key"].upper(), model=self.cfg["model"], thr=thr_str))

    def open_settings(self):
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.cfg.update(dlg.values())
            core.set_autostart(self.cfg.pop("autostart"))
            core.save_config(self.cfg)
            self.restart_listener()
            self.update_info()

    def start_listener(self):
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

    def restart_listener(self):
        if self.listener:
            self.listener.stop()
            self.listener = None
        self.key_held = False
        self.combo = False
        self.recording_active = False
        self.start_listener()

    def on_press(self):
        if self.key_held:
            return
        self.key_held = True
        self.combo = False
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
        if self.cfg["mode"] == "ptt" and self.recording_active:
            # Offload PipeWire close to keep the GUI thread responsive.
            self._discard_take()
            self.recording_active = False
            self.set_status("ready", _("Cancelled (combo)"))
            held = time.monotonic() - self.press_time
            core.log.info("cancelled after %.1fs by %s", held, self._last_other)
            # A shortcut like Ctrl+C cancels within a moment and needs no
            # message; a long hold was a dictation that just got thrown away.
            min_hold = float(self.cfg.get("threshold", 0.0))
            if held >= max(min_hold, 1.0):
                core.notify(_("Recording cancelled after {held:.0f}s — another key or mouse button was pressed").format(held=held),
                            urgency="critical", timeout_ms=5000)

    def on_release(self):
        self.key_held = False
        if self.cfg["mode"] != "ptt":
            return
        if not self.recording_active:
            return
        duration = time.monotonic() - self.press_time
        min_hold = float(self.cfg.get("threshold", 0.0))
        if min_hold > 0 and duration < min_hold:
            # Discard branch also blocks on recorder.stop() → freeze. Offload.
            self._discard_take()
            self.recording_active = False
            self.set_status("ready", _("Discarded (held {duration:.1f}s)").format(duration=duration))
            return
        self.stop_and_transcribe()
        self.recording_active = False

    def _ensure_model(self) -> bool:
        """True if recording can start. A missing local model (profile skipped
        the download, or it failed) is fetched now, once, in the background."""
        if not core.PROVIDERS.get(self.cfg.get("provider"), {}).get("is_local"):
            return True
        try:
            import local_stt
        except ImportError:
            return True  # the transcribe error will say what is missing
        if local_stt.model_installed():
            return True
        if not self._model_downloading:
            self._model_downloading = True
            threading.Thread(target=self._model_download_worker, args=(local_stt,), daemon=True).start()
            threading.Thread(
                target=core.notify,
                args=(_("Downloading the speech model once (about 640 MB). Dictation works when it is done."),
                      "normal", 6000),
                daemon=True).start()
        return False

    def _model_download_worker(self, local_stt):
        try:
            local_stt.download_model(progress_cb=self.bridge.model_progress.emit)
            self.bridge.model_done.emit(True, "")
        except Exception as e:
            core.log.exception("model download failed")
            self.bridge.model_done.emit(False, str(e))

    def on_model_done(self, ok, err):
        self._model_downloading = False
        if ok:
            self.set_status("ready", _("Ready"))
            threading.Thread(
                target=core.notify,
                args=(_("Speech model ready. Hold {key} and speak.").format(key=self.cfg["key"].upper()),
                      "normal", 4000),
                daemon=True).start()
        else:
            self.on_error(_("Model download failed: {err}").format(err=err))

    def start_recording(self) -> bool:
        if not self._ensure_model():
            return False
        # Reload the model if it was unloaded while idle; the load runs while
        # the user speaks. Also restarts the idle countdown.
        self._preload_local_if_needed()
        if not core.provider_key(self.cfg):
            self.set_status("error", _("No API key — open Settings"))
            return False
        try:
            self.recorder.start()
        except Exception as e:
            core.log.exception("could not open the microphone")
            self.on_error(_("Microphone: {err}").format(err=e))
            return False
        self.set_status("recording", _("Recording..."))
        return True

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
        threading.Thread(target=self._stop_and_transcribe_worker, args=(take,), daemon=True).start()

    def _discard_take(self):
        take = self.recorder.detach()
        threading.Thread(target=core.Recorder.finish, args=(take,), daemon=True).start()

    def _stop_and_transcribe_worker(self, take):
        # Short trailing buffer: PipeWire has ~50-100ms input latency and
        # people typically finish the last syllable *after* they release the
        # hotkey. Without this the last word tends to get clipped.
        time.sleep(0.25)
        audio = core.Recorder.finish(take)
        if audio is None:
            core.log.warning("no audio captured (mic delivered no frames)")
            self.bridge.error.emit(_("No audio captured — check the microphone"))
            return
        secs = len(audio) / core.SAMPLE_RATE
        peak = int(np.abs(audio).max())
        t0 = time.monotonic()
        try:
            text = core.transcribe(audio, self.cfg)
        except Exception as e:
            core.log.exception("transcribe failed: %.1fs audio, peak %d", secs, peak)
            self.bridge.error.emit(str(e))
            return
        core.log.info("transcribed %.1fs audio, peak %d, %d chars in %.1fs",
                      secs, peak, len(text or ""), time.monotonic() - t0)
        if not text:
            # Peak is out of 32768; a live mic with speech is in the thousands.
            why = "microphone was silent" if peak < 300 else "no speech recognised"
            if peak >= 300:
                core.keep_failed_audio(audio)
            core.log.info("nothing transcribed (%.0fs) — %s", secs, why)
            self.bridge.transcribed.emit("")
            return
        self.bridge.transcribed.emit(text)

    def on_transcribed(self, text):
        if text:
            # A finished sentence gets a trailing space so the next dictation
            # doesn't run into it.
            typed = text + " " if text.endswith((".", "!", "?")) else text
            threading.Thread(target=core.type_text, args=(typed,), daemon=True).start()
            self.last.setPlainText(text)
        self.set_status("ready", _("Ready"))

    def on_error(self, msg):
        self.set_status("error", _("Error: {msg}").format(msg=msg[:80]))
        # The window is usually hidden in the tray, so the status label alone
        # means the dictation fails without anyone noticing.
        threading.Thread(target=core.notify, args=(msg[:200], "critical", 5000), daemon=True).start()

    def set_status(self, state, msg):
        bg, fg = STATUS_STYLES.get(state, STATUS_STYLES["ready"])
        self.status_label.setText(msg)
        self.status_label.setStyleSheet(
            f"font-size: 24px; padding: 28px; border-radius: 10px;"
            f"background: {bg}; color: {fg};"
        )
        self._status = (state, msg)
        self._refresh_tray()

    def _local_state(self):
        """(state, seconds until unload) for the local model, or None for cloud providers."""
        if not core.PROVIDERS.get(self.cfg.get("provider"), {}).get("is_local"):
            return None
        try:
            import local_stt
        except ImportError:
            return None
        return local_stt.status()

    def _privacy_line(self):
        """Where the audio goes: the one thing the user must be able to see at a glance."""
        pid = self.cfg.get("provider")
        pdef = core.PROVIDERS.get(pid, {})
        if pdef.get("is_local"):
            return _("Privacy: local, your voice never leaves this computer")
        if pid == "yorik":
            from urllib.parse import urlparse
            host = urlparse(self.cfg.get("yorik_url") or "").hostname or "?"
            if host in ("127.0.0.1", "localhost", "::1"):
                return _("Privacy: local, your voice never leaves this computer")
            return _("Privacy: your voice is sent to your server {host}").format(host=host)
        return _("Privacy: CLOUD, your voice is sent to {provider}").format(provider=pdef.get("label", pid))

    def _refresh_tray(self):
        if not self.tray:
            return
        state, msg = self._status
        local = self._local_state()
        lines = [_("Dictate — {msg}").format(msg=msg)]
        if local:
            mstate, left = local
            if mstate == "loading":
                lines.append(_("Model: loading ..."))
            elif mstate == "loaded" and left is None:
                lines.append(_("Model: loaded, stays loaded"))
            elif mstate == "loaded":
                mins, secs = divmod(int(left) + 1, 60)
                t = _("{m} min {s} s").format(m=mins, s=secs) if mins else _("{s} s").format(s=secs)
                lines.append(_("Model: loaded, unloads in {t}").format(t=t))
            else:
                lines.append(_("Model: not loaded (loads when you press the hotkey)"))
        lines.append(self._privacy_line())
        lines.append(_("Hotkey: {key}").format(key=self.cfg["key"].upper().replace("_", " ")))
        self.tray.setToolTip("\n".join(lines))
        if state in ("recording", "transcribing"):
            key = "active"
        elif local and local[0] != "loaded":
            key = "unloaded"
        else:
            key = "loaded"
        if key != self._tray_icon_key:
            self._tray_icon_key = key
            if key == "active":
                self._anim_frame = 0
                self._set_active_frame()
                self._anim_timer.start()
            else:
                self._anim_timer.stop()
                if key not in self._tray_icons:
                    self._tray_icons[key] = make_mic_icon(
                        {"unloaded": "#8a8a8a", "loaded": "#2b2b2b"}[key], outline=(key == "unloaded"))
                self.tray.setIcon(self._tray_icons[key])

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
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.show_window()

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        if self.tray:
            # With a panel icon, closing the window just hides it; the tray
            # menu's Quit ends the app.
            event.ignore()
            self.hide()
        else:
            QApplication.quit()


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
    if not acquire_single_instance_lock():
        sys.exit(0)
    core.setup_logging()
    core.log.info("started")
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
    has_tray = QSystemTrayIcon.isSystemTrayAvailable()
    app.setQuitOnLastWindowClosed(not has_tray)
    win = MainWindow()
    if not (has_tray and win.cfg.get("start_hidden", True)):
        win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
