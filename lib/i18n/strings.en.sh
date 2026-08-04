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
	[plymouth.luks_success]="Hard drive unlocked"
	[plymouth.shutdown_text]="Locking hard disk and shutting down"
	[plymouth.grub_background]="grub-background-en.png"
	[login.welcome_message]="Enter short password to unlock desktop"
	[web_install.confirm_title]="Install app?"
	[web_install.confirm_message]="A web page wants to install APPNAME on this computer.

Only continue if you clicked an install link on a page you trust."
	[web_install.install_label]="Install APPNAME"
	[web_install.cancel_label]="Cancel"
	[web_install.success_title]="Installed"
	[web_install.success_message]="APPNAME was installed successfully."
	[web_install.failure_title]="Installation failed"
	[web_install.failure_message]="Could not install APPNAME. See cyberbeest_pkg_helper.log for details."
	[web_install.unknown_app_title]="Unknown app"
	[web_install.unknown_app_message]="This install link does not match any app Cyberbeest knows about."
)
