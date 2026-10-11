#!/usr/bin/env python3
"""Dictate GUI — PyQt6 tray app for voice dictation via Groq Whisper."""
import fcntl
import sys
import threading
import time

import numpy as np
from PyQt6.QtCore import Qt, QObject, QPointF, QTimer, QLibraryInfo, QLocale, QTranslator, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QColor, QCursor, QIcon, QPainter, QPixmap
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

        self.notify_box = QCheckBox(_("Show a notification while dictating"))
        self.notify_box.setChecked(bool(self.cfg.get("dictation_notifications", True)))
        self.notify_box.setToolTip(_("\"Speak now\" while you hold the key, then \"Transcribing\" until the text is typed."))
        self.form.addRow("", self.notify_box)
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
            "local_stt_num_threads": int(self.local_threads_box.value()),
            "local_stt_idle_minutes": int(self.local_idle_box.value()),
            "dictation_notifications": self.notify_box.isChecked(),
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


class DictationNote:
    """One notification that follows a dictation: "Speak now" while the key is
    held, then "Transcribing ...", closed when the text is ready. Showing it
    runs on a thread so pressing the hotkey never waits for the notification
    daemon; update() and close() must not be called from the GUI thread."""

    def __init__(self, msg):
        self.id = None
        self._thread = threading.Thread(target=self._show, args=(msg,), daemon=True)
        self._thread.start()

    def _show(self, msg):
        self.id = core.notify_sticky(msg)

    def update(self, msg):
        self._thread.join()
        self.id = core.notify_sticky(msg, replace_id=self.id)

    def close(self):
        self._thread.join()
        core.close_notification(self.id)



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

        self._note = None            # DictationNote of the dictation in progress
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

    def show_last_transcript(self):
        if not self.last_text:
            return
        self._last_dialog = LastTranscriptDialog(self.last_text, self.clear_last_transcript)
        self._last_dialog.show()
        self._last_dialog.raise_()
        self._last_dialog.activateWindow()

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
            if held >= 1.0:
                core.notify(_("Recording cancelled after {held:.0f}s — another key or mouse button was pressed").format(held=held),
                            urgency="critical", timeout_ms=5000)

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

    def start_recording(self) -> bool:
        self._ensure_model()   # a missing model downloads while the user speaks
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
        if self.cfg.get("dictation_notifications"):
            self._note = DictationNote(_("Speak now"))
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
        note, self._note = self._note, None
        threading.Thread(target=self._stop_and_transcribe_worker, args=(take, note), daemon=True).start()

    def _discard_take(self):
        note, self._note = self._note, None
        if note:
            threading.Thread(target=note.close, daemon=True).start()
        take = self.recorder.detach()
        threading.Thread(target=core.Recorder.finish, args=(take,), daemon=True).start()

    def _note_text(self):
        if not core.model_ready():
            return _("Waiting for the speech model download")
        if self._local_state() == "loaded":
            return _("Transcribing")
        return _("Loading speech model and transcribing")

    def _stop_and_transcribe_worker(self, take, note):
        try:
            self._transcribe_take(take, note)
        finally:
            if note:
                note.close()

    def _transcribe_take(self, take, note):
        if note:
            note.update(self._note_text())   # the key is up: "Speak now" turns into the current step
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
                note.update(self._note_text())
        wait_note = None
        if self._local_model_available() and not note:
            import local_stt
            if local_stt.status() != "loaded":
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
            self.last_text = text
            self._clear_timer.start()   # restarts the countdown
        self.set_status("ready", _("Ready"))

    def on_error(self, msg):
        self.set_status("error", _("Error: {msg}").format(msg=msg[:80]))
        # The window is usually hidden in the tray, so the status label alone
        # means the dictation fails without anyone noticing.
        threading.Thread(target=core.notify, args=(msg[:200], "critical", 5000), daemon=True).start()

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

    def _refresh_tray(self):
        if not self.tray:
            return
        state, msg = self._status
        key = self.cfg["key"].upper().replace("_", " ")
        hotkey_on = self.cfg.get("hotkey_enabled", True)
        german_only = self.cfg.get("model") == "nemo-de-fastconformer-int8"
        if not hotkey_on:
            lines = [_("Dictation is off. Turn the hotkey on in this menu.")]
        else:
            if state != "ready":
                first = _("Dictate — {msg}").format(msg=msg)
            elif self.cfg.get("mode") == "toggle":
                first = (_("Tap {key} to start and stop dictating in German") if german_only else
                         _("Tap {key} to start and stop dictating in any supported language")).format(key=key)
            else:
                first = (_("Hold {key} to dictate in German") if german_only else
                         _("Hold {key} to dictate in any supported language")).format(key=key)
            lines = [first]
            if state == "ready" and not german_only:
                import textwrap
                lines += textwrap.wrap(_(LANGUAGE_LIST_EN), width=64)
            mstate = self._local_state()
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
        # Left-click opens the same menu as right-click.
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.menu.popup(QCursor.pos())


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
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
