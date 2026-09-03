# German strings for provisioning's Python GUI scripts. Keys must match
# strings_en.py -- lib/lint-i18n.sh checks the two catalog pairs stay in
# sync.
#
# Addresses the user informally (du), matching how most contemporary
# German desktop software reads.
STRINGS = {
    "logout.title": "Abmelden",
    "logout.lock": "Sperren",
    "logout.restart": "Neu starten",
    "logout.shutdown": "Herunterfahren",
    "logout.cancel": "Abbrechen",

    "power.window_title": "Cyberbeest-Energieeinstellungen",
    "power.heading": "Verhalten bei gesperrtem Bildschirm",
    "power.info": (
        "Dieser Rechner sperrt sich nach 5 Minuten Inaktivität und fährt "
        "standardmäßig aus Sicherheitsgründen vollständig herunter, sobald er "
        "durchgehend gesperrt ist. Setze eine Zeit auf 0 für „Nie“, um die "
        "automatische Abschaltung für diese Stromquelle zu deaktivieren."
    ),
    "power.link_same_time": "Gleiche Zeit für Netz- und Akkubetrieb verwenden",
    "power.shutdown_after": "Abschalten nach (Minuten gesperrt):",
    "power.on_ac": "Im Netzbetrieb (Minuten gesperrt):",
    "power.on_battery": "Im Akkubetrieb (Minuten gesperrt):",
    "power.experimental": "Experimentell",
    "power.notif_checkbox": "Benachrichtigungen im Akkubetrieb bei gesperrtem Bildschirm abspielen",
    "power.detail": (
        "Wenn aktiviert, wechselt der Rechner im Akkubetrieb während dieser "
        "Stunde zwischen Ruhezustand und Aufwachen, statt vollständig wach zu "
        "bleiben, sodass Benachrichtigungstöne weiterhin gelegentlich "
        "durchkommen können, während deutlich weniger Strom verbraucht wird. "
        "Nachrichten können sich verspäten, bis zu der unten angegebenen "
        "Ruhezeit. Im Netzbetrieb hat das keine Auswirkung — der Rechner "
        "bleibt einfach für die gesamte Sperrzeit wach."
    ),
    "power.awake_minutes": "Wache Minuten pro Zyklus:",
    "power.asleep_minutes": "Ruhe-Minuten pro Zyklus:",
    "power.saved": "Gespeichert. Wird beim nächsten Sperrzyklus wirksam, kein Neustart nötig.",
    "power.never": "Nie",

    "timer.never": "Nie",
    "timer.lock_screen_after": "Bildschirm sperren nach:",
    "timer.lock_now": "Jetzt sperren",
    "timer.restart_now": "Jetzt neu starten",
    "timer.shutdown_now": "Jetzt herunterfahren",
    "timer.auto_shutdown_while_locked": "Automatisches Abschalten bei Sperrung",
    "timer.use_same_time": "Gleiche Zeit für Netz- und Akkubetrieb verwenden",
    "timer.important": "WICHTIG",
    "timer.no_auto_lock_note": "Automatisches Sperren ist aus, daher ist automatisches Abschalten deaktiviert",
    "timer.shutdown_after_both": "Abschalten nach Sperrdauer von:",
    "timer.on_ac": "Im Netzbetrieb:",
    "timer.on_battery": "Im Akkubetrieb:",
    "timer.power_saving_while_locked": "Energiesparen bei Sperrung…",

    "lockpower.window_title": "Cyberbeest Erweiterte Energieoptionen",
    "lockpower.info": (
        "Sobald der Bildschirm so lange gesperrt ist, werden Fenster "
        "minimiert und die CPU-Nutzung des Browsers begrenzt, um Energie "
        "zu sparen. Downloads und Benachrichtigungstöne funktionieren "
        "weiterhin, nur langsamer."
    ),
    "lockpower.minimize_after": "Fenster minimieren nach (Minuten):",
    "lockpower.limit_cpu": "Browser-CPU begrenzen auf (%):",
    "lockpower.never": "Nie",
    "lockpower.off": "Aus",
    "lockpower.close": "Schließen",

    "pw.window_title": "Cyberbeest-Passwörter & Start",
    "pw.master_title": "Master-Passwort",
    "pw.master_desc": "Das Passwort, mit dem deine Festplatte beim Start entschlüsselt wird.",
    "pw.short_title": "Kurzes Passwort",
    "pw.short_desc": (
        "Das Passwort, mit dem du dich anmeldest oder den Bildschirm "
        "entsperrst. Beide Passwörter werden benötigt, um das Gerät zu starten."
    ),
    "pw.current_password": "Aktuelles Passwort:",
    "pw.new_password": "Neues Passwort:",
    "pw.confirm_password": "Neues Passwort bestätigen:",
    "pw.generate": "Erzeugen",
    "pw.change_password": "Passwort ändern",
    "pw.cancel": "Abbrechen",
    "pw.hide_password": "Passwort verbergen",
    "pw.show_password": "Passwort anzeigen",
    "pw.generated_passphrase": (
        "Unten wurde eine neue Passphrase erzeugt — schreib sie auf oder "
        "merke sie dir, bevor du das Passwort änderst."
    ),
    "pw.recommended_format": (
        "Empfohlenes Format: {word_count} zufällige Wörter "
        "(Mindestlänge: {min_length} Zeichen)"
    ),
    "pw.fill_all_fields": "Bitte fülle alle Felder aus.",
    "pw.mismatch": "Das neue Passwort und die Bestätigung stimmen nicht überein.",
    "pw.too_short": "Das neue Passwort sollte mindestens {min_length} Zeichen lang sein.",
    "pw.waiting_auth": "Warte auf Authentifizierung…",
    "pw.confirm_written_title": "HAST DU ES WIRKLICH AUFGESCHRIEBEN ODER DIR GEMERKT?",
    "pw.confirm_written_secondary": "Dein Cyberbeest-{title} lautet: {password}",
    "pw.success": "Das Passwort wurde erfolgreich geändert.",
    "pw.auth_cancelled": "Die Authentifizierung wurde abgebrochen, das Passwort wurde daher nicht geändert.",
    "pw.wrong_current": "Das eingegebene aktuelle Passwort war nicht korrekt.",
    "pw.change_failed": "Das Passwort konnte nicht geändert werden.",
    "pw.details": "Details",
    "pw.unknown_error": "unbekannter Fehler",
    "pw.mark_temp_checkbox": "Das ist ein vorläufiges Passwort — erinnere mich, es später zu ändern",
    "pw.mark_temp_failed": "Das Passwort wurde geändert, konnte aber nicht als vorläufig markiert werden:",
    "pw.pkexec_error": "pkexec konnte nicht gestartet werden:",
    "pw.pty_error": "Pty konnte nicht geöffnet werden:",
    "pw.change_failed_wrong_current": (
        "Das Passwort konnte nicht geändert werden. Das bedeutet meist, dass "
        "das aktuelle Passwort falsch war."
    ),
    "pw.boot_screen_tab": "Startbildschirm",
    "pw.boot_name_desc": (
        "Gib ein Codewort ein, das bei der Passwortabfrage angezeigt wird, "
        "damit du dein Cyberbeest von den anderen unterscheiden kannst."
    ),
    "pw.boot_name_label": "Codewort:",
    "pw.save": "Speichern",
    "pw.boot_name_waiting": (
        "Warte auf Authentifizierung, danach wird das Boot-Image neu "
        "erstellt (dauert normalerweise etwa {seconds} Sekunden)…"
    ),
    "pw.boot_name_set": "Der Startbildschirm zeigt jetzt den Namen dieses Geräts.",
    "pw.boot_name_cleared": "Der Gerätename auf dem Startbildschirm wurde entfernt.",
    "pw.boot_name_auth_cancelled": (
        "Die Authentifizierung wurde abgebrochen, der Gerätename wurde daher "
        "nicht geändert."
    ),
    "pw.boot_name_failed": "Der Gerätename konnte nicht geändert werden.",
    "pw.boot_bright_mode_label": "Heller Bildschirm beim Entsperren",
    "pw.boot_bright_mode_desc": (
        "Eine improvisierte Taschenlampe: macht den Entsperrbildschirm hell "
        "statt schwarz, praktisch zum Tippen im Dunkeln."
    ),
    "pw.boot_bright_mode_on": "Der Startbildschirm ist beim Entsperren jetzt hell.",
    "pw.boot_bright_mode_off": "Der Startbildschirm hat wieder seinen normalen dunklen Hintergrund.",
    "pw.boot_bright_mode_auth_cancelled": (
        "Die Authentifizierung wurde abgebrochen, die Bildschirmhelligkeit "
        "wurde daher nicht geändert."
    ),
    "pw.boot_bright_mode_failed": "Die Bildschirmhelligkeit konnte nicht geändert werden.",

    "pw.sound_tab": "Ton",
    "pw.sound_startup_title": "Startton",
    "pw.sound_startup_desc": "Spielt, sobald die Audio-Hardware aufwacht, noch vor dem Entsperrbildschirm.",
    "pw.sound_shutdown_title": "Herunterfahrton",
    "pw.sound_shutdown_desc": "Spielt, wenn das Gerät tatsächlich ausgeschaltet wird (nicht beim Neustart).",
    "pw.sound_enabled": "Diesen Ton abspielen",
    "pw.sound_standard": "Cyberbeest-Standardton",
    "pw.sound_choose_file": "Sounddatei wählen…",
    "pw.sound_play": "Abspielen",
    "pw.sound_file_filter": "Sounddateien (wav, mp3, ogg)",
    "pw.sound_converting": "Sound wird konvertiert und installiert…",
    "pw.sound_install_failed": "Der Sound konnte nicht installiert werden.",
    "pw.sound_installed": "Sound installiert.",
    "pw.sound_select_failed": "Der Sound konnte nicht geändert werden.",
    "pw.sound_selected": "Sound geändert.",
    "pw.sound_enabled_on": "Dieser Ton wird jetzt abgespielt.",
    "pw.sound_enabled_off": "Dieser Ton ist jetzt stummgeschaltet.",
    "pw.sound_toggle_failed": "Konnte nicht ändern, ob dieser Ton abgespielt wird.",
    "pw.sound_play_failed": "Der Sound konnte nicht abgespielt werden.",
    "pw.sound_ffmpeg_missing": "ffmpeg ist nicht installiert, die Sounddatei konnte daher nicht konvertiert werden.",

    "nag.title": "Du verwendest noch das für dich eingerichtete Passwort",
    "nag.still_secure_default": (
        "noch das beim Einrichten zufällig erzeugte Passwort. Das ist an sich "
        "sicher — aber nur solange der Zettel, auf dem es notiert ist, "
        "getrennt von diesem Rechner aufbewahrt wird."
    ),
    "nag.still_temp_default": "noch das vorübergehende Standardpasswort. Bitte ändere es.",
    "nag.remind_later": "Später erinnern",
    "nag.change_now": "{title} jetzt ändern",
    "nag.keep": "{title} behalten",
    "nag.stop_nagging": "Nicht mehr erinnern",
    "nag.stop_notify_title": "Cyberbeest-Passwörter & Start",
    "nag.stop_notify_body": (
        "Du kannst deine Passwörter, den Namen auf dem Startbildschirm und "
        "die Start-/Herunterfahr-Klänge jederzeit über Einstellungen → "
        "Cyberbeest-Passwörter & Start ändern."
    ),

    "panelcolor.window_title": "Cyberbeest-Panelfarbe",
    "panelcolor.heading": "Panelfarbe",
    "panelcolor.info": (
        "Legt die Hintergrundfarbe des Panels fest und passt die "
        "Rahmenfarbe des KITT-Scanners und des Speichertank-Widgets "
        "automatisch daran an."
    ),
    "panelcolor.warning": (
        "Hinweis: Diese Widgets können aus technischen Gründen bis zu "
        "einer Minute brauchen, um nachzuziehen."
    ),
    "panelcolor.custom": "Eigene Farbe:",
    "panelcolor.applied": "Übernommen.",
    "panelcolor.preset_theme_default": "Theme-Standard",
    "panelcolor.preset_slate_blue": "Schieferblau",
    "panelcolor.preset_forest_green": "Waldgrün",
    "panelcolor.preset_warm_amber": "Warmes Bernstein",
    "panelcolor.preset_charcoal": "Anthrazit",
    "update_genmon.log_title": "Sicherheitsupdate-Protokoll",
    "update_genmon.log_missing": "Noch kein Update-Protokoll vorhanden -- die Prüfung wurde noch nicht ausgeführt.",
    "update_genmon.close": "Schließen",
}
