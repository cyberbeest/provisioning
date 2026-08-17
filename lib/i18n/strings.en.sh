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
	[update_genmon.min_ago]="N min ago"
	[update_genmon.in_min]="in N min"
	[update_genmon.right_now]="right now"
	[update_genmon.unknown]="unknown"
	[update_genmon.installing]="Installing security updates now..."
	[update_genmon.waiting_first_check]="Waiting for the first security check since boot..."
	[update_genmon.checking]="Checking for security updates now..."
	[update_genmon.reboot_needed]="A security update was installed and needs a restart to take effect."
	[update_genmon.reboot_triggered_by]="Triggered by: PKGS"
	[update_genmon.reboot_please]="Please reboot when you get a chance."
	[update_genmon.network_error]="Last security check failed: no network connection."
	[update_genmon.upgrade_error]="Last security update failed to install."
	[update_genmon.overdue]="Security check is overdue -- it should have run by now."
	[update_genmon.all_good]="All security updates are installed, your system is safe."
	[update_genmon.last_check_with_duration]="Last check: REL (COUNT updates, took DURATION)"
	[update_genmon.last_check_no_duration]="Last check: REL (COUNT updates)"
	[update_genmon.next_check]="Next check: REL"
	[update_genmon.skipped_metered]="Last check was skipped: on a metered connection (e.g. tethered mobile data)."
	[update_genmon.skipped_metered_retry]="It'll run automatically once you're back on an unmetered network."
	[update_genmon.apps_up_to_date]="Messenger apps: up to date (checked REL)"
	[update_genmon.apps_deferred_metered]="Messenger apps: update deferred (metered connection)"
	[update_genmon.apps_error]="Messenger apps: last update check failed"
)
