# German strings for provisioning shell scripts.
#
# Every non-English catalog names its array STRINGS_L10N (not e.g.
# STRINGS_DE) -- lib/i18n.sh only ever sources one such file per run, picked
# by the detected locale, so the array name itself doesn't need to encode
# the language.
declare -gA STRINGS_L10N=(
	[launch_software.dialog_title]="Cyberbeest-Hinweis"
	[launch_software.message]="„Software“ lässt dich jedes Paket aus dem Debian-Archiv durchsuchen und installieren -- nicht nur die von Cyberbeest freigegebenen Apps.

Die Installation hier erfolgt auf eigenes Risiko. Für eine kuratierte, freigegebene Liste nutze stattdessen den Cyberbeest Package Manager."
	[launch_software.continue]="Weiter zu „Software“"
	[launch_software.cancel]="Abbrechen"
	[plymouth.luks_prompt]="Master-Passwort zum Entschlüsseln der Festplatte eingeben"
	[plymouth.luks_success]="Festplatte entsperrt"
	[plymouth.shutdown_text]="Festplatte wird gesperrt und heruntergefahren"
	[plymouth.grub_background]="grub-background-de.png"
	[grub.menu_hint]="Eingabetaste zum Starten   ·   Pfeiltasten zum Auswählen"
	[grub.countdown]="Start in %d Sekunden"
	[login.welcome_message]="Kurzes Passwort eingeben, um den Desktop zu entsperren"
	[web_install.confirm_title]="App installieren?"
	[web_install.confirm_message]="Eine Webseite möchte APPNAME auf diesem Computer installieren.

Fahre nur fort, wenn du einen Installations-Link auf einer vertrauenswürdigen Seite angeklickt hast."
	[web_install.install_label]="APPNAME installieren"
	[web_install.cancel_label]="Abbrechen"
	[web_install.success_title]="Installiert"
	[web_install.success_message]="APPNAME wurde erfolgreich installiert."
	[web_install.failure_title]="Installation fehlgeschlagen"
	[web_install.failure_message]="APPNAME konnte nicht installiert werden. Details in cyberbeest_pkg_helper.log."
	[web_install.unknown_app_title]="Unbekannte App"
	[web_install.unknown_app_message]="Dieser Installations-Link passt zu keiner App, die Cyberbeest kennt."
	[update_genmon.min_ago]="vor N Min."
	[update_genmon.in_min]="in N Min."
	[update_genmon.right_now]="gerade eben"
	[update_genmon.unknown]="unbekannt"
	[update_genmon.installing]="Sicherheitsupdates werden jetzt installiert …"
	[update_genmon.waiting_first_check]="Warte auf die erste Sicherheitsprüfung seit dem Start …"
	[update_genmon.checking]="Suche gerade nach Sicherheitsupdates …"
	[update_genmon.reboot_needed]="Ein Sicherheitsupdate wurde installiert und erfordert einen Neustart, um wirksam zu werden."
	[update_genmon.reboot_triggered_by]="Ausgelöst durch: PKGS"
	[update_genmon.reboot_please]="Bitte starte den Computer neu, sobald es passt."
	[update_genmon.network_error]="Letzte Sicherheitsprüfung fehlgeschlagen: keine Netzwerkverbindung."
	[update_genmon.upgrade_error]="Das letzte Sicherheitsupdate konnte nicht installiert werden."
	[update_genmon.overdue]="Die Sicherheitsprüfung ist überfällig -- sie hätte längst laufen sollen."
	[update_genmon.all_good]="Alle Sicherheitsupdates sind installiert, dein System ist sicher."
	[update_genmon.last_check_with_duration]="Letzte Prüfung: REL (COUNT Updates, dauerte DURATION)"
	[update_genmon.last_check_no_duration]="Letzte Prüfung: REL (COUNT Updates)"
	[update_genmon.next_check]="Nächste Prüfung: REL"
	[update_genmon.skipped_metered]="Letzte Prüfung übersprungen: getaktete Verbindung (z. B. mobiles Datentethering)."
	[update_genmon.skipped_metered_retry]="Läuft automatisch, sobald wieder eine ungetaktete Verbindung besteht."
	[update_genmon.apps_up_to_date]="Messenger-Apps: aktuell (geprüft REL)"
	[update_genmon.apps_deferred_metered]="Messenger-Apps: Update aufgeschoben (getaktete Verbindung)"
	[update_genmon.apps_error]="Messenger-Apps: letzte Prüfung fehlgeschlagen"
	[shutdown_genmon.never]="Nie"
	[shutdown_genmon.no_auto_lock]="Keine automatische Sperre"
	[shutdown_genmon.locks_after]="Sperrt nach DURATION Inaktivität"
	[shutdown_genmon.auto_lock_off_warning]="WICHTIG: Automatische Sperre ist deaktiviert, daher ist die automatische Abschaltung deaktiviert"
	[shutdown_genmon.disabled_both]="Automatische Abschaltung im gesperrten Zustand ist deaktiviert (Netzbetrieb und Akku)"
	[shutdown_genmon.after_both]="Automatische Abschaltung nach DURATION im gesperrten Zustand (Netzbetrieb und Akku)"
	[shutdown_genmon.after_locked_header]="Automatische Abschaltung nach Sperrung:"
	[shutdown_genmon.ac_label]="Netzbetrieb: DURATION"
	[shutdown_genmon.battery_label]="Akku: DURATION"
	[shutdown_genmon.click_to_change]="Zum Ändern klicken"
	[shutdown_genmon.blocked_suffix]=" (derzeit BLOCKIERT)"
	[shutdown_genmon.inhibited_warning]="WICHTIG: Automatische Sperre wird von APPNAME blockiert -- Bildschirm wird NICHT gesperrt"
	[panel_status_genmon.lock_heading]="Sperre &amp; automatische Abschaltung"
	[panel_status_genmon.security_heading]="Sicherheitsupdates"
	[panel_status_genmon.ip_line]="IP-Adresse: ADDR"
	[panel_status_genmon.ip_unknown]="keine Netzwerkverbindung"
	[panel_status_genmon.ports_line]="Offene Ports: PORTS"
	[panel_status_genmon.ports_none]="keine"
	[update.title]="Cyberbeest-Update"
	[update.no_repo_message]="Kein Provisioning-Checkout unter ~/provisioning oder ~/provisioning-bleeding gefunden.

Führe zuerst beestify.sh aus (siehe cyberbeest.com)."
	[update.track_beta]="Beta"
	[update.track_stable]="Stable"
	[update.switch_confirm_message]="Diesen Computer vom Cyberbeest-CURRENT-Repository auf das OTHER-Repository umstellen?

Dabei wird der CURRENT-Checkout gelöscht und OTHER neu geklont. Cyberbeest-Update kann nicht wissen, welche Skripte im neuen Track noch nötig sind -- das musst du selbst prüfen und ausführen."
	[update.switch_exists_message]="Es existiert bereits ein OTHER-Checkout unter PATH.

Entferne ihn zuerst manuell, um die Tracks zu wechseln."
	[update.switch_progress_message]="Wechsle zum TRACK-Repository..."
	[update.switch_clone_failed_message]="git clone fehlgeschlagen:

OUTPUT"
	[update.switch_done_message]="Zum Cyberbeest-TRACK-Repository gewechselt.

COUNT Skript(e) waren identisch zum alten Checkout und sind bereits als erledigt markiert. Prüfe den Rest und führe aus, was nötig ist."
	[update.progress_message]="Suche nach Updates..."
	[update.check_failed_message]="Suche nach Updates fehlgeschlagen:

OUTPUT"
	[update.apply_message]="Update wird angewendet..."
	[update.apply_failed_message]="Anwenden des Updates fehlgeschlagen:

OUTPUT"
	[update.local_changes_message]="Der Update-Ordner dieses Computers enthält Änderungen, die nicht auf dem Server sind:

CHANGES
Ein normales Update würde sie verwerfen. Behalten und nur die neuen Updates übernehmen, oder verwerfen?"
	[update.local_commits_line]="COUNT Commit(s) noch nicht hochgeladen"
	[update.keep_changes]="Änderungen behalten"
	[update.discard_changes]="Änderungen verwerfen"
	[update.cancel]="Abbrechen"
	[update.keep_failed_message]="Das Update ließ sich nicht anwenden, ohne deine Änderungen anzutasten, daher wurde nichts verändert:

OUTPUT"
	[lockwarning.title]="Bildschirm sperrt in SECONDS Sekunden"
	[lockwarning.title_one]="Bildschirm sperrt in 1 Sekunde"
	[lockwarning.body]="Bewege die Maus oder drücke eine Taste, um entsperrt zu bleiben."
	[clipboard_genmon.label_text]="Text"
	[clipboard_genmon.label_image]="Bild"
	[clipboard_genmon.label_image_file]="Bild + Datei"
	[clipboard_genmon.label_files]="Dateipfad(e)"
	[clipboard_genmon.label_unknown]="unbekannter Inhalt"
	[clipboard_genmon.never]="Nie"
	[mic_recording.tooltip_heading]="Mikrofon wird verwendet von:"
	[connections_genmon.none]="Keine aktiven Netzwerkverbindungen"
	[connections_genmon.in_n]="%d eingehende Verbindungen:"
	[connections_genmon.in_1]="%d eingehende Verbindung:"
	[connections_genmon.out_n]="%d ausgehende Verbindungen:"
	[connections_genmon.out_1]="%d ausgehende Verbindung:"
	[connections_genmon.system_service]="Systemdienst"
	[connections_genmon.unknown]="unbekannt (zum Klären anklicken)"
	[clipboard_genmon.auto_clear_prefix]="Automatisch leeren:"
	[clipboard_genmon.empty_with_setting]="Zwischenablage ist leer — SETTING"
	[clipboard_genmon.status]="Zwischenablage: LABEL (AGE)COUNTDOWN"
	[clipboard_genmon.countdown]=" — wird geleert in DURATION"
	[vm_start.failed_title]="Virtuelle Maschine startet nicht"
	[vm_start.failed_body]="NAME konnte nicht gestartet werden."
	[vm_start.updating_title]="Virtuelle Maschine installiert Updates"
	[vm_start.updating_body]="NAME fährt herunter, sobald die Updates installiert sind."
	[vm_start.restoring_title]="Virtuelle Maschine wird wiederhergestellt"
	[vm_start.restoring_body]="NAME macht gleich dort weiter, wo du aufgehört hast."
	[vm_start.saving_title]="Virtuelle Maschine wird gespeichert"
	[vm_start.stopping_title]="Virtuelle Maschine wird heruntergefahren"
	[vm_start.stopping_body]="NAME: Fenster geschlossen, fahre sauber herunter…"
	[vm_start.killed_title]="Virtuelle Maschine gestoppt"
	[vm_start.killed_body]="NAME reagierte nicht und wurde hart gestoppt."

	[vpn.import_file_title]="WireGuard-Konfigurationsdatei auswählen (.conf)"
	[vpn.import_file_filter]="WireGuard-Konfigurationen"
	[vpn.import_name_title]="Dieses VPN-Profil benennen"
	[vpn.import_name_text]="Kurzer Name für dieses Profil (nur Buchstaben, Zahlen, - und _):"
	[vpn.import_invalid_name]="Ungültiger Name. Nur Buchstaben, Zahlen, - und _ verwenden (max. 15 Zeichen)."
	[vpn.import_name_exists]="Ein Profil namens \"NAME\" existiert bereits."
	[vpn.import_failed]="Import der Konfiguration fehlgeschlagen. Prüfe ~/claude oder führe vpn-import-helper.sh manuell aus, um den Fehler zu sehen."
	[vpn.import_notify_title]="VPN-Profil \"NAME\" importiert"
	[vpn.import_notify_body]="Klicke auf das Panel-Symbol, um dich zu verbinden."
	[vpn.connect_notify_title]="Verbunden"
	[vpn.connect_notify_body]="VPN-Profil \"NAME\" ist jetzt aktiv."
	[vpn.connect_failed_title]="Verbindung fehlgeschlagen"
	[vpn.connect_failed_body]="VPN-Profil \"NAME\" konnte nicht gestartet werden. Prüfe die Konfigurationsdatei."
	[vpn.disconnect_notify]="Getrennt"
	[vpn.remove_notify]="Profil \"NAME\" entfernt"
	[vpn.icon_removed_notify]="VPN-Symbol entfernt"
	[vpn.genmon_connected]="VPN verbunden: NAME"
	[vpn.genmon_dropped]="VPN unerwartet getrennt (war: NAME)"
	[vpn.genmon_none]="Kein VPN verbunden."
	[vpn.genmon_click_for_options]="Klicken für Optionen."
	[claude.warn_title]="Claude Code installieren? DATENSCHUTZ-WARNUNG"
	[claude.warn_message]="<span size=\"xx-large\" weight=\"bold\" foreground=\"#c00000\">⚠  DATENSCHUTZ-WARNUNG</span>

<span size=\"large\" weight=\"bold\">Claude Code ist NICHT privat. Es ist ein Cloud-Dienst.</span>

Alles, was du damit machst, geht über das Internet an die Server von Anthropic: deine Nachrichten, der Inhalt jeder Datei und jedes Ordners, die es liest, die Ausgabe jedes Befehls, den es ausführt, und alles auf dem Bildschirm, was es sich ansieht. Anthropic kann das speichern. Verschlüsselung, Firewall und die Offline-Voreinstellung von Cyberbeest <b>schützen nichts davon, was du Claude Code gibst</b>.

• Nie mit Passwörtern, Schlüsseln, Wallets, privaten Dokumenten oder Daten anderer Personen verwenden.
• Es kann Befehle auf diesem Computer ausführen. Du bestimmst, was es darf, aber eine falsche Freigabe kann Dateien löschen oder preisgeben.
• Du brauchst ein eigenes Claude-Konto (Bezahl-Tarif oder API-Guthaben). Cyberbeest ist nicht mit Anthropic verbunden.
• Download-Größe: etwa 1,2 GB (Claude Code, Hilfswerkzeuge, Sprachausgabe-Stimmen).

Die Installation betrifft nur dein eigenes Benutzerkonto, und der Menüeintrag „Claude Code entfernen“ löscht alles wieder.

<b>Nur fortfahren, wenn du akzeptierst, dass deine Arbeit diesen Computer verlässt.</b>"
	[claude.warn_install]="Verstanden - installieren"
	[claude.warn_cancel]="Abbrechen"
	[claude.installing]="Claude Code wird installiert (dauert einige Minuten)..."
	[claude.install_done_title]="Claude Code installiert"
	[claude.install_done_message]="Fertig. Öffne „Claude Code“ im Menü. Beim ersten Start wirst du gebeten, dich mit deinem Claude-Konto anzumelden.

Zur Erinnerung: Alles, was du dort eintippst, geht an Anthropic."
	[claude.install_failed_title]="Installation fehlgeschlagen"
	[claude.install_failed_message]="Etwas ist schiefgelaufen. Sonst wurde nichts an deinem System geändert. Einzelheiten: LOG"
	[claude.remove_title]="Claude Code entfernen"
	[claude.remove_message]="Claude Code, die Anmeldung, die Hilfswerkzeuge, Stimmen und Menüeinträge werden in jedem Fall entfernt.

<b>Entfernen, Daten behalten</b> (empfohlen)
Behält deine Einstellungen, deine gespeicherten Gespräche und den Ordner ~/claude mit deinen Projekten. Eine spätere Neuinstallation nutzt sie wieder.

<b>Alles entfernen</b>
Löscht zusätzlich deine Einstellungen, alle gespeicherten Gespräche und den ganzen Ordner ~/claude samt deiner eigenen Dateien darin.

Dein Claude-Konto selbst bleibt unberührt."
	[claude.remove_keep_button]="Entfernen, Daten behalten"
	[claude.remove_all_button]="Alles entfernen"
	[claude.remove_cancel]="Abbrechen"
	[claude.remove_confirm_title]="Wirklich?"
	[claude.remove_confirm_keep]="Claude Code wird jetzt entfernt. Deine Einstellungen, gespeicherten Gespräche und Projekte in ~/claude bleiben."
	[claude.remove_confirm_all]="<b>Das lässt sich nicht rückgängig machen.</b>

Claude Code, deine Einstellungen, alle gespeicherten Gespräche und der ganze Ordner ~/claude (samt deiner eigenen Dateien) werden endgültig gelöscht."
	[claude.remove_confirm_yes]="Ja, entfernen"
	[claude.remove_done_title]="Claude Code entfernt"
	[claude.remove_done_message]="Claude Code und alles, was dazugehörte, ist entfernt."
	[claude.remove_none_message]="Claude Code ist in diesem Benutzerkonto nicht installiert."
)
