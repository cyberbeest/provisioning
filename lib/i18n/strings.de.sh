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
	[update.title]="Cyberbeest-Update"
	[update.no_repo_message]="Kein Provisioning-Checkout unter ~/provisioning oder ~/provisioning-bleeding gefunden.

Führe zuerst beestify.sh aus (siehe cyberbeest.com)."
	[update.confirm_message]="Die neuesten Cyberbeest-Provisioning-Updates holen (Branch BRANCH) und alles Neue anwenden?

Du wirst pro geändertem Schritt einmal nach deinem Passwort gefragt, wie bei der Einrichtung."
	[update.progress_message]="Suche nach Updates..."
	[update.pull_failed_message]="git pull fehlgeschlagen:

OUTPUT"
)
