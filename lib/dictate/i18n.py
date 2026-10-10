"""Minimal UI translation: English source strings are the keys.

_("text") returns the translation for the active language, or the English
text when there is none. Catalogs are plain dicts in CATALOGS; to add a
language, add a dict there and an entry in LANGUAGES. Strings with
placeholders use str.format: _("Error: {msg}").format(msg=...).
"""
import locale
import os

LANGUAGES = [("auto", "Automatic"), ("en", "English"), ("de", "Deutsch")]

CATALOGS = {
    "de": {
        "Dictate — Settings": "Dictate — Einstellungen",
        "show": "zeigen",
        "Push-to-talk (hold key)": "Push-to-Talk (Taste halten)",
        "Toggle (tap to start, tap to stop)": "Umschalten (tippen zum Starten, tippen zum Beenden)",
        "Mode:": "Modus:",
        "Hotkey:": "Tastenkürzel:",
        "Model:": "Modell:",
        "Local model:": "Lokales Modell:",
        "CPU threads:": "CPU-Threads:",
        "sherpa-onnx CPU thread count. 4 = best latency/resource balance on\nthis system; more brings little. Changing this rebuilds the recognizer.": "Anzahl der sherpa-onnx-CPU-Threads. Mehr Threads helfen nur\nbei Rechnern mit mehr Kernen. Eine Änderung lädt die Erkennung neu.",
        "Unload when idle:": "Bei Leerlauf entladen:",
        "Never": "Nie",
        " min": " Min.",
        "Unload the model after this long without a dictation to free about\n800 MB of RAM. It reloads (about 10 s on a slow CPU) when you next\npress the hotkey, while you are speaking.": "Entlädt das Modell nach dieser Zeit ohne Diktat und gibt rund\n800 MB Arbeitsspeicher frei. Beim nächsten Druck auf das Tastenkürzel\nwird es neu geladen (auf einer langsamen CPU etwa 10 s), während Sie sprechen.",
        "Recording starts immediately on press; release sends for transcription.\nIf you release before this duration, the recording is discarded. 0 =\nalways send. Recommended ~2.0s when bound to Ctrl/Alt/Shift so brief\ntaps and shortcuts don't transcribe.": "Die Aufnahme startet sofort beim Drücken; Loslassen sendet sie zur Transkription.\nWird früher losgelassen, wird die Aufnahme verworfen. 0 = immer senden.\nEmpfohlen: etwa 2,0 s bei Strg/Alt/Umschalt, damit kurze Tipper und\nTastenkombinationen nichts transkribieren.",
        "Min hold to send:": "Mindestdauer zum Senden:",
        "Installed and ready.": "Installiert und bereit.",
        "Not installed.": "Nicht installiert.",
        "Downloading...": "Lade herunter ...",
        "Starting download...": "Download startet ...",
        "Installed.": "Installiert.",
        "Download failed: {err}": "Download fehlgeschlagen: {err}",
        "Retry download": "Download wiederholen",
        "Downloading model: {name} ({done} / {total} MB)": "Lade Modell herunter: {name} ({done} / {total} MB)",
        "Model downloaded.": "Modell heruntergeladen.",
        "Settings": "Einstellungen",
        "Ready": "Bereit",
        "Last transcription:": "Letzte Transkription:",
        "Quit": "Beenden",
        "Hold {key} to dictate": "{key} halten zum Diktieren",
        "Tap {key} to start and stop dictating": "{key} tippen zum Starten und Beenden des Diktierens",
        "Speech model: {name} (loaded)": "Sprachmodell: {name} (geladen)",
        "Speech model: {name} (loading ...)": "Sprachmodell: {name} (wird geladen ...)",
        "Speech model: {name} (not loaded)": "Sprachmodell: {name} (nicht geladen)",
        "Load dictation model": "Diktiermodell laden",
        "Unload dictation model": "Diktiermodell entladen",
        "Welcome to Dictate": "Willkommen bei Dictate",
        "Push-to-talk": "Push-to-Talk",
        "Toggle": "Umschalten",
        "Mode: {mode}     Hotkey: {key}     Model: {model}{thr}": "Modus: {mode}     Tastenkürzel: {key}     Modell: {model}{thr}",
        "     Min hold: {thr:.1f}s": "     Mindestdauer: {thr:.1f} s",
        "Cancelled (combo)": "Abgebrochen (Tastenkombination)",
        "Recording cancelled after {held:.0f}s — another key or mouse button was pressed": "Aufnahme nach {held:.0f} s abgebrochen — eine andere Taste oder Maustaste wurde gedrückt",
        "Discarded (held {duration:.1f}s)": "Verworfen (gehalten: {duration:.1f} s)",
        "Recording...": "Aufnahme ...",
        "Transcribing...": "Transkribiere ...",
        "No audio captured — check the microphone": "Kein Ton aufgenommen — Mikrofon prüfen",
        "Error: {msg}": "Fehler: {msg}",
        "Dictate is already running": "Dictate läuft bereits",
        "Typing failed ({tool} exit {code})": "Eingabe fehlgeschlagen ({tool}, Exit-Code {code})",
        "Dictate — {msg}": "Dictate — {msg}",
        "Privacy: local, your voice never leaves this computer": "Datenschutz: lokal, Ihre Stimme verlässt diesen Computer nie",
        "Start as a panel icon, without a window": "Als Symbol im Panel starten, ohne Fenster",
        "Start Dictate when I log in": "Dictate beim Anmelden starten",
        "Loading the speech model, your text follows in a moment...": "Sprachmodell wird geladen, Ihr Text folgt gleich ...",
        "Speech model ready. Hold {key} and speak.": "Sprachmodell bereit. Halten Sie {key} und sprechen Sie.",
        "Model download failed: {err}": "Modell-Download fehlgeschlagen: {err}",
        "Microphone: {err}": "Mikrofon: {err}",
        "Speech model:": "Sprachmodell:",
        "German only (faster)": "Nur Deutsch (schneller)",
        "Multi-language (slower)": "Mehrsprachig (langsamer)",
        "Not installed. It is downloaded when you first dictate.": "Nicht installiert. Es wird beim ersten Diktieren heruntergeladen.",
        "Download model (~{mb} MB)": "Modell herunterladen (ca. {mb} MB)",
        "Downloading model (about {mb} MB, one-time) ...": "Lade Modell herunter (ca. {mb} MB, einmalig) ...",
        "Our server did not deliver the model, trying another source ...": "Unser Server hat das Modell nicht geliefert, versuche eine andere Quelle ...",
                "Runs entirely on this computer: your voice is never sent anywhere. German only: NVIDIA stt_de_fastconformer_hybrid_large_pc. Multi-language: primeline parakeet, based on NVIDIA Parakeet. Both CC-BY-4.0, converted to ONNX int8 and run with <a href='https://github.com/k2-fsa/sherpa-onnx'>sherpa-onnx</a>.": "Läuft vollständig auf diesem Computer: Ihre Stimme wird nirgendwohin gesendet. Nur Deutsch: NVIDIA stt_de_fastconformer_hybrid_large_pc. Mehrsprachig: primeline Parakeet, basierend auf NVIDIA Parakeet. Beide CC-BY-4.0, nach ONNX int8 konvertiert und mit <a href='https://github.com/k2-fsa/sherpa-onnx'>sherpa-onnx</a> ausgeführt.",
        "Dictate needs a speech model to work. Pick one in Settings; it is downloaded once and then runs entirely on this computer.": "Dictate braucht ein Sprachmodell. Wählen Sie eines in den Einstellungen; es wird einmalig heruntergeladen und läuft danach vollständig auf diesem Computer.",
        "Downloading the speech model once (about {mb} MB). Dictation works when it is done.": "Das Sprachmodell wird einmalig heruntergeladen (etwa {mb} MB). Danach können Sie diktieren.",
    },
}

_lang = "en"


def resolve(setting):
    """'auto' -> the desktop locale's language if we have a catalog, else 'en'."""
    if setting in CATALOGS or setting == "en":
        return setting
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(var)
        if val:
            code = val.split(".")[0].split("_")[0].lower()
            return code if code in CATALOGS else "en"
    try:
        code = (locale.getlocale()[0] or "en").split("_")[0].lower()
    except ValueError:
        code = "en"
    return code if code in CATALOGS else "en"


def set_language(setting):
    global _lang
    _lang = resolve(setting)


def _(text):
    return CATALOGS.get(_lang, {}).get(text, text)
