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
        "Provider:": "Anbieter:",
        "{label} API key:": "{label}-API-Schlüssel:",
        "show": "zeigen",
        "Yorik URL:": "Yorik-URL:",
        "Push-to-talk (hold key)": "Push-to-Talk (Taste halten)",
        "Toggle (tap to start, tap to stop)": "Umschalten (tippen zum Starten, tippen zum Beenden)",
        "Mode:": "Modus:",
        "Hotkey:": "Tastenkürzel:",
        "Model:": "Modell:",
        "Local model:": "Lokales Modell:",
        "CPU threads:": "CPU-Threads:",
        "sherpa-onnx CPU thread count. 4 = best latency/resource balance on\nthis system; more brings little. Changing this rebuilds the recognizer.":
            "Anzahl der sherpa-onnx-CPU-Threads. Mehr Threads helfen nur\nbei Rechnern mit mehr Kernen. Eine Änderung lädt die Erkennung neu.",
        "Unload when idle:": "Bei Leerlauf entladen:",
        "Never": "Nie",
        " min": " Min.",
        "Unload the model after this long without a dictation to free about\n800 MB of RAM. It reloads (about 10 s on a slow CPU) when you next\npress the hotkey, while you are speaking.":
            "Entlädt das Modell nach dieser Zeit ohne Diktat und gibt rund\n800 MB Arbeitsspeicher frei. Beim nächsten Druck auf das Tastenkürzel\nwird es neu geladen (auf einer langsamen CPU etwa 10 s), während Sie sprechen.",
        "Recording starts immediately on press; release sends for transcription.\nIf you release before this duration, the recording is discarded. 0 =\nalways send. Recommended ~2.0s when bound to Ctrl/Alt/Shift so brief\ntaps and shortcuts don't transcribe.":
            "Die Aufnahme startet sofort beim Drücken; Loslassen sendet sie zur Transkription.\nWird früher losgelassen, wird die Aufnahme verworfen. 0 = immer senden.\nEmpfohlen: etwa 2,0 s bei Strg/Alt/Umschalt, damit kurze Tipper und\nTastenkombinationen nichts transkribieren.",
        "Min hold to send:": "Mindestdauer zum Senden:",
        "Language:": "Sprache:",
        "Automatic": "Automatisch",
        "Applies after restarting Dictate.": "Gilt nach einem Neustart von Dictate.",
        "Test API key": "API-Schlüssel testen",
        "Runs entirely offline on your CPU. Model: parakeet-primeline (German, ~640 MB, CC-BY-4.0). Attribution: primeline · NVIDIA · <a href='https://github.com/k2-fsa/sherpa-onnx'>k2-fsa/sherpa-onnx</a>.":
            "Läuft vollständig offline auf Ihrer CPU. Modell: parakeet-primeline (Deutsch, ca. 640 MB, CC-BY-4.0). Quellen: primeline · NVIDIA · <a href='https://github.com/k2-fsa/sherpa-onnx'>k2-fsa/sherpa-onnx</a>.",
        "OpenAI key: <a href='https://platform.openai.com/api-keys'>platform.openai.com/api-keys</a>.":
            "OpenAI-Schlüssel: <a href='https://platform.openai.com/api-keys'>platform.openai.com/api-keys</a>.",
        "Get a free Groq API key at <a href='https://console.groq.com'>console.groq.com</a>.":
            "Einen kostenlosen Groq-API-Schlüssel gibt es unter <a href='https://console.groq.com'>console.groq.com</a>.",
        "sherpa-onnx not installed — run: pip install --user sherpa-onnx soundfile":
            "sherpa-onnx ist nicht installiert — ausführen: pip install --user sherpa-onnx soundfile",
        "Download model (~640 MB)": "Modell herunterladen (ca. 640 MB)",
        "Installed and ready.": "Installiert und bereit.",
        "Re-download model": "Modell erneut herunterladen",
        "Not installed.": "Nicht installiert.",
        "Downloading...": "Lade herunter ...",
        "Starting download...": "Download startet ...",
        "Installed.": "Installiert.",
        "Download failed: {err}": "Download fehlgeschlagen: {err}",
        "Retry download": "Download wiederholen",
        "Downloading model (~640 MB, one-time) ...": "Lade Modell herunter (ca. 640 MB, einmalig) ...",
        "Downloading model: {name} ({done} / {total} MB)": "Lade Modell herunter: {name} ({done} / {total} MB)",
        "Our server did not deliver the model, trying Hugging Face ...": "Unser Server hat das Modell nicht geliefert, versuche Hugging Face ...",
        "Model downloaded.": "Modell heruntergeladen.",
        "Enter an API key first.": "Bitte zuerst einen API-Schlüssel eingeben.",
        "Testing...": "Teste ...",
        "API key works.": "Der API-Schlüssel funktioniert.",
        "API key rejected.": "Der API-Schlüssel wurde abgelehnt.",
        "Settings": "Einstellungen",
        "Ready": "Bereit",
        "Last transcription:": "Letzte Transkription:",
        "Show window": "Fenster anzeigen",
        "Quit": "Beenden",
        "Welcome to Dictate": "Willkommen bei Dictate",
        "Open Settings to pick a transcription provider:\n\n  * Groq (cloud, free tier — console.groq.com)\n  * OpenAI (cloud — platform.openai.com)\n  * Local (offline, German, CPU — one-time 640 MB download)":
            "Öffnen Sie die Einstellungen und wählen Sie einen Transkriptionsanbieter:\n\n  * Groq (Cloud, kostenlose Stufe — console.groq.com)\n  * OpenAI (Cloud — platform.openai.com)\n  * Lokal (offline, Deutsch, CPU — einmaliger Download von 640 MB)",
        "Push-to-talk": "Push-to-Talk",
        "Toggle": "Umschalten",
        "Mode: {mode}     Hotkey: {key}     Model: {model}{thr}":
            "Modus: {mode}     Tastenkürzel: {key}     Modell: {model}{thr}",
        "     Min hold: {thr:.1f}s": "     Mindestdauer: {thr:.1f} s",
        "Cancelled (combo)": "Abgebrochen (Tastenkombination)",
        "Recording cancelled after {held:.0f}s — another key or mouse button was pressed":
            "Aufnahme nach {held:.0f} s abgebrochen — eine andere Taste oder Maustaste wurde gedrückt",
        "Discarded (held {duration:.1f}s)": "Verworfen (gehalten: {duration:.1f} s)",
        "No API key — open Settings": "Kein API-Schlüssel — Einstellungen öffnen",
        "Recording...": "Aufnahme ...",
        "Transcribing...": "Transkribiere ...",
        "No audio captured — check the microphone": "Kein Ton aufgenommen — Mikrofon prüfen",
        "Error: {msg}": "Fehler: {msg}",
        "Dictate is already running": "Dictate läuft bereits",
        "Typing failed ({tool} exit {code})": "Eingabe fehlgeschlagen ({tool}, Exit-Code {code})",
        "Dictate — {msg}": "Dictate — {msg}",
        "Model: loading ...": "Modell: wird geladen ...",
        "Model: loaded, stays loaded": "Modell: geladen, bleibt geladen",
        "{m} min {s} s": "{m} Min. {s} s",
        "{s} s": "{s} s",
        "Model: loaded, unloads in {t}": "Modell: geladen, wird in {t} entladen",
        "Model: not loaded (loads when you press the hotkey)": "Modell: nicht geladen (wird beim Druck auf das Tastenkürzel geladen)",
        "Privacy: local, your voice never leaves this computer": "Datenschutz: lokal, Ihre Stimme verlässt diesen Computer nie",
        "Privacy: your voice is sent to your server {host}": "Datenschutz: Ihre Stimme wird an Ihren Server {host} gesendet",
        "Privacy: CLOUD, your voice is sent to {provider}": "Datenschutz: CLOUD, Ihre Stimme wird an {provider} gesendet",
        "Hotkey: {key}": "Tastenkürzel: {key}",
        "Start as a panel icon, without a window": "Als Symbol im Panel starten, ohne Fenster",
        "Start Dictate when I log in": "Dictate beim Anmelden starten",
        "Downloading the speech model once (about 640 MB). Dictation works when it is done.": "Das Sprachmodell wird einmalig heruntergeladen (etwa 640 MB). Danach können Sie diktieren.",
        "Speech model ready. Hold {key} and speak.": "Sprachmodell bereit. Halten Sie {key} und sprechen Sie.",
        "Model download failed: {err}": "Modell-Download fehlgeschlagen: {err}",
        "Microphone: {err}": "Mikrofon: {err}",
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
