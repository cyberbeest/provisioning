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
	[shutdown_genmon.never]="Never"
	[shutdown_genmon.no_auto_lock]="No auto-lock"
	[shutdown_genmon.locks_after]="Locks after DURATION idle"
	[shutdown_genmon.auto_lock_off_warning]="IMPORTANT: Auto-lock is off, so auto-shutdown is disabled"
	[shutdown_genmon.disabled_both]="Auto-shutdown while locked is disabled (AC and battery)"
	[shutdown_genmon.after_both]="Auto-shutdown after DURATION locked (AC and battery)"
	[shutdown_genmon.after_locked_header]="Auto-shutdown after being locked:"
	[shutdown_genmon.ac_label]="AC: DURATION"
	[shutdown_genmon.battery_label]="Battery: DURATION"
	[shutdown_genmon.click_to_change]="Click to change"
	[shutdown_genmon.blocked_suffix]=" (currently BLOCKED)"
	[shutdown_genmon.inhibited_warning]="IMPORTANT: Auto-lock is being blocked by APPNAME -- screen will NOT lock"
	[panel_status_genmon.lock_heading]="Lock &amp; auto-shutdown"
	[panel_status_genmon.security_heading]="Security updates"
	[panel_status_genmon.ip_line]="IP address: ADDR"
	[panel_status_genmon.ip_unknown]="no network connection"
	[panel_status_genmon.ports_line]="Listening ports: PORTS"
	[panel_status_genmon.ports_none]="none"
	[update.title]="Cyberbeest Update"
	[update.no_repo_message]="No provisioning checkout found at ~/provisioning or ~/provisioning-bleeding.

Run beestify.sh first (see cyberbeest.com)."
	[update.track_beta]="beta"
	[update.track_stable]="stable"
	[update.switch_confirm_message]="Switch this computer from the Cyberbeest CURRENT repository to the OTHER repository?

This deletes the CURRENT checkout and clones OTHER fresh. Cyberbeest Update can't tell which scripts the new track still needs -- that's up to you to review and run afterwards."
	[update.switch_exists_message]="An OTHER checkout already exists at PATH.

Remove it manually first if you want to switch tracks."
	[update.switch_progress_message]="Switching to the TRACK repository..."
	[update.switch_clone_failed_message]="git clone failed:

OUTPUT"
	[update.switch_done_message]="Switched to the Cyberbeest TRACK repository.

COUNT script(s) were identical to the old checkout and already marked done. Review the rest and run whatever you need."
	[update.progress_message]="Checking for updates..."
	[update.check_failed_message]="Checking for updates failed:

OUTPUT"
	[update.apply_message]="Applying update..."
	[update.apply_failed_message]="Applying the update failed:

OUTPUT"
	[update.local_changes_message]="This computer's update folder has changes that aren't on the server:

CHANGES
Updating normally would discard them. Keep them and only bring in the new updates, or discard them?"
	[update.local_commits_line]="COUNT commit(s) not yet uploaded"
	[update.keep_changes]="Keep my changes"
	[update.discard_changes]="Discard changes"
	[update.cancel]="Cancel"
	[update.keep_failed_message]="The update couldn't be applied without touching your changes, so nothing was changed:

OUTPUT"
	[lockwarning.title]="Screen locks in SECONDS seconds"
	[lockwarning.title_one]="Screen locks in 1 second"
	[lockwarning.body]="Move the mouse or press a key to stay unlocked."
	[clipboard_genmon.label_text]="text"
	[clipboard_genmon.label_image]="image"
	[clipboard_genmon.label_image_file]="image + file"
	[clipboard_genmon.label_files]="file path(s)"
	[clipboard_genmon.label_unknown]="unrecognized content"
	[clipboard_genmon.never]="Never"
	[clipboard_genmon.auto_clear_prefix]="Auto-clear:"
	[clipboard_genmon.empty_with_setting]="Clipboard is empty — SETTING"
	[clipboard_genmon.status]="Clipboard: LABEL (AGE)COUNTDOWN"
	[clipboard_genmon.countdown]=" — clears in DURATION"
	[vm_start.failed_title]="Virtual machine didn't start"
	[vm_start.failed_body]="NAME could not be started."
	[vm_start.updating_title]="Virtual machine is installing updates"
	[vm_start.updating_body]="NAME will shut down once the updates are installed."
	[vm_start.restoring_title]="Restoring virtual machine"
	[vm_start.restoring_body]="NAME continues where you left off in a moment."
	[vm_start.saving_title]="Saving virtual machine"
	[vm_start.stopping_title]="Shutting down virtual machine"
	[vm_start.stopping_body]="NAME: window closed, shutting down cleanly…"
	[vm_start.killed_title]="Virtual machine stopped"
	[vm_start.killed_body]="NAME didn't respond and was stopped forcibly."

	[vpn.import_file_title]="Select a WireGuard config file (.conf)"
	[vpn.import_file_filter]="WireGuard configs"
	[vpn.import_name_title]="Name this VPN profile"
	[vpn.import_name_text]="Short name for this profile (letters, numbers, - and _ only):"
	[vpn.import_invalid_name]="Invalid name. Use only letters, numbers, - and _ (max 15 characters)."
	[vpn.import_name_exists]="A profile named \"NAME\" already exists."
	[vpn.import_failed]="Failed to import that config. Check ~/claude or run vpn-import-helper.sh manually to see the error."
	[vpn.import_notify_title]="VPN profile \"NAME\" imported"
	[vpn.import_notify_body]="Click the panel icon to connect."
	[vpn.connect_notify_title]="Connected"
	[vpn.connect_notify_body]="VPN profile \"NAME\" is now active."
	[vpn.connect_failed_title]="Connection failed"
	[vpn.connect_failed_body]="Could not start VPN profile \"NAME\". Check the config file."
	[vpn.disconnect_notify]="Disconnected"
	[vpn.remove_notify]="Profile \"NAME\" removed"
	[vpn.genmon_connected]="VPN connected: NAME"
	[vpn.genmon_dropped]="VPN disconnected unexpectedly (was: NAME)"
	[vpn.genmon_none]="No VPN connected."
	[vpn.genmon_click_for_options]="Click for options."
)
