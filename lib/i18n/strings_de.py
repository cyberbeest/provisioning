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
    "logout.hibernate": "Ruhezustand",
    "logout.cancel": "Abbrechen",

    "hibernate.splash_text": "RUHEZUSTAND",

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
    "timer.hibernate_now": "Jetzt in den Ruhezustand",
    "timer.auto_shutdown_while_locked": "Automatisches Abschalten bei Sperrung",
    "timer.use_same_time": "Gleiche Zeit für Netz- und Akkubetrieb verwenden",
    "timer.important": "WICHTIG",
    "timer.no_auto_lock_note": "Automatisches Sperren ist aus, daher ist automatisches Abschalten deaktiviert",
    "timer.shutdown_after_both": "Abschalten nach Sperrdauer von:",
    "timer.on_ac": "Im Netzbetrieb:",
    "timer.on_battery": "Im Akkubetrieb:",
    "timer.power_saving_while_locked": "Erweiterte Energieoptionen…",

    "settings.window_title": "Cyberbeest Einstellungen",
    "settings.props_title": "Eigenschaften: {name}",
    "settings.props_info": "Änderungen gelten sofort.",
    "settings.tab_power": "Erweiterte Energieoptionen",
    "settings.apply": "Übernehmen",
    "settings.ok": "OK",
    "settings.tab_panel": "Leiste",
    "settings.tab_wallpaper": "Hintergrund",
    "wallpaper.info": "Wähle das Cyberbeest-Bild, dein eigenes Bild oder eine Fotoreihe, die stündlich wechselt.",
    "wallpaper.standard": "Cyberbeest-Standard",
    "wallpaper.previous": "Einzelnes Bild (dein voriges)",
    "wallpaper.nature": "Naturfotos",
    "wallpaper.space": "Weltraumfotos",
    "wallpaper.architecture": "Architekturfotos",
    "wallpaper.cars": "Autofotos",
    "wallpaper.cities": "Stadtfotos",
    "wallpaper.coast": "Küsten- und Meerfotos",
    "wallpaper.art": "Gemälde",
    "wallpaper.desktop_settings": "Einstellungen für den Desktophintergrund…",
    "wallpaper.credits": "Bildnachweise",
    "settings.tab_butler": "Butler",
    "butler.info": "Butler versteht Befehle und Fragen, die du in die Suche des Menüs tippst, zum Beispiel „Bildschirm heller“ oder „Ist meine Festplatte sicher?“. Bei Benutzung braucht er etwa 500 MB Arbeitsspeicher.",
    "butler.enabled": "Butler im Menü verwenden",
    "butler.note": "Änderungen gelten beim nächsten Öffnen des Menüs.",
    "settings.tab_weather": "Wetter",
    "weather.accuracy": "Außerhalb Deutschlands kann die Anzeige ungenau sein: Sie stammt von der nächsten Station des Deutschen Wetterdienstes, die weit entfernt sein kann.",
    "weather.info": "Zeigt die aktuelle Temperatur oben im Menü. Es wird nichts abgefragt, bis du einen Ort gewählt und das Wetter eingeschaltet hast.",
    "weather.city": "Ort oder Postleitzahl",
    "weather.search": "Suchen",
    "weather.searching": "Suche läuft …",
    "weather.pick": "Wähle deinen Ort aus der Liste.",
    "weather.nothing": "Kein Ort gefunden.",
    "weather.error": "Die Suche ist fehlgeschlagen. Bist du online?",
    "weather.none": "Noch kein Ort gewählt.",
    "weather.current": "Ort: {place}",
    "weather.enabled": "Wetter im Menü anzeigen",
    "weather.note": "Beim Öffnen des Menüs gehen dann deine IP-Adresse und der Ort, auf etwa 1 km gerundet, an api.brightsky.dev (Daten des Deutschen Wetterdienstes). Die Ortssuche fragt OpenStreetMap. Ein VPN deckt beides ab. Änderungen gelten beim nächsten Öffnen des Menüs.",
    "panel.info": "Wähle, welche Leiste am unteren Bildschirmrand angezeigt wird. Die Änderung gilt, sobald du auf „Übernehmen“ oder „OK“ klickst, und bleibt bis zur nächsten Anmeldung erhalten.",
    "panel.xfce": "XFCE-Leiste (Standard)",
    "panel.gopanel": "Cyberbeest-Leiste",
    "panel.note": "Die Leisten wechseln innerhalb weniger Sekunden.",
    "panel.bg_label": "Hintergrund der Leiste:",
    "panel.bg_off": "Feste Farbe",
    "panel.bg_24h": "Langsamer Farbverlauf, ein Durchlauf in 24 Stunden",
    "panel.bg_1h": "Langsamer Farbverlauf, ein Durchlauf in 1 Stunde",
    "panel.bg_5m": "Langsamer Farbverlauf, ein Durchlauf in 5 Minuten",
    "panel.bg_1m": "Langsamer Farbverlauf, ein Durchlauf in 1 Minute",
    "panel.bg_10s": "Farbverlauf, ein Durchlauf in 10 Sekunden",
    "panel.bg_wild": "Wilder Modus: Die Farben wechseln zwischen hell und sehr dunkel",
    "panel.bg_note": "Nur die Cyberbeest-Leiste. Die Farben wandern durch helle Pastelltöne; 24 Stunden folgt der Tageszeit.",
    "panel.monitor_label": "Cyberbeest-Leiste anzeigen auf:",
    "panel.monitor_auto": "Automatisch (Hauptbildschirm)",
    "panel.monitor_all": "Allen Bildschirmen (Kopien der Leiste)",
    "panel.monitor_note": "Die Kopien zeigen alles außer Tray-Symbolen, die eigene Fenster sind; diese bleiben auf der Hauptleiste.",

    "lockpower.window_title": "Cyberbeest Erweiterte Energieoptionen",
    "lockpower.info": (
        "Sobald der Bildschirm so lange gesperrt ist, werden Fenster "
        "minimiert und die CPU-Nutzung des Browsers begrenzt, um Energie "
        "zu sparen. Downloads und Benachrichtigungstöne funktionieren "
        "weiterhin, nur langsamer."
    ),
    "lockpower.curtain_enabled": "Bildschirm beim Sperren sofort abdecken (empfohlen)",
    "lockpower.minimize_after": "Fenster minimieren nach (Minuten):",
    "lockpower.limit_cpu": "Browser-CPU begrenzen auf (%):",
    "lockpower.warn_enabled": "Vor dem automatischen Sperren warnen",
    "lockpower.warn_seconds": "So viele Sekunden vorher warnen:",
    "lockpower.never": "Nie",
    "lockpower.off": "Aus",
    "lockpower.no_mercy_enabled": "Keine Gnade: Sperre erzwingen, auch wenn eine App wach bleiben möchte",
    "lockpower.no_mercy_info": (
        "Ignoriert Videowiedergabe, Präsentationen und jede andere "
        "Anfrage einer App, die Sperre zu verzögern -- der Bildschirm "
        "sperrt sich planmäßig, egal was läuft. Kann etwas unterbrechen, "
        "das gerade angeschaut wird."
    ),
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
    "pw.progress_title": "Passwortänderung läuft",
    "pw.progress_message": "Passwort wird geändert, bitte warten…",
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
    "update_genmon.log_last_run": "Protokoll des letzten Update-Laufs:",
    "update_genmon.log_live": "Updates laufen -- Live-Ausgabe:",
    "update_genmon.log_starting": "Update-Lauf wird gestartet...",
    "update_genmon.close": "Schließen",
    "update_genmon.reboot_now": "Jetzt neu starten",
    "update_genmon.run_now": "Jetzt aktualisieren",
    "update_genmon.run_now_already_running": "Eine Update-Prüfung läuft bereits.",
    "update_genmon.run_now_failed": "Update-Prüfung konnte nicht gestartet werden.",
    "update_genmon.settings": "Einstellungen...",
    "update_genmon.settings_title": "Einstellungen für Sicherheitsupdates",
    "update_genmon.settings_save_failed": "Die Einstellung konnte nicht gespeichert werden.",
    "update_genmon.delay_prompt": "Nach dem Start warten, bevor nach Updates gesucht wird:",
    "update_genmon.delay_hint": "In den ersten Minuten nach dem Einschalten werden keine Updates installiert. Die nächste Prüfung danach holt sie nach.",
    "update_genmon.save": "Speichern",
    "update_genmon.cancel": "Abbrechen",
    "update_genmon.interrupted": (
        "Die letzte Update-Prüfung wurde unterbrochen (vermutlich durch ein "
        "Herunterfahren oder einen Neustart mittendrin) -- sie wird "
        "automatisch zum nächsten planmäßigen Zeitpunkt wiederholt."
    ),

    "run_gui.window_title": "Cyberbeest-Provisioning-Runner",
    "run_gui.confirm_remove_openssh": (
        "Dies entfernt den SSH-Server dauerhaft und löscht die "
        "authorized_keys aller Benutzer -- der Fernzugriff per SSH auf "
        "diesen Rechner wird damit gekappt.\n\n"
        "Fortfahren?"
    ),
    "run_gui.state_pending": "ausstehend",
    "run_gui.state_running": "läuft...",
    "run_gui.state_done": "fertig",
    "run_gui.state_failed": "fehlgeschlagen",
    "run_gui.state_skipped": "übersprungen",
    "run_gui.profile_dialog_title": "Provisioning-Profil",
    "run_gui.profile_save": "_Speichern",
    "run_gui.profile_start_one_script": "1 Skript starten",
    "run_gui.profile_start_n_scripts": "{count} Skripte starten",
    "run_gui.profile_country_label": "Land:",
    "run_gui.profile_ui_language_label": "Oberflächensprache:",
    "run_gui.profile_lang_english": "English",
    "run_gui.profile_lang_german": "Deutsch",
    "run_gui.profile_keyboard_label": "Tastaturlayout:",
    "run_gui.profile_menu_key_remap": (
        "Menü-Taste auf </>/| umbelegen (nur auf originaler Cyberbeest-Hardware, "
        "deutsche Tastatur)"
    ),
    "run_gui.profile_timezone_label": "Zeitzone:",
    "run_gui.profile_touchpad_label": "Touchpad:",
    "run_gui.profile_touchpad_checkbox": (
        "Cyberbeest-Touchpad-Feinabstimmung anwenden (Tippen zum Klicken "
        "überall, Empfindlichkeit/Scrollen abgestimmt auf Referenz-Hardware)"
    ),
    "run_gui.profile_sounds_label": "Töne:",
    "run_gui.profile_sounds_checkbox": "Cyberbeest-Start- und Abschalt-Töne abspielen und die Lautstärke auf Maximum setzen",
    "run_gui.profile_plymouth_pointer_label": "Startbildschirm:",
    "run_gui.profile_plymouth_pointer_checkbox": "Mauszeiger auf dem Startbildschirm und bei der Passwortabfrage für die Festplatte anzeigen",
    "run_gui.profile_dictation_model_label": "Diktat:",
    "run_gui.profile_dictation_model_checkbox": "Sprachmodell für das Diktieren herunterladen (140–640 MB)",
    "run_gui.profile_vm_image_label": "VM-Image:",
    "run_gui.profile_vm_image_checkbox": "Cyberbeest-VM-Image herunterladen (KVM)",
    "run_gui.profile_vm_update_label": "VM-Update:",
    "run_gui.profile_vm_update_checkbox": (
        "Cyberbeest-VM auf die neue Version aktualisieren "
        "(die alte VM bleibt als Sicherung in der Virtuellen Maschinenverwaltung erhalten)"
    ),
    "run_gui.profile_vm_update_space": (
        "Freier Speicherplatz: {free}. Aktuelle VM: {current}. Das Update braucht {needed}."
    ),
    "run_gui.profile_vm_update_previous_backup": (
        "Die vorherige Sicherung ({size}) wird gelöscht."
    ),
    "run_gui.profile_vm_update_no_space": (
        "Nicht genug freier Speicherplatz für das Update."
    ),
    "run_gui.profile_vm_update_tooltip": (
        "Eine neuere Version der Cyberbeest-VM ist verfügbar. Beim Update wird sie "
        "heruntergeladen (etwa {download}) und als frische VM eingerichtet: Du beginnst "
        "mit einer leeren VM und meldest dich in deinen Apps neu an.\n\n"
        "Deine bisherige VM bleibt als Sicherung erhalten und ist weiter in der Virtuellen Maschinenverwaltung "
        "verfügbar, es geht also nichts verloren. Es wird nur eine Sicherung aufbewahrt. "
        "Die VM muss während des Updates ausgeschaltet sein. Dateien im Ordner "
        "VM-Shared sind nicht betroffen."
    ),
    "run_gui.button_run_changed": "Geänderte Skripte ausführen",
    "run_gui.button_run_changed_count": "Geänderte Skripte ausführen ({count})",
    "run_gui.button_run_all": "Alles ausführen",
    "run_gui.button_run_selected": "Auswahl ausführen",
    "run_gui.button_profile": "Profil...",
    "run_gui.button_select_all": "Alles auswählen",
    "run_gui.filter_placeholder": "Skripte filtern…",
    "run_gui.button_stop": "Nach aktuellem Skript stoppen",
    "run_gui.button_abort_download": "Download abbrechen",
    "run_gui.button_view_source": "Quelltext ansehen",
    "run_gui.view_source_title": "Quelltext: {script}",
    "run_gui.status_abort_download_none": "Kein laufender Download zum Abbrechen gefunden.",
    "run_gui.status_abort_download_killed": "Download abgebrochen -- das aktuelle Skript sollte in Kürze mit einem Fehler beenden.",
    "run_gui.more_actions_tooltip": "Weitere Aktionen",
    "run_gui.menu_disable_autostart": "Automatisches Provisioning beim Anmelden deaktivieren",
    "run_gui.menu_select_vm_scripts": "Skripte für VM-Installation auswählen",
    "run_gui.menu_switch_to_update": "Aktualisieren...",
    "run_gui.timing_summary": "{elapsed} | {remaining} | {total}",
    "run_gui.status_idle": "Bereit. Doppelklick auf ein Skript unten, um nur dieses auszuführen.",
    "run_gui.status_idle_changed": "{count} geänderte Skripte. Doppelklick auf ein Skript unten, um nur dieses auszuführen.",
    "run_gui.todo_frame_title": "Nach dem Provisioning noch zu erledigen",
    "run_gui.log_hasnt_run_this_session": (
        "-- {script} wurde in dieser Sitzung noch nicht ausgeführt; zeige das "
        "Protokoll eines früheren Laufs --\n\n"
    ),
    "run_gui.log_hasnt_run_yet": "{script} wurde noch nicht ausgeführt. Doppelklick zum Ausführen.\n",
    "run_gui.status_running_script": "Läuft: {script}",
    "run_gui.status_running_script_elapsed": "Läuft: {script} ({elapsed})",
    "run_gui.status_nothing_to_run": "Nichts auszuführen -- bereits alles auf dem neuesten Stand.",
    "run_gui.status_nothing_selected": (
        "Nichts ausgewählt -- erst unten ein oder mehrere Skripte anklicken "
        "(oder Strg/Umschalt+Klick)."
    ),
    "run_gui.status_vm_scripts_selected": (
        "{count} Skripte für VM-Installation ausgewählt -- unten prüfen, "
        "dann auf \"Auswahl ausführen\" klicken."
    ),
    "run_gui.status_starting": "{label}: startet (sudo-Passwort eingeben, falls gefragt)...",
    "run_gui.menu_run_script": "{script} ausführen",
    "run_gui.menu_run_scripts": "{count} ausgewählte Skripte ausführen",
    "run_gui.menu_mark_dones": "{count} ausgewählte Skripte als erledigt markieren",
    "run_gui.menu_mark_done": "{script} als erledigt markieren",
    "run_gui.status_marked_done": "{count} Skript(e) als erledigt markiert",
    "run_gui.label_run_single": "{script} ausführen",
    "run_gui.dismiss_button": "Verwerfen",
    "run_gui.action_open_desktop_settings": "Desktop-Einstellungen öffnen",
    "run_gui.action_open_password_settings": "Passwörter & Start öffnen",
    "run_gui.reboot_confirm_title": "Jetzt neu starten?",
    "run_gui.reboot_confirm_secondary": "Der Rechner wird sofort neu gestartet.",
    "run_gui.confirm_run_title": "{script} ausführen?",
    "run_gui.log_opening_terminal": (
        "=== {script} wird in einem Terminalfenster geöffnet (braucht ein "
        "interaktives Terminal) -- dort abschließen ===\n"
    ),
    "run_gui.log_stop_requested": "=== Stopp angefordert: {count} verbleibende(s) Skript(e) übersprungen ===\n",
    "run_gui.log_skipped_declined": "=== {script} übersprungen (früher abgelehnt; einzeln ausführen, um erneut gefragt zu werden) ===\n",
    "run_gui.log_skipped": "=== {script} übersprungen (nicht bestätigt) ===\n",
    "run_gui.log_running_marker": "=== {script} läuft ===\n",
    "run_gui.log_done_marker": "=== {script} fertig ({duration}) ===\n",
    "run_gui.log_failed_marker": "=== {script} FEHLGESCHLAGEN ({duration}, Exitcode {status}) ===\n",
    "run_gui.log_failed_password": (
        "Das sieht nach einem falschen Sudo-Passwort aus, nicht nach einem "
        "Problem mit {script} selbst. Einfach erneut ausführen und das "
        "Passwort neu eingeben.\n"
    ),
    "run_gui.log_stopping_dependency": "Stoppe hier, da spätere Skripte hiervon abhängen könnten.\n",
    "run_gui.log_apt_retry": (
        "Ein Paketserver hatte ein vorübergehendes Problem. {script} wird in "
        "{seconds} Sekunden erneut versucht (Wiederholung {attempt} von {total}).\n"
    ),
    "run_gui.status_stopped": "Nach aktuellem Skript gestoppt.",
    "run_gui.status_failed": "Fehlgeschlagen: {script} -- siehe Protokoll oben.",
    "run_gui.status_finished": "Erfolgreich abgeschlossen. Du kannst dieses Fenster jetzt schließen.",
    "run_gui.todo_reboot_text": "Neu starten, um alle Änderungen dieses Laufs vollständig zu übernehmen.",
    "run_gui.todo_reboot_action": "Jetzt neu starten",
    "run_gui.disable_autostart_confirm_title": "Automatisches Provisioning beim Anmelden deaktivieren?",
    "run_gui.disable_autostart_message": (
        "Dieser Rechner bietet Provisioning beim Anmelden künftig nicht mehr "
        "automatisch an."
    ),
    "run_gui.disable_autostart_pending_note": (
        "\n\n{count} Skript(e) sind noch nicht abgeschlossen:\n{list}\n\n"
        "Du kannst dieses Tool jederzeit manuell starten (beestify.sh)."
    ),
    "run_gui.status_disable_autostart_failed": "{path} konnte nicht entfernt werden: {error}",
    "run_gui.status_autostart_disabled": (
        "Automatisches Provisioning beim Anmelden deaktiviert. Starte beestify.sh "
        "jederzeit manuell, um dort weiterzumachen, wo du aufgehört hast."
    ),
    "run_gui.status_stop_requested": "Stopp angefordert -- aktuelles Skript wird noch beendet, dann Stopp...",

    "askpass.title": "Cyberbeest provisioning",
    "askpass.heading": "Gib dein kurzes Passwort ein, um die Provisioning-Skripte als root auszuführen:",
    "askpass.field_label": "Kurzes Passwort:",

    "update.title": "Cyberbeest-Update",
    "update.confirm_message": (
        "Dieser Computer wurde mit dem Cyberbeest-<b>{track}</b>-Repository eingerichtet.\n\n"
        "Die neuesten Updates aus diesem Repository holen?"
    ),
    "update.last_pull_message": "Zuletzt aktualisiert: {when} ({relative})",
    "update.last_pull_never": "Noch nie aktualisiert.",
    "update.version_label": "Version: {version}",

    "relative.just_now": "gerade eben",
    "relative.minute_ago": "vor {n} Minute",
    "relative.minutes_ago": "vor {n} Minuten",
    "relative.hour_ago": "vor {n} Stunde",
    "relative.hours_ago": "vor {n} Stunden",
    "relative.day_ago": "vor {n} Tag",
    "relative.days_ago": "vor {n} Tagen",
    "relative.month_ago": "vor {n} Monat",
    "relative.months_ago": "vor {n} Monaten",
    "relative.year_ago": "vor {n} Jahr",
    "relative.years_ago": "vor {n} Jahren",
    "update.button_no": "Abbrechen",
    "update.button_yes": "Updates herunterladen",
    "update.switch_button": "Track wechseln",
    "update.switch_menu_item": "Stattdessen zu {track} wechseln",
    "update.files_heading": "Geänderte Dateien",
    "update.no_changes_message": "Keine Änderungen seit dem letzten Update.",
    "update.status_added": "Hinzugefügt",
    "update.status_modified": "Geändert",
    "update.status_deleted": "Gelöscht",
    "update.status_renamed": "Umbenannt",
    "update.status_copied": "Kopiert",
    "update.status_other": "{code}",
    "update.column_file": "Datei",
    "update.column_comment": "Kommentar",
    "update.column_date": "Datum",
    "update.diff_row_button": "Dateiunterschiede anzeigen",
    "update.recheck_button_tooltip": "Erneut bei GitHub nachsehen",
    "update.recheck_failed_tooltip": "GitHub nicht erreichbar -- gleich noch einmal versuchen.",
    "update.diff_dialog_title": "Unterschiede: {path} ({date})",
    "update.diff_column_before": "Vorher",
    "update.diff_column_after": "Nachher",
    "update.close_button": "Schließen",

    "clipboard.label_text": "Text",
    "clipboard.label_image": "Bild",
    "clipboard.label_image_file": "Bild + Datei",
    "clipboard.label_files": "Dateipfad(e)",
    "clipboard.label_unknown": "Unbekannter Inhalt",
    "clipboard.empty": "Zwischenablage ist leer",
    "clipboard.clears_in": " — wird geleert in {duration}",
    "clipboard.view_edit": "Anzeigen / Bearbeiten…",
    "clipboard.show_image": "Bild anzeigen",
    "clipboard.open_file": "Datei öffnen",
    "clipboard.show_in_folder": "Im Ordner zeigen",
    "clipboard.show_in_folders": "In Ordnern zeigen ({count} Fenster)",
    "clipboard.view": "Anzeigen…",
    "clipboard.convert_png": "In PNG umwandeln",
    "clipboard.convert_jpeg": "In JPEG umwandeln",
    "clipboard.clear_clipboard": "Zwischenablage leeren",
    "clipboard.auto_clear_settings": "Einstellungen für automatisches Leeren…",
    "clipboard.window_title": "Zwischenablage",
    "clipboard.contains_image": "Zwischenablage enthält ein Bild",
    "clipboard.contains_files": "Zwischenablage enthält Dateipfad(e):",
    "clipboard.contains_text": "Zwischenablage enthält Text (bearbeitbar):",
    "clipboard.formatting_warning": "Dieser Eintrag enthält auch Formatierung (z. B. HTML), die hier nicht angezeigt wird und beim Bearbeiten oder Speichern verloren geht.",
    "clipboard.contains_unknown": "Zwischenablage enthält unbekannten Inhalt",
    "clipboard.close": "Schließen",
    "clipboard.save_changes": "Änderungen speichern",
    "clipboard.autoclear_title": "Automatisches Leeren der Zwischenablage",
    "clipboard.autoclear_prompt": "Zwischenablage automatisch leeren nach:",
    "clipboard.never": "Nie",

    "report.window_title": "Fehlerbericht senden",
    "report.intro": (
        "{script} ist fehlgeschlagen. Du kannst diesen Bericht an das "
        "Cyberbeest-Team senden, damit wir den Fehler beheben können. Genau "
        "dieser Text wird gesendet -- du kannst vorher alles ändern oder löschen."
    ),
    "report.privacy_note": (
        "Persönliche Angaben wie dein Name, Netzwerknamen und Adressen wurden "
        "ersetzt. Der Bericht enthält keine Gerätekennung, und der Server "
        "speichert deine IP-Adresse nicht."
    ),
    "report.no_log": "(keine Protokolldatei gefunden)",
    "report.send": "Senden",
    "report.cancel": "Abbrechen",
    "report.close": "Schließen",
    "report.sending": "Wird gesendet...",
    "report.sent": "Gesendet, danke! Berichts-ID: {reply}",
    "report.failed": "Der Bericht konnte nicht gesendet werden: {error}",
    "report.empty": "Der Bericht ist leer -- nichts zu senden.",
    "report.too_large": "Der Bericht ist zu groß (max. 64 KB). Bitte kürze ihn.",
    "run_gui.todo_report_text": "{script} ist fehlgeschlagen. Ein Bericht hilft uns, den Fehler zu beheben.",
    "run_gui.todo_report_action": "Bericht senden...",

    "vpn.window_title": "Cyberbeest VPN",
    "vpn.status_heading": "VPN-Status",
    "vpn.disconnect": "Trennen",
    "vpn.status_connected": "Verbunden: {name}",
    "vpn.status_not_connected_no_profiles": "Nicht verbunden. Noch keine Profile importiert.",
    "vpn.status_not_connected": "Nicht verbunden.",
    "vpn.kill_switch_label": "Automatischer Kill Switch:",
    "vpn.kill_switch_body": (
        "Jedes hier importierte VPN-Profil bekommt automatisch einen Kill "
        "Switch, falls es noch keinen hat — bricht der Tunnel unerwartet "
        "ab, wird dein Datenverkehr blockiert, statt stillschweigend auf "
        "deine ungeschützte Verbindung zurückzufallen."
    ),
    "vpn.providers_heading": "Bekanntermaßen unterstützte VPNs (Stand {date})",
    "vpn.open_button": "{name} öffnen",
    "vpn.install_button": "Installieren...",
    "vpn.signup_button": "Registrieren",
    "vpn.other_heading": "Jeder andere VPN-Anbieter",
    "vpn.other_note": (
        "Jeder Anbieter, der eine WireGuard-.conf-Datei ausgibt, "
        "funktioniert, auch wenn er oben nicht aufgeführt ist. Importiere "
        "sie hier — Cyberbeest fügt automatisch einen Kill Switch hinzu, "
        "falls die Konfiguration noch keinen hat."
    ),
    "vpn.import_button": "VPN-Profil importieren...",

    "vpn.mullvad_note": (
        "Anmeldung per Kontonummer, keine E-Mail nötig. Installation über "
        "die Cyberbeest-Paketverwaltung — optional, weil danach ein "
        "eigener Hintergrunddienst läuft."
    ),
    "vpn.mullvad_badge": "Ohne Protokolle, auditiert",
    "vpn.mullvad_detail": (
        "Mullvad (Schweden) veröffentlicht eine No-Logs-Richtlinie und "
        "hat sie von unabhängigen externen Prüfern (Cure53, Assured AB) "
        "bestätigen lassen. Die Registrierung braucht weder E-Mail noch "
        "persönliche Daten — nur eine generierte Kontonummer —, sodass es "
        "schon im Prinzip weniger zu protokollieren gibt."
    ),

    "vpn.protonvpn_note": (
        "Installation über die Cyberbeest-Paketverwaltung — aus demselben "
        "Grund optional wie bei Mullvad. Offiziell für GNOME gedacht, "
        "funktioniert aber auch auf diesem Xfce-System."
    ),
    "vpn.protonvpn_badge": "Ohne Protokolle, auditiert",
    "vpn.protonvpn_detail": (
        "Proton VPN (Schweiz) veröffentlicht eine No-Logs-Richtlinie, die "
        "2022 unabhängig von SEC Consult geprüft wurde. Gehört zum "
        "selben Mutterunternehmen wie Proton Mail."
    ),

    "vpn.ivpn_note": (
        "Registrieren, eine WireGuard-Konfiguration herunterladen und "
        "unten importieren."
    ),
    "vpn.ivpn_badge": "Ohne Protokolle, auditiert",
    "vpn.ivpn_detail": (
        "IVPN (Gibraltar) veröffentlicht eine No-Logs-Richtlinie, "
        "veröffentlicht eigene externe Prüfberichte und führt einen "
        "Warrant Canary (eine regelmäßig aktualisierte Erklärung, dass "
        "keine geheime behördliche Anordnung vorliegt — bleibt sie aus, "
        "ist das das Warnsignal)."
    ),

    "vpn.airvpn_note": (
        "Registrieren, eine WireGuard-Konfiguration erzeugen und unten "
        "importieren."
    ),
    "vpn.airvpn_badge": "Ohne Protokolle, nicht auditiert",
    "vpn.airvpn_detail": (
        "AirVPN (Italien) behauptet eine No-Logs-Richtlinie und hat in "
        "der Privatsphäre-Community einen guten Ruf, hat das aber — "
        "anders als die drei oben — bislang nicht durch eine unabhängige "
        "externe Prüfung bestätigen lassen. Italien gilt als EU-Rechtsraum "
        "manchen Datenschutz-Fürsprechern zufolge zudem als etwas "
        "schwächerer rechtlicher Schutz als Schweden/Schweiz/Gibraltar, "
        "was aber weniger ins Gewicht fällt, wenn wirklich nichts "
        "protokolliert wird, das herausgegeben werden könnte."
    ),

    "vpn.menu_empty": "Noch keine VPN-Profile importiert",
    "vpn.menu_connected": "✓ {name} (verbunden)",
    "vpn.menu_connect": "Verbinden: {name}",
    "vpn.menu_import": "Neues Profil importieren...",
    "vpn.menu_remove": "Profil entfernen",
    "vpn.menu_hide_icon": "Symbol entfernen",
    "vpn.menu_hide_icon_connected": "Trennen und Symbol entfernen",
    "vpn.show_icon_button": "VPN-Symbol anzeigen",
    "vpn.status_icon_hidden": "VPN-Symbol ausgeblendet ({count} Profil(e) gespeichert, nicht verbunden).",

    "sharedfolders.window_title": "Zugelassene Ordner",
    "sharedfolders.intro": "Wähle die Ordner, die für geschützte Apps sichtbar sind.",
    "sharedfolders.col_folder": "Ordner",
    "sharedfolders.col_contents": "Inhalt",
    "sharedfolders.counting": "Z\u00e4hle\u2026",
    "sharedfolders.count": "{folders}, {files}",
    "sharedfolders.choose": "Ordner f\u00fcr deine Apps freigeben",
    "sharedfolders.share": "Freigeben",
    "sharedfolders.cancel": "Abbrechen",
    "sharedfolders.err_chars": "Der Ordnername enth\u00e4lt Zeichen, die nicht sicher freigegeben werden k\u00f6nnen.",
    "sharedfolders.err_not_dir": "Das ist kein Ordner.",
    "sharedfolders.err_home": "Dein gesamter Home-Ordner kann nicht freigegeben werden. W\u00e4hle einen Ordner darin.",
    "sharedfolders.err_hidden": "Versteckte Ordner enthalten Einstellungen und Schl\u00fcssel und k\u00f6nnen nicht freigegeben werden.",
    "sharedfolders.err_location": "Nur Ordner in deinem Home-Ordner oder auf Wechseldatentr\u00e4gern k\u00f6nnen freigegeben werden.",
    "sharedfolders.err_firejail": "Die Schutzumgebung akzeptiert diesen Ordner nicht, er wurde nicht hinzugef\u00fcgt.",
    "sharedfolders.add_tip": "Einen weiteren Ordner für geschützte Apps freigeben",
    "sharedfolders.remove_tip": "Freigabe des ausgewählten Ordners beenden",
    "sharedfolders.added": "Ordner freigegeben.",
    "sharedfolders.removed": "Ordner entfernt.",
    "sharedfolders.restart_note": "Laufende Apps neu starten, damit Änderungen wirken.",
    "sharedfolders.restart_btn": "Apps neu starten…",
    "sharedfolders.restart_q": "Diese Apps jetzt neu starten?",
    "sharedfolders.restart_warn": "Nicht gespeicherte Arbeit darin kann verloren gehen.",
    "sharedfolders.restart_do": "Neu starten",
    "sharedfolders.restarted": "Apps neu gestartet.",
    "sharedfolders.folder_one": "{n} Ordner",
    "sharedfolders.folder_many": "{n} Ordner",
    "sharedfolders.file_one": "{n} Datei",
    "sharedfolders.file_many": "{n} Dateien",
    "sharedfolders.missing": "Nicht gefunden",
    "sharedfolders.none_running": "Es laufen keine geschützten Apps.",
    "sharedfolders.step_closing": "{app} wird geschlossen…",
    "sharedfolders.step_starting": "{app} wird neu gestartet…",
    "sharedfolders.step_done": "Fertig: {n} App(s) neu gestartet.",
    "sharedfolders.step_none": "Es konnte nichts neu gestartet werden.",

    "connections.window_title": "Netzwerkverbindungen nach App",
    "connections.col_app": "App / Gegenstelle",
    "connections.col_port": "Port / Anzahl",
    "connections.col_direction": "Richtung",
    "connections.col_host": "Hostname (Reverse-DNS)",
    "connections.n_incoming": "{n} eingehend",
    "connections.dir_incoming": "⬇ eingehend",
    "connections.dir_outgoing": "ausgehend",
    "connections.system_service": "Systemdienst",
    "connections.sandboxed": "abgeschottet",
    "connections.unknown": "unbekannt",
    "connections.status": "{total} Verbindungen ({incoming} eingehend), {apps} Apps. Aktualisiert alle {secs} s. Hostnamen sind nur Reverse-DNS-Hinweise.",

    "welcome.title": "Willkommen bei Cyberbeest",
    "welcome.heading": "Willkommen bei Cyberbeest",
    "welcome.sub": "Ein paar Dinge, die man wissen sollte:",
    "welcome.close": "Schließen",
    "welcome.never": "Nicht mehr anzeigen",

    "welcome.s1_eyebrow": "02 · SPRACHSTEUERUNG",
    "welcome.s1_title": "Sie können mit Ihrem Computer sprechen!",
    "welcome.s1_lead": "Ihr Computer wird per Sprache gesteuert, mit lokaler, vollkommen privater KI.",
    "welcome.f9_title": "F9 halten zum Diktieren in jeder App",
    "welcome.f9_text": "Taste halten, sprechen, loslassen. Ihre Worte erscheinen dort, wo der Cursor steht: in einer Nachricht, einem Dokument oder im Browser. Funktioniert in 25 Sprachen.",
    "welcome.win_title": "Drücken öffnet das Startmenü, Halten zum Sprechen",
    "welcome.win_text": "Probieren Sie „Mach den Bildschirm heller“ oder „Öffne Google“.",
    "welcome.s2_eyebrow": "03 · SICHERHEIT",
    "welcome.s2_title": "So sperren oder schalten Sie in jedem Notfall aus",
    "welcome.sec_lock_badge": "SPERRE",
    "welcome.sec_lock_title": "Automatische Sperre",
    "welcome.sec_lock_text": "Nach einer eingestellten Zeit ohne Maus- oder Tastaturbewegung sperrt sich der Bildschirm von selbst. 10 Sekunden vorher erscheint eine Warnung; eine Mausbewegung hält Sie angemeldet.",
    "welcome.sec_off_badge": "AUS",
    "welcome.sec_off_title": "Automatisches Herunterfahren",
    "welcome.sec_off_text": "Nach 60 Minuten im gesperrten Zustand schaltet sich der Laptop vollständig aus. Ein Klick auf den Timer in der Leiste ändert die Zeit.",
    "welcome.sec_lid_badge": "DECKEL",
    "welcome.sec_lid_title": "Deckel zuklappen",
    "welcome.sec_lid_text": "Beim Zuklappen sperrt sich der Laptop sofort und der Bildschirm geht aus.",
    "welcome.sec_4x_badge": "4×",
    "welcome.sec_4x_title": "Ein-/Ausschalter viermal drücken",
    "welcome.sec_4x_text": "Vier schnelle Drücke hintereinander schalten den Laptop sofort ganz aus.",
    "welcome.sec_hold_badge": "10 s",
    "welcome.sec_hold_title": "Ein-/Ausschalter gedrückt halten",
    "welcome.sec_hold_text": "Wenn nichts anderes hilft: Ein-/Ausschalter 10 Sekunden gedrückt halten. Das trennt den Laptop sofort vom Strom.",
    "welcome.sec_note": "Ein einzelner Druck auf den Ein-/Ausschalter öffnet einen Dialog mit Sperren, Neustart und Herunterfahren. Ihr Cyberbeest ist nur aus, wenn alle blauen LEDs dunkel sind.",
    "welcome.s3_eyebrow": "04 · DIE LEISTE",
    "welcome.s3_title": "Was die Symbole in der Leiste bedeuten",
    "welcome.s3_lead": "Fahren Sie mit der Maus über ein Symbol in der Leiste, um zu sehen, wofür es da ist.",
    "welcome.s3_nohl": "Die Erklärungen unten gelten für die Standardleiste.",
    "welcome.s4_eyebrow": "01 · FAKTEN",
    "welcome.s4_title": "Konfuzius sagt …",
    "welcome.p_menu_n": "Menü",
    "welcome.p_menu": "Alle Ihre Programme, Suche und Sprachbefehle. Auch die Windows-Taste öffnet es.",
    "welcome.p_launchers_n": "Schnellstart",
    "welcome.p_launchers": "Ein Klick startet diese Programme. Halten Sie die Maus über ein Symbol, um seinen Namen zu sehen.",
    "welcome.p_taskbar_n": "Offene Fenster",
    "welcome.p_taskbar": "Jedes geöffnete Programm erscheint hier. Ein Klick holt es nach vorn oder minimiert es.",
    "welcome.p_dictate_n": "Diktieren",
    "welcome.p_dictate": "Das Symbol zum Diktieren. Halten Sie F9 oder klicken Sie darauf, um zu sprechen; das Sprachmodell liegt auf diesem Laptop.",
    "welcome.p_bluetooth_n": "Bluetooth",
    "welcome.p_bluetooth": "Bluetooth ist aus, bis Sie es einschalten. Ein Klick auf das Symbol richtet es ein.",
    "welcome.p_volume_n": "Lautstärke",
    "welcome.p_volume": "Ein Klick regelt Lautsprecher und Mikrofon.",
    "welcome.p_cpu_n": "Prozessor-Lichtband",
    "welcome.p_cpu": "Ein rotes Licht wandert hin und her, umso schneller, je mehr der Prozessor arbeitet.",
    "welcome.p_disk_n": "Festplattenaktivität",
    "welcome.p_disk": "Ein grünes Lichtband, das bei jedem Lesen und Schreiben auf der Festplatte schneller wird.",
    "welcome.p_network_n": "Netzwerkaktivität",
    "welcome.p_network": "Ein blaues Lichtband, das anzeigt, wie viele Daten durch Ihre Netzwerkverbindung fließen.",
    "welcome.p_memory_n": "Speichertank",
    "welcome.p_memory": "Füllt sich wie eine Flüssigkeit, je mehr Arbeitsspeicher (RAM) belegt ist. Der Tooltip zeigt auch Swap und Festplattenplatz.",
    "welcome.p_wattage_n": "Stromverbrauch",
    "welcome.p_wattage": "Wie viele Watt der Laptop gerade braucht und wie lange der Akku noch reicht.",
    "welcome.p_battery_n": "Akku",
    "welcome.p_battery": "Ladestand. Ein Klick zeigt den Regler für die Bildschirmhelligkeit.",
    "welcome.p_status_n": "Sperr-Timer und Updates",
    "welcome.p_status": "Zählt bis zur automatischen Sperre und zum Herunterfahren und zeigt, ob die letzte Prüfung auf Sicherheitsupdates geklappt hat. Im Tooltip steht Ihre IP-Adresse.",
    "welcome.p_mic_n": "Mikrofon-Punkt",
    "welcome.p_mic": "Ein blinkender roter Punkt bedeutet, dass ein Programm das Mikrofon aufnimmt.",
    "welcome.p_clipboard_n": "Zwischenablage",
    "welcome.p_clipboard": "Zeigt, was Sie kopiert haben. Ein Klick zeigt, bearbeitet oder leert sie. Nach 15 Minuten leert sie sich selbst.",
    "welcome.p_vpn_n": "VPN",
    "welcome.p_vpn": "VPN mit einem Klick verbinden oder trennen, sobald Sie eine WireGuard-Datei importiert haben.",
    "welcome.p_connections_n": "Netzwerkverbindungen",
    "welcome.p_connections": "Listet auf, welche Programme mit dem Internet sprechen. Eine rote Markierung zeigt eine eingehende Verbindung.",
    "welcome.p_clock_n": "Uhr",
    "welcome.p_clock": "Ein Klick öffnet den Kalender.",
    "welcome.s3_hint": "Fahren Sie oben über ein Symbol.",
    "welcome.facts_more": "Nächster Fakt",
    "welcome.facts_open": "Alle {n} Fakten",
    "welcome.link_opens": "Öffnet: {name}",
    "welcome.hidden_title": "Willkommensbildschirm ausgeblendet",
    "welcome.hidden_body": "Um ihn wieder zu sehen, halten Sie die Windows-Taste gedrückt und sagen Sie „Willkommen“.",

    # Cyberbeest Backup (cyberbeest_backup_gui.py)
    "backup.title": "Cyberbeest Sicherung",
    "backup.tab_backup": "Sichern",
    "backup.tab_restore": "Wiederherstellen",
    "backup.idle": "Bereit",
    "backup.starting": "Startet …",
    "backup.finished": "Fertig",
    "backup.failed": "Fehlgeschlagen",
    "backup.cancel": "Abbrechen",
    "backup.cancelling": "Wird abgebrochen …",
    "backup.refresh": "Aktualisieren",
    "backup.disk_external": "extern",
    "backup.disk_internal": "intern",
    "backup.backup_intro": "Kopiert das gesamte System – Programme, Einstellungen und Dateien – verschlüsselt auf ein externes Laufwerk. Mit der Wiederherstellung ist dieser Computer wieder genau so, wie er jetzt ist. Das dauert eine Weile; lassen Sie den Computer am Netzteil.",
    "backup.dest_folder": "Sicherung auf diesem Laufwerk oder Ordner ablegen:",
    "backup.master_password": "Master-Passwort (das beim Start eingegebene):",
    "backup.master_note": "Die Sicherung wird wie die Festplatte mit Ihrem Master-Passwort verschlüsselt. Sie lässt sich nur mit dem Master-Passwort öffnen, das der Computer bei der Sicherung hatte – denken Sie daran, falls Sie es später ändern.",
    "backup.battery_warning": "Der Computer läuft im Akkubetrieb. Schließen Sie das Netzteil an, bevor Sie starten.",
    "backup.start_backup": "Sicherung starten",
    "backup.restore_intro": "Schreibt eine Sicherung auf eine Festplatte und ersetzt dabei alles, was darauf ist.",
    "backup.restore_installed_hint": "Tipp: Die Wiederherstellung funktioniert am besten, wenn der Computer vom Cyberbeest-Stick gestartet wurde. Das installierte System kann keine Sicherung seiner selbst zurückspielen.",
    "backup.source_folder": "Sicherungsordner:",
    "backup.target_disk": "Auf diese Festplatte wiederherstellen:",
    "backup.master_password_restore": "Master-Passwort, das der Computer bei der Sicherung hatte:",
    "backup.start_restore": "Wiederherstellen",
    "backup.confirm_title": "Festplatte löschen und wiederherstellen?",
    "backup.confirm_body": "Alles auf {disk} wird gelöscht. Das lässt sich nicht rückgängig machen. Geben Sie zum Fortfahren das Wort unten ein.",
    "backup.confirm_word": "LÖSCHEN",
    "backup.need_folder_and_password": "Wählen Sie einen Ordner und geben Sie Ihr Master-Passwort ein.",
    "backup.need_restore_fields": "Wählen Sie den Sicherungsordner und die Festplatte und geben Sie das Master-Passwort ein.",
    "backup.close_while_running": "Ein Vorgang läuft noch. Anhalten und das Fenster schließen?",
    "backup.done_backup": "Sicherung abgeschlossen. Die Sicherung liegt in:",
    "backup.done_restore": "Wiederherstellung abgeschlossen. Sie können den Computer jetzt von der wiederhergestellten Festplatte starten.",
    "backup.stage_check": "Prüfen",
    "backup.stage_container": "Verschlüsseln",
    "backup.stage_boot": "Startdateien",
    "backup.stage_image": "System",
    "backup.stage_verify": "Kontrolle",
    "backup.stage_finish": "Abschluss",
    "backup.stage_partition": "Partitionen",
    "backup.stage_encryption": "Festplattenschloss",
    "backup.stage_system": "System",
    "backup.err.generic": "Etwas ist schiefgegangen. Das Protokoll in ~/.local/share/cyberbeest/backup enthält Einzelheiten.",
    "backup.err.not_root": "Administratorrechte sind nötig.",
    "backup.err.no_passphrase": "Es wurde kein Passwort empfangen.",
    "backup.err.missing_tool": "Ein benötigtes Programm fehlt.",
    "backup.err.no_layout": "Die Festplattenaufteilung dieses Computers wird von der Sicherung nicht unterstützt.",
    "backup.err.same_disk": "Wählen Sie ein anderes Laufwerk als das, das gesichert wird.",
    "backup.err.fat_filesystem": "Dieses Laufwerk nutzt FAT und kann keine großen Dateien aufnehmen. Verwenden Sie ein Laufwerk mit ext4, NTFS oder exFAT.",
    "backup.err.no_space": "Auf dem Laufwerk ist nicht genug Platz frei.",
    "backup.err.no_snapshot_space": "Auf der Festplatte ist kein Platz für einen konsistenten Schnappschuss frei, daher ist keine Sicherung des laufenden Systems möglich.",
    "backup.err.bad_destination": "Der Ordner kann nicht verwendet werden.",
    "backup.err.bad_master_passphrase": "Das ist nicht das richtige Master-Passwort.",
    "backup.err.container_failed": "Die verschlüsselte Sicherungsdatei konnte nicht angelegt werden.",
    "backup.err.backup_failed": "Das Kopieren des Systems ist fehlgeschlagen.",
    "backup.err.snapshot_invalid": "Das System hat sich während des Kopierens zu stark verändert. Schließen Sie andere Programme und versuchen Sie es erneut.",
    "backup.err.verify_failed": "Die fertige Sicherung hat die Prüfung nicht bestanden.",
    "backup.err.bad_backup": "Dieser Ordner enthält keine verwendbare Cyberbeest-Sicherung.",
    "backup.err.bad_target": "Das ist keine verwendbare Festplatte.",
    "backup.err.target_busy": "Diese Festplatte ist in Benutzung. Wählen Sie eine andere.",
    "backup.err.backup_on_target": "Die Sicherung liegt auf der Festplatte, die Sie löschen wollten.",
    "backup.err.wrong_sector": "Die Festplatte hat eine andere Sektorgröße als die gesicherte.",
    "backup.err.vg_name_conflict": "Dieses System verwendet bereits dieselben Volume-Namen. Starten Sie zum Wiederherstellen den Computer vom Cyberbeest-Stick.",
    "backup.err.target_small": "Die Festplatte ist für diese Sicherung zu klein.",
    "backup.err.restore_failed": "Die Wiederherstellung ist fehlgeschlagen. Die Festplatte ist noch nicht nutzbar; starten Sie die Wiederherstellung erneut.",
    "backup.warn.extra_partitions": "Diese zusätzlichen Partitionen sind nicht in der Sicherung enthalten:",
    "backup.warn.disk_incomplete": "Die Festplatte wurde verändert, aber die Wiederherstellung wurde nicht abgeschlossen.",
    "backup.warn.grow_failed": "Die Systempartition konnte nicht auf die ganze Festplatte vergrößert werden.",
    "backup.warn.no_boot_entry": "Der Boot-Eintrag in der Firmware konnte nicht angelegt werden; wählen Sie die Festplatte im Startmenü.",
    "backup.tab_extract": 'Dateien suchen',
    "backup.extract_intro": 'Öffnet eine Sicherung, damit Sie einzelne Dateien oder Ordner herauskopieren können. Die Sicherung wird dazu zunächst in eine temporäre Datei entpackt; das dauert etwa so lange wie eine Wiederherstellung und braucht freien Platz für die Daten der Sicherung.',
    "backup.scratch_folder": 'Temporärer Platz zum Entpacken (ein Laufwerk mit genug freiem Speicher):',
    "backup.start_extract": 'Sicherung öffnen',
    "backup.stage_unpack": 'Entpacken',
    "backup.stage_mount": 'Öffnen',
    "backup.extract_ready": 'Die Sicherung ist geöffnet (nur lesbar). Kopieren Sie, was Sie brauchen, und klicken Sie dann auf Beenden.',
    "backup.open_files": 'In Dateien öffnen',
    "backup.finish": 'Beenden',
    "backup.need_extract_fields": 'Wählen Sie den Sicherungsordner und einen temporären Ordner und geben Sie das Master-Passwort ein.',
    "backup.err.view_busy": 'Es ist bereits eine Sicherung geöffnet. Beenden Sie diese zuerst.',
    "backup.err.extract_failed": 'Die Sicherung konnte nicht geöffnet werden.',
    'memdetails.title': 'Speicherdetails',
    'memdetails.col_process': 'Programm',
    'memdetails.col_count': 'Prozesse',
    'memdetails.col_memory': 'Speicher',
    'memdetails.col_share': 'Anteil am RAM',
    'memdetails.ram': 'RAM: {used:.1f} / {total:.1f} GiB belegt',
    'memdetails.swap': 'Auslagerung: {used:.1f} / {total:.1f} GiB belegt',
    'proc.dictate': 'Spracheingabe. Hört über das Mikrofon zu und tippt, was Sie sagen.',
    'proc.claude': 'Der Claude-Assistent, mit dem Sie im Terminal schreiben.',
    'proc.claude (background)': 'Ein Claude-Assistent, der im Hintergrund ohne Fenster arbeitet.',
    'proc.claude (standby)': 'Ein Claude-Assistent in Bereitschaft, damit die nächste Hintergrundaufgabe sofort startet. Er tut nichts, bis er gebraucht wird.',
    'proc.telegram-deskto': 'Der Telegram-Messenger.',
    'proc.Xorg': 'Zeichnet alles, was Sie auf dem Bildschirm sehen.',
    'proc.python3': 'Kleine Hilfsprogramme in Python, zum Beispiel für Symbole in der Leiste oder Einstellungsfenster.',
    'proc.fwupd': 'Sucht nach Updates für die eingebaute Gerätesoftware (Firmware) des Computers.',
    'proc.systemd-journal': 'Führt das Logbuch des Computers darüber, was wann geschehen ist.',
    'proc.fail2ban-server': 'Sperrt jeden, der wiederholt versucht, Passwörter über das Netzwerk zu erraten.',
    'proc.xfdesktop': 'Zeigt den Desktop-Hintergrund und die Symbole darauf.',
    'proc.systemd': 'Das erste Programm, das startet. Es startet und überwacht alle anderen Hintergrunddienste.',
    'proc.xfsettingsd': 'Wendet Ihre Einstellungen zu Aussehen und Verhalten an, etwa Design, Schriften und Tastatur.',
    'proc.blueman-tray': 'Zeigt das Bluetooth-Symbol in der Leiste.',
    'proc.exim4': 'Versendet System-E-Mails, zum Beispiel Warnungen des Computers an Sie.',
    'proc.gopanel': 'Die Leiste mit Menü-Knopf, Uhr und Symbolen.',
    'proc.xfce4-terminal': 'Das Terminalfenster, in dem Sie Befehle eintippen.',
    'proc.NetworkManager': 'Verbindet den Computer mit WLAN und Netzwerkkabeln.',
    'proc.dnscrypt-proxy': 'Schlägt Internetadressen verschlüsselt nach, damit andere nicht sehen, welche Seiten Sie besuchen.',
    'proc.Thunar': 'Das Programm Dateien zum Durchsuchen Ihrer Ordner.',
    'proc.udisksd': 'Bemerkt USB-Sticks und Festplatten und lässt Sie diese öffnen.',
    'proc.unattended-upgr': 'Installiert wichtige Sicherheitsupdates selbstständig.',
    'proc.lightdm': 'Der Anmeldebildschirm.',
    'proc.xfwm4': 'Verwaltet die Fenster: Verschieben, Größe ändern und Titelleisten.',
    'proc.cups-browsed': 'Findet Drucker in Ihrem Netzwerk.',
    'proc.blueman-applet': 'Kümmert sich um Bluetooth-Verbindungen und Kopplungsanfragen.',
    'proc.xfce4-screensav': 'Sperrt den Bildschirm, wenn Sie nicht da sind.',
    'proc.xfce4-session': 'Startet Ihren Desktop bei der Anmeldung und beendet ihn bei der Abmeldung.',
    'proc.polkitd': 'Entscheidet, welche Programme Dinge tun dürfen, die Administratorrechte brauchen.',
    'proc.wpa_supplicant': 'Kümmert sich um das WLAN-Passwort und die sichere WLAN-Verbindung.',
    'proc.mem-liquid': 'Das Speicher-Symbol in der Leiste, das sich wie ein Tank füllt.',
    'proc.colord': 'Sorgt für naturgetreue Bildschirmfarben.',
    'proc.kitt': 'Das wandernde Licht in der Leiste, das zeigt, wie ausgelastet der Prozessor ist.',
    'proc.systemd-udevd': 'Erkennt neu angeschlossene Geräte.',
    'proc.network-scanner': 'Das Symbol in der Leiste, das den Netzwerkverkehr zeigt.',
    'proc.upowerd': 'Überwacht den Akku und das Netzkabel.',
    'proc.io-scanner': 'Das Symbol in der Leiste, das die Festplattenaktivität zeigt.',
    'proc.systemd-logind': 'Verwaltet, wer angemeldet ist, und kümmert sich um Deckel und Ein-Aus-Taste.',
    'proc.dbus-daemon': 'Eine Vermittlungsstelle, über die Programme miteinander sprechen.',
    'proc.applet.py': 'Ein kleines Hilfsprogramm, das in der Leiste läuft.',
    'proc.wattage-panel': 'Das Symbol in der Leiste, das zeigt, wie viel Strom der Computer verbraucht.',
    'proc.ModemManager': 'Verwaltet Mobilfunk-Modems und SIM-Karten.',
    'proc.cupsd': 'Der Druckdienst. Er sammelt und versendet Ihre Druckaufträge.',
    'proc.accounts-daemon': 'Verwaltet die Liste der Benutzerkonten auf diesem Computer.',
    'proc.pulseaudio': 'Kümmert sich um den Ton: Lautsprecher, Kopfhörer und Mikrofon.',
    'proc.systemd-timesyn': 'Hält die Uhr über das Internet richtig.',
    'proc.xfce4-notifyd': 'Zeigt die kleinen Hinweisfenster an.',
    'proc.bash': 'Eine Eingabezeile, die auf Ihre Befehle wartet oder ein Skript ausführt.',
    'proc.ssh-agent': 'Merkt sich Ihre Schlüssel für Fernzugriffe, damit Sie das Passwort nur einmal eingeben.',
    'proc.nm-applet': 'Das WLAN- und Netzwerk-Symbol in der Leiste.',
    'proc.xdg-desktop-por': 'Lässt abgeschottete Programme Sie bitten, eine Datei zu wählen oder den Bildschirm zu teilen.',
    'proc.switcheroo-cont': 'Wählt den Grafikchip, wenn es zwei gibt.',
    'proc.sshd': 'Erlaubt anderen Computern, sich aus der Ferne hier anzumelden.',
    'proc.firejail': 'Ein Schutzkäfig um ein Programm, damit es nicht an Ihre übrigen Dateien kommt.',
    'proc.bluetoothd': 'Der Bluetooth-Dienst.',
    'proc.xfce4-power-man': 'Verwaltet Energiesparen, Helligkeit und was beim Zuklappen des Deckels geschieht.',
    'proc.obexd': 'Empfängt Dateien, die Ihnen per Bluetooth geschickt werden.',
    'proc.gpu-stall-watch': 'Beobachtet Grafik-Aussetzer und meldet sie.',
    'proc.gpg-agent': 'Bewacht Ihre Verschlüsselungsschlüssel und fragt bei Bedarf nach dem Passwort.',
    'proc.rtkit-daemon': 'Gibt dem Ton hohe Priorität, damit er nicht knackt.',
    'proc.cron': 'Führt geplante Aufgaben zu festgelegten Zeiten aus.',
    'proc.(sd-pam)': 'Teil Ihrer Anmeldung. Es räumt beim Abmelden auf.',
    'proc.agetty': 'Die Textanmeldung, die verwendet wird, wenn kein Desktop angezeigt wird.',
    'proc.gnome-keyring-d': 'Verwahrt Ihre gespeicherten Passwörter sicher.',
    'proc.sleep': 'Wartet eine Weile. Ein Hilfsskript nutzt es als Zeitgeber.',
    'proc.gvfs-udisks2-vo': 'Zeigt USB-Sticks und Festplatten im Programm Dateien an.',
    'proc.fusermount3': 'Lässt einen Ordner, etwa einen verschlüsselten oder im Netzwerk, wie einen normalen Ordner erscheinen.',
    'proc.acpid': 'Reagiert auf Ein-Aus-Taste und Deckel.',
    'proc.pactl': 'Ein winziges Werkzeug, das das Tonsystem nach seinem Zustand fragt.',
    'proc.gvfsd-trash': 'Lässt den Papierkorb im Programm Dateien funktionieren.',
    'proc.polkit-mate-aut': 'Fragt nach Ihrem Passwort, wenn ein Programm Administratorrechte braucht.',
    'proc.xfconfd': 'Speichert die Desktop-Einstellungen.',
    'proc.claude-sudo-hel': 'Fragt um Ihre Erlaubnis, bevor ein vorbereitetes Skript mit Administratorrechten läuft.',
    'proc.xterm': 'Ein einfaches Terminalfenster.',
    'proc.gcr-ssh-agent': 'Merkt sich Ihre Schlüssel für Fernzugriffe.',
    'proc.mic-recording-w': 'Zeigt den roten Punkt in der Leiste, solange das Mikrofon benutzt wird.',
    'proc.at-spi2-registr': 'Hilft Hilfsmitteln wie Screenreadern, mit Programmen zu sprechen.',
    'proc.xiccd': 'Lädt das Farbprofil Ihres Bildschirms.',
    'proc.xdg-document-po': 'Gibt abgeschotteten Programmen kontrollierten Zugriff auf die Dateien, die Sie wählen.',
    'proc.xclip': 'Kopiert oder fügt Text und Bilder für ein Skript über die Zwischenablage ein.',
    'proc.gvfsd': 'Lässt das Programm Dateien auf Netzwerkordner und andere Orte zugreifen.',
    'memdetails.unknown_proc': 'Für dieses Programm gibt es noch keine Beschreibung.',
    'proc.memory-details.py': 'Dieses Fenster mit den Speicherdetails.',
    'proc.cyberbeest-wallpaper-fade': 'Blendet den Desktop-Hintergrund sanft zwischen Bildern über.',
    'proc.cyberbeest-shutdown-chime-daemon.py': 'Wartet im Hintergrund darauf, den Ton beim Herunterfahren abzuspielen.',
}
