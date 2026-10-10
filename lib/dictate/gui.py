#!/usr/bin/env python3
"""Dictate GUI — PyQt6 tray app for voice dictation via Groq Whisper."""
import fcntl
import sys
import threading
import time

import numpy as np
from PyQt6.QtCore import Qt, QObject, QPointF, QTimer, QLibraryInfo, QLocale, QTranslator, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QColor, QIcon, QPainter, QPixmap
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

        self.start_hidden_box = QCheckBox(_("Start as a panel icon, without a window"))
        self.start_hidden_box.setChecked(bool(self.cfg.get("start_hidden", True)))
        self.form.addRow("", self.start_hidden_box)
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
            "model":                 self.model_box.currentData(),
            "threshold":             float(self.threshold_box.value()),
            "local_stt_num_threads": int(self.local_threads_box.value()),
            "local_stt_idle_minutes": int(self.local_idle_box.value()),
            "start_hidden":          self.start_hidden_box.isChecked(),
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
            a_settings = QAction(_("Settings"), self)
            a_settings.triggered.connect(self.open_settings)
            self.a_load = QAction(_("Load dictation model"), self)
            self.a_load.triggered.connect(self.load_model_now)
            self.a_unload = QAction(_("Unload dictation model"), self)
            self.a_unload.triggered.connect(self.unload_model_now)
            a_quit = QAction(_("Quit"), self)
            a_quit.triggered.connect(QApplication.quit)
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
            menu.aboutToShow.connect(self._update_model_actions)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(self.on_tray)
            self.tray.show()
            self._tray_timer = QTimer(self)
            self._tray_timer.timeout.connect(self._refresh_tray)
            self._tray_timer.start(2000)

        self.set_status("ready", _("Ready"))
        self.update_info()
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

    def update_info(self):
        mode_name = _("Push-to-talk") if self.cfg["mode"] == "ptt" else _("Toggle")
        thr = float(self.cfg.get("threshold", 0.0))
        thr_str = _("     Min hold: {thr:.1f}s").format(thr=thr) if thr > 0 else ""
        self.info_label.setText(_("Mode: {mode}     Hotkey: {key}     Model: {model}{thr}").format(
            mode=mode_name, key=self.cfg["key"].upper(), model=self._model_label(), thr=thr_str))

    def set_model(self, model_id):
        """Switch the speech model from the tray menu."""
        import local_stt
        if model_id == self.cfg.get("model"):
            return
        local_stt.unload()   # free the old model's memory now
        self.cfg["model"] = local_stt.select_model(model_id)
        core.save_config(self.cfg)
        self.update_info()
        self._refresh_tray()
        if not local_stt.model_installed():
            self._ensure_model()   # starts the one-time download

    def _update_model_actions(self):
        for mid, act in self._model_actions.items():
            act.setChecked(mid == self.cfg.get("model"))
        local = self._local_model_available()
        state = "not_loaded"
        if local:
            import local_stt
            state = local_stt.status()[0]
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
        import local_stt
        if local_stt.model_installed():
            return True
        if not self._model_downloading:
            self._model_downloading = True
            threading.Thread(target=self._model_download_worker, args=(local_stt,), daemon=True).start()
        return False

    def _model_download_worker(self, local_stt):
        # The notice stays up for the whole download and is taken down at the end.
        note = core.notify_sticky(
            _("Downloading the speech model once (about {mb} MB). Dictation works when it is done.").format(
                mb=local_stt._spec()["size_mb"]))
        try:
            local_stt.download_model(progress_cb=self.bridge.model_progress.emit)
            self.bridge.model_done.emit(True, "")
        except Exception as e:
            core.log.exception("model download failed")
            self.bridge.model_done.emit(False, str(e))
        finally:
            core.close_notification(note)

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
        wait_note = None
        if self._local_model_available():
            import local_stt
            if local_stt.status()[0] != "loaded":
                # Dictation ended before the model finished loading: say why
                # the text is late, and take the message down when it is ready.
                wait_note = core.notify_sticky(
                    _("Loading the speech model, your text follows in a moment..."))
        try:
            text = core.transcribe(audio, self.cfg)
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
        """(state, seconds until unload) of the speech model."""
        import local_stt
        return local_stt.status()

    def _privacy_line(self):
        """Where the audio goes: the one thing the user must be able to see at a glance."""
        return _("Privacy: local, your voice never leaves this computer")

    def _refresh_tray(self):
        if not self.tray:
            return
        state, msg = self._status
        local = self._local_state()
        key = self.cfg["key"].upper().replace("_", " ")
        if state == "ready":
            if self.cfg.get("mode") == "toggle":
                first = _("Tap {key} to start and stop dictating").format(key=key)
            else:
                first = _("Hold {key} to dictate").format(key=key)
        else:
            first = _("Dictate — {msg}").format(msg=msg)
        lines = [first]
        mstate = local[0] if local else "not_loaded"
        name = self._model_label()
        if mstate == "loaded":
            lines.append(_("Speech model: {name} (loaded)").format(name=name))
        elif mstate == "loading":
            lines.append(_("Speech model: {name} (loading ...)").format(name=name))
        else:
            lines.append(_("Speech model: {name} (not loaded)").format(name=name))
        lines.append(self._privacy_line())
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
