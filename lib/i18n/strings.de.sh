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
)
