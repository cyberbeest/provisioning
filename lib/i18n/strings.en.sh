# English strings for provisioning shell scripts. Always sourced by
# lib/i18n.sh as the fallback layer, regardless of the active locale.
#
# Keys are dotted "script-or-area.thing" names, e.g. logout.title.
declare -gA STRINGS_EN=(
	[launch_software.dialog_title]="Cyberbeest Notice"
	[launch_software.message]="\"Software\" lets you browse and install any package from the Debian archive -- not just Cyberbeest-approved apps.

Installing something here is at your own risk. For a curated, pre-approved list instead, use the Cyberbeest Package Manager."
	[launch_software.continue]="Continue to \"Software\""
	[launch_software.cancel]="Cancel"
	[plymouth.luks_prompt]="Enter master password to decrypt hard drive"
	[plymouth.unlock_success]="Hard drive unlocked"
	[plymouth.shutdown_text]="Locking hard disk and shutting down"
	[plymouth.grub_background]="grub-background-en.png"
	[login.welcome_message]="Enter short password to unlock desktop"
)
