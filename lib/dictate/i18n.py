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
        "Cancel": "Abbrechen",
        "Transcribing & pasting": "Transkribiere & füge ein",
        "Loading speech model, transcribing & pasting": "Lade Sprachmodell, transkribiere & füge ein",
        "Microphone:": "Mikrofon:",
        "Automatic": "Automatisch",
        "{name} (not connected)": "{name} (nicht verbunden)",
        "Local model:": "Lokales Modell:",
        "CPU threads:": "CPU-Threads:",
        "sherpa-onnx CPU thread count. 4 = best latency/resource balance on\nthis system; more brings little. Changing this rebuilds the recognizer.": "Anzahl der sherpa-onnx-CPU-Threads. Mehr Threads helfen nur\nbei Rechnern mit mehr Kernen. Eine Änderung lädt die Erkennung neu.",
        "Unload when idle:": "Bei Leerlauf entladen:",
        "Never": "Nie",
        " min": " Min.",
        "Unload the model after this long without a dictation to free about\n800 MB of RAM. It reloads (about 10 s on a slow CPU) when you next\npress the hotkey, while you are speaking.": "Entlädt das Modell nach dieser Zeit ohne Diktat und gibt rund\n800 MB Arbeitsspeicher frei. Beim nächsten Druck auf das Tastenkürzel\nwird es neu geladen (auf einer langsamen CPU etwa 10 s), während Sie sprechen.",
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
        "Quit": "Beenden",
        "Test dictation": "Diktat testen",
        "Dictate — Test dictation": "Dictate — Diktat testen",
        "Your dictation appears here.": "Ihr Diktat erscheint hier.",
        "Waiting for the speech model download": "Warte auf den Download des Sprachmodells",
        "Loading speech model & transcribing": "Lade Sprachmodell & transkribiere",
        "Transcribing": "Transkribiere",
        "Speak now": "Jetzt sprechen",
        "Filter mains hum": "Netzbrummen filtern",
        "Mains hum (a low buzz, often from the charger) can hide quiet words from the\nspeech detector, so they get cut out. This hides everything below 150 Hz from the\ndetector only; the recording itself is not changed.": "Netzbrummen (ein tiefes Summen, oft vom Netzteil) kann leise Wörter vor der\nSpracherkennung verbergen, sodass sie herausgeschnitten werden. Dies blendet alles\nunter 150 Hz nur für die Erkennung aus; die Aufnahme selbst bleibt unverändert.",
        "Show a level meter while dictating": "Beim Diktieren eine Pegelanzeige zeigen",
        "A small meter in the top right corner that moves while the program hears you speak.\nClick it to stop dictating.": "Eine kleine Anzeige oben rechts, die sich bewegt, solange das Programm Sie sprechen hört.\nKlicken Sie darauf, um das Diktieren zu beenden.",
        "Stop": "Stopp",
        "Click to stop dictating": "Klicken, um das Diktieren zu beenden",
        "Or click this icon to start, and click it again to stop": "Oder auf dieses Symbol klicken, um zu starten, und noch einmal, um zu beenden",
        "Show a notification while dictating": "Beim Diktieren eine Benachrichtigung anzeigen",
        "\"Speak now\" while you hold the key, then \"Transcribing\" until the text is typed.": "„Jetzt sprechen“, solange die Taste gehalten wird, danach „Transkribiere“, bis der Text getippt ist.",
        "Dictation settings": "Diktier-Einstellungen",
        "Clear": "Löschen",
        "Installed and ready.": "Installiert und bereit.",
        "Dictate — Last transcript": "Dictate — Letztes Transkript",
        "Copy": "Kopieren",
        "Learn corrections": "Korrekturen lernen",
        "Learned pairs": "Gelernte Paare",
        "As heard: {text}": "So verstanden: {text}",
        "Correct words I fixed before": "Früher korrigierte Wörter automatisch verbessern",
        "Dictate learns from the corrections you make in the last-transcript window\nand applies them to later dictations. Turn this off to paste exactly what was heard.": "Dictate lernt aus den Korrekturen, die Sie im Fenster „Letztes Transkript“ machen,\nund wendet sie auf spätere Diktate an. Ausschalten, um genau das Verstandene einzufügen.",
        "Learned corrections...": "Gelernte Korrekturen ...",
        "Dictate — Learned corrections": "Dictate — Gelernte Korrekturen",
        "Remove": "Entfernen",
        "Dictate replaces the left side by the right side. The numbers are how often you changed the words out of how often Dictate heard them. Grey entries do not qualify yet.": "Dictate ersetzt die linke Seite durch die rechte. Die Zahlen: wie oft Sie die Wörter geändert haben, von wie oft Dictate sie gehört hat. Graue Einträge gelten noch nicht.",
        "Remembers the words you changed above. After you have fixed the same\nmistake twice, Dictate corrects it by itself from then on.": "Merkt sich die oben geänderten Wörter. Haben Sie denselben Fehler\nzweimal korrigiert, verbessert Dictate ihn danach selbst.",
        "Learned: {pairs}": "Gelernt: {pairs}",
        "Forgotten: {pairs}": "Vergessen: {pairs}",
        "Noted. A mistake is learned once you have fixed it a couple of times.": "Vermerkt. Ein Fehler wird gelernt, sobald Sie ihn zweimal korrigiert haben.",
        "Close": "Schließen",
        "Show last transcript": "Letztes Transkript anzeigen",
        "Replay last recording": "Letzte Aufnahme abspielen",
        "Last recording": "Letzte Aufnahme",
        "Play": "Abspielen",
        "Close": "Schließen",
        "Audio": "Audio",
        "Speech while recording": "Sprache bei der Aufnahme",
        "Speech in the clip": "Sprache im Clip",
        "(not used: the clip was checked afterwards)": "(nicht verwendet: der Clip wurde nachträglich geprüft)",
        "(no speech found)": "(keine Sprache gefunden)",
        "key": "Taste",
        "no audio arrived": "kein Audio angekommen",
        "no audio for {t:.1f} s": "{t:.1f} s kein Audio",
        "stream on": "Stream an",
        "first audio": "erstes Audio",
        "released": "losgelassen",
        "Key press to recording running: {t}  (model check + microphone choice {a}, opening the device {b})": "Taste bis Aufnahme läuft: {t}  (Modellprüfung + Mikrofonwahl {a}, Gerät öffnen {b})",
        "First audio block {a} after the stream started; longest gap between blocks {b}; overflow reports {c}": "Erster Audioblock {a} nach Streamstart; längste Lücke zwischen Blöcken {b}; Überlaufmeldungen {c}",
        "Clip {d:.1f} s, level of the first 200 ms {h:.0f} dBFS, first speech at {f}": "Clip {d:.1f} s, Pegel der ersten 200 ms {h:.0f} dBFS, erste Sprache bei {f}",
        "never": "nie",
        "Reading: audio stopped arriving {t} before the key was released; the microphone stalled and the rest of the take is missing.": "Deutung: {t} vor dem Loslassen der Taste kam kein Audio mehr an; das Mikrofon hing und der Rest der Aufnahme fehlt.",
        "Reading: recording only started {t} after the key press; words spoken in that time are lost.": "Deutung: Die Aufnahme begann erst {t} nach dem Tastendruck; in dieser Zeit Gesprochenes fehlt.",
        "Reading: speech is already loud at the very start of the clip, so the first word began before the recording did.": "Deutung: Die Sprache ist schon ganz am Anfang des Clips laut, das erste Wort begann also vor der Aufnahme.",
        "Reading: the microphone delivered audio with a gap of {t}, so something was missing mid-take.": "Deutung: Das Mikrofon lieferte Audio mit einer Lücke von {t}, mitten in der Aufnahme fehlte also etwas.",
        "Reading: the recording itself looks complete; if a word is missing in the text, look at the speech lanes.": "Deutung: Die Aufnahme selbst wirkt vollständig; fehlt im Text ein Wort, schau auf die Sprachspuren.",
        "No recording yet": "Noch keine Aufnahme",
        "Dictation is off. Turn the hotkey on in this menu.": "Diktieren ist aus. Schalten Sie das Tastenkürzel in diesem Menü ein.",
        "Hotkey {key} enabled": "Tastenkürzel {key} aktiv",
        "Downloading the speech model once (about {mb} MB). Whatever you dictate meanwhile is typed when it is done.": "Das Sprachmodell wird einmalig heruntergeladen (etwa {mb} MB). Was Sie in der Zwischenzeit diktieren, wird danach getippt.",
        "Hold {key} to dictate in any supported language": "{key} gedrückt halten, um in jeder unterstützten Sprache zu diktieren",
        "Tap {key} to start and stop dictating in any supported language": "{key} tippen, um das Diktieren in jeder unterstützten Sprache zu starten und zu beenden",
        "Supported languages: Bulgarian, Croatian, Czech, Danish, Dutch, English, Estonian, Finnish, French, German, Greek, Hungarian, Italian, Latvian, Lithuanian, Maltese, Polish, Portuguese, Romanian, Russian, Slovak, Slovenian, Spanish, Swedish, Ukrainian": "Unterstützte Sprachen: Bulgarisch, Dänisch, Deutsch, Englisch, Estnisch, Finnisch, Französisch, Griechisch, Italienisch, Kroatisch, Lettisch, Litauisch, Maltesisch, Niederländisch, Polnisch, Portugiesisch, Rumänisch, Russisch, Schwedisch, Slowakisch, Slowenisch, Spanisch, Tschechisch, Ukrainisch, Ungarisch",
        "Hold {key} to dictate in German": "{key} gedrückt halten, um auf Deutsch zu diktieren",
        "Tap {key} to start and stop dictating in German": "{key} tippen, um das Diktieren auf Deutsch zu starten und zu beenden",
        "Speech model: {name} (loaded)": "Sprachmodell: {name} (geladen)",
        "Speech model: {name} (loading ...)": "Sprachmodell: {name} (wird geladen ...)",
        "Speech model: {name} (not loaded)": "Sprachmodell: {name} (nicht geladen)",
        "Load dictation model": "Diktiermodell laden",
        "Unload dictation model": "Diktiermodell entladen",
        "Welcome to Dictate": "Willkommen bei Dictate",
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
