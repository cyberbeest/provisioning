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
)
