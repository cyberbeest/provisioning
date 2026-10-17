# English strings for provisioning's Python GUI scripts. Always loaded by
# lib/i18n.py as the fallback layer, regardless of the active locale.
#
# Keys are dotted "script-or-area.thing" names, e.g. logout.title.
STRINGS = {
    "logout.title": "Log Out",
    "logout.lock": "Lock",
    "logout.restart": "Restart",
    "logout.shutdown": "Shut Down",
    "logout.hibernate": "Hibernate",
    "logout.cancel": "Cancel",

    "hibernate.splash_text": "HIBERNATING",

    "power.window_title": "Cyberbeest Power Settings",
    "power.heading": "Locked screen behavior",
    "power.info": (
        "This machine locks after 5 minutes idle and, by default, fully shuts "
        "down after being continuously locked, for safety. Set a time to 0 for "
        "“Never” to disable auto-shutdown for that power source."
    ),
    "power.link_same_time": "Use the same time on AC and battery",
    "power.shutdown_after": "Shutdown after (minutes locked):",
    "power.on_ac": "On AC power (minutes locked):",
    "power.on_battery": "On battery (minutes locked):",
    "power.experimental": "Experimental",
    "power.notif_checkbox": "Play notifications while locked, on battery",
    "power.detail": (
        "When enabled, on battery the machine cycles suspend and wake during "
        "that hour instead of staying fully awake, so notification sounds can "
        "still come through periodically while using much less power. "
        "Messages may arrive late, up to the asleep time below. "
        "On AC power this has no effect — the machine just "
        "stays awake for the whole locked period."
    ),
    "power.awake_minutes": "Awake minutes per cycle:",
    "power.asleep_minutes": "Asleep minutes per cycle:",
    "power.saved": "Saved. Takes effect on the next lock cycle, no restart needed.",
    "power.never": "Never",

    "timer.never": "Never",
    "timer.lock_screen_after": "Lock screen after:",
    "timer.lock_now": "Lock now",
    "timer.restart_now": "Restart now",
    "timer.shutdown_now": "Shut down now",
    "timer.hibernate_now": "Hibernate now",
    "timer.auto_shutdown_while_locked": "Auto-shutdown while locked",
    "timer.use_same_time": "Use the same time for AC and battery",
    "timer.important": "IMPORTANT",
    "timer.no_auto_lock_note": "Auto-lock is off, so auto-shutdown is disabled",
    "timer.shutdown_after_both": "Shutdown after locked for:",
    "timer.on_ac": "On AC power:",
    "timer.on_battery": "On battery:",
    "timer.power_saving_while_locked": "Extended power options…",

    "settings.window_title": "Cyberbeest Settings",
    "settings.props_title": "Properties: {name}",
    "settings.props_info": "Changes apply right away.",
    "settings.tab_power": "Extended power options",
    "settings.apply": "Apply",
    "settings.ok": "OK",
    "settings.tab_panel": "Panel",
    "settings.tab_wallpaper": "Wallpaper",
    "wallpaper.info": "Choose Cyberbeest's picture, your own, or a set of photos that changes every hour.",
    "wallpaper.standard": "Cyberbeest standard",
    "wallpaper.previous": "Single picture (what you had before)",
    "wallpaper.nature": "Nature photos",
    "wallpaper.space": "Space photos",
    "wallpaper.architecture": "Architecture photos",
    "wallpaper.cars": "Car photos",
    "wallpaper.cities": "City photos",
    "wallpaper.coast": "Coast and sea photos",
    "wallpaper.art": "Paintings",
    "wallpaper.desktop_settings": "Desktop background settings…",
    "wallpaper.credits": "Photo credits",
    "settings.tab_butler": "Butler",
    "butler.info": "Butler understands commands and questions typed into the menu search, for example \"make the display brighter\" or \"is my disk safe\". It needs about 500 MB of memory while it is in use.",
    "butler.enabled": "Use Butler in the menu",
    "butler.note": "Changes apply the next time you open the menu.",
    "settings.tab_weather": "Weather",
    "weather.accuracy": "Outside Germany the reading may be inaccurate: it comes from the nearest German Weather Service station, which can be far away.",
    "weather.info": "Shows the current temperature in the header of the menu. Nothing is looked up until you choose a place and turn this on.",
    "weather.city": "City or postcode",
    "weather.search": "Search",
    "weather.searching": "Searching…",
    "weather.pick": "Choose your place from the list.",
    "weather.nothing": "No place found.",
    "weather.error": "The search failed. Are you online?",
    "weather.none": "No place chosen yet.",
    "weather.current": "Place: {place}",
    "weather.enabled": "Show the weather in the menu",
    "weather.note": "Opening the menu then sends your IP address and the place, rounded to about 1 km, to api.brightsky.dev (German Weather Service data). Searching for a place asks OpenStreetMap. A VPN covers both. Changes apply the next time you open the menu.",
    "panel.info": "Choose which panel is shown at the bottom of the screen. The change takes effect when you click Apply or OK, and is kept for the next login.",
    "panel.xfce": "XFCE panel (default)",
    "panel.gopanel": "Cyberbeest panel",
    "panel.note": "The panels swap within a few seconds.",
    "panel.bg_label": "Panel background:",
    "panel.bg_off": "Fixed color",
    "panel.bg_24h": "Slow color drift, a full cycle in 24 hours",
    "panel.bg_1h": "Slow color drift, a full cycle in 1 hour",
    "panel.bg_5m": "Slow color drift, a full cycle in 5 minutes",
    "panel.bg_1m": "Slow color drift, a full cycle in 1 minute",
    "panel.bg_10s": "Color drift, a full cycle in 10 seconds",
    "panel.bg_wild": "Wild mode: colors swing between light and very dark",
    "panel.bg_note": "Cyberbeest panel only. The colors drift through light pastels; 24 hours follows the time of day.",
    "panel.monitor_label": "Show the Cyberbeest panel on:",
    "panel.monitor_auto": "Automatic (primary monitor)",
    "panel.monitor_all": "All monitors (copies of the panel)",
    "panel.monitor_note": "Copies show everything except tray icons that are real windows; those stay on the main panel.",

    "lockpower.window_title": "Cyberbeest Extended Power Options",
    "lockpower.info": (
        "Once the screen has been locked this long, windows are minimized "
        "and the browser's CPU use is capped, to save power. Downloads and "
        "notification sounds keep working, just slower."
    ),
    "lockpower.curtain_enabled": "Cover screen instantly on lock (recommended)",
    "lockpower.minimize_after": "Minimize windows after (minutes):",
    "lockpower.limit_cpu": "Limit browser CPU to (%):",
    "lockpower.warn_enabled": "Warn before auto-lock",
    "lockpower.warn_seconds": "Warn this many seconds ahead:",
    "lockpower.never": "Never",
    "lockpower.off": "Off",
    "lockpower.no_mercy_enabled": "No mercy: force-lock even if an app requests to stay awake",
    "lockpower.no_mercy_info": (
        "Ignores video playback, presentations, and any other app's request "
        "to delay the lock -- the screen locks on schedule no matter what. "
        "May interrupt something you're watching."
    ),
    "lockpower.close": "Close",

    "pw.window_title": "Cyberbeest Passwords & Boot",
    "pw.master_title": "Master password",
    "pw.master_desc": "The password used to decrypt your hard drive at startup.",
    "pw.short_title": "Short password",
    "pw.short_desc": (
        "The password used to enter your desktop or unlock the screen. "
        "Both passwords are required to start the device."
    ),
    "pw.current_password": "Current password:",
    "pw.new_password": "New password:",
    "pw.confirm_password": "Confirm new password:",
    "pw.generate": "Generate",
    "pw.change_password": "Change Password",
    "pw.cancel": "Cancel",
    "pw.hide_password": "Hide password",
    "pw.show_password": "Show password",
    "pw.generated_passphrase": (
        "Generated a new passphrase below — write it down or memorize it "
        "before changing the password."
    ),
    "pw.recommended_format": (
        "Recommended format: {word_count} random words "
        "(minimum length: {min_length} characters)"
    ),
    "pw.fill_all_fields": "Please fill in all fields.",
    "pw.mismatch": "The new password and confirmation do not match.",
    "pw.too_short": "The new password should be at least {min_length} characters long.",
    "pw.waiting_auth": "Waiting for authentication...",
    "pw.progress_title": "Password change in progress",
    "pw.progress_message": "Changing password, please wait...",
    "pw.confirm_written_title": "DID YOU REALLY WRITE THIS DOWN OR MEMORIZE IT?",
    "pw.confirm_written_secondary": "My Cyberbeest {title} is: {password}",
    "pw.success": "The password was changed successfully.",
    "pw.auth_cancelled": "Authentication was cancelled, so the password was not changed.",
    "pw.wrong_current": "The current password you entered was not correct.",
    "pw.change_failed": "The password could not be changed.",
    "pw.details": "Details",
    "pw.unknown_error": "unknown error",
    "pw.mark_temp_checkbox": "This is a temporary password — remind me to change it later",
    "pw.mark_temp_failed": "The password was changed, but could not be marked as temporary:",
    "pw.pkexec_error": "Could not start pkexec:",
    "pw.pty_error": "Could not open a pty:",
    "pw.change_failed_wrong_current": (
        "The password could not be changed. This usually means the current "
        "password was incorrect."
    ),
    "pw.boot_screen_tab": "Boot Screen",
    "pw.boot_name_desc": (
        "Enter a code word to show at the master password prompt so you can "
        "tell your Cyberbeest apart from the others."
    ),
    "pw.boot_name_label": "Code word:",
    "pw.save": "Save",
    "pw.boot_name_waiting": (
        "Waiting for authentication, then rebuilding the boot image "
        "(usually takes about {seconds} seconds)..."
    ),
    "pw.boot_name_set": "The boot screen now shows this machine's name.",
    "pw.boot_name_cleared": "The boot screen name was cleared.",
    "pw.boot_name_auth_cancelled": (
        "Authentication was cancelled, so the boot screen name was not changed."
    ),
    "pw.boot_name_failed": "The boot screen name could not be changed.",
    "pw.boot_bright_mode_label": "Bright screen at unlock",
    "pw.boot_bright_mode_desc": (
        "A poor man's flashlight: makes the unlock screen bright instead of "
        "black, useful for typing in the dark."
    ),
    "pw.boot_bright_mode_on": "The boot screen will now be bright at unlock.",
    "pw.boot_bright_mode_off": "The boot screen is back to its normal dark background.",
    "pw.boot_bright_mode_auth_cancelled": (
        "Authentication was cancelled, so the boot screen brightness was not changed."
    ),
    "pw.boot_bright_mode_failed": "The boot screen brightness could not be changed.",

    "pw.sound_tab": "Sound",
    "pw.sound_startup_title": "Startup chime",
    "pw.sound_startup_desc": "Plays right after the audio hardware wakes up, before the unlock screen.",
    "pw.sound_shutdown_title": "Shutdown chime",
    "pw.sound_shutdown_desc": "Plays when the machine actually powers off (not on restart).",
    "pw.sound_enabled": "Play this chime",
    "pw.sound_standard": "Cyberbeest standard chime",
    "pw.sound_choose_file": "Choose Sound File…",
    "pw.sound_play": "Play",
    "pw.sound_file_filter": "Sound files (wav, mp3, ogg)",
    "pw.sound_converting": "Converting and installing sound…",
    "pw.sound_install_failed": "The sound could not be installed.",
    "pw.sound_installed": "Sound installed.",
    "pw.sound_select_failed": "The sound could not be changed.",
    "pw.sound_selected": "Sound changed.",
    "pw.sound_enabled_on": "This chime will now play.",
    "pw.sound_enabled_off": "This chime is now muted.",
    "pw.sound_toggle_failed": "Could not change whether this chime plays.",
    "pw.sound_play_failed": "Could not play the sound.",
    "pw.sound_ffmpeg_missing": "ffmpeg is not installed, so the sound file could not be converted.",

    "nag.title": "Still using the password set up for you",
    "nag.still_secure_default": (
        "still the randomly-generated password from setup. That's secure on "
        "its own -- but only as long as the paper it's written on is stored "
        "somewhere separate from this machine."
    ),
    "nag.still_temp_default": "still the temporary default. Please change it.",
    "nag.remind_later": "Remind me later",
    "nag.change_now": "Change {title} now",
    "nag.keep": "Keep {title}",
    "nag.stop_nagging": "Stop nagging me",
    "nag.stop_notify_title": "Cyberbeest Passwords & Boot",
    "nag.stop_notify_body": (
        "You can still change your passwords, boot screen name, and startup "
        "sounds anytime from Settings → Cyberbeest Passwords & Boot."
    ),

    "panelcolor.window_title": "Cyberbeest Panel Color",
    "panelcolor.heading": "Panel color",
    "panelcolor.info": (
        "Sets the panel background and keeps the KITT scanner and memory "
        "tank widgets' margin color matching it."
    ),
    "panelcolor.warning": (
        "Note: those widgets may take up to a minute to catch up, for "
        "technical reasons."
    ),
    "panelcolor.custom": "Custom:",
    "panelcolor.applied": "Applied.",
    "panelcolor.preset_theme_default": "Theme default",
    "panelcolor.preset_slate_blue": "Slate blue",
    "panelcolor.preset_forest_green": "Forest green",
    "panelcolor.preset_warm_amber": "Warm amber",
    "panelcolor.preset_charcoal": "Charcoal",
    "update_genmon.log_title": "Security Update Log",
    "update_genmon.log_missing": "No update log found yet -- the check hasn't run.",
    "update_genmon.log_last_run": "Log of the last update run:",
    "update_genmon.log_live": "Updates are running -- live output:",
    "update_genmon.log_starting": "Starting the update run...",
    "update_genmon.close": "Close",
    "update_genmon.reboot_now": "Restart now",
    "update_genmon.run_now": "Run updates now",
    "update_genmon.run_now_already_running": "An update check is already running.",
    "update_genmon.run_now_failed": "Couldn't start the update check.",
    "update_genmon.settings": "Settings...",
    "update_genmon.settings_title": "Security Update Settings",
    "update_genmon.settings_save_failed": "Couldn't save the setting.",
    "update_genmon.delay_prompt": "Wait after startup before checking for updates:",
    "update_genmon.delay_hint": "Updates are never installed in the first minutes after you switch the computer on. The next check afterwards picks them up.",
    "update_genmon.save": "Save",
    "update_genmon.cancel": "Cancel",
    "update_genmon.interrupted": (
        "The last update check was interrupted (likely a shutdown or reboot "
        "mid-run) -- it'll retry automatically on the usual schedule."
    ),

    "run_gui.window_title": "Cyberbeest Provisioning Runner",
    "run_gui.confirm_remove_openssh": (
        "This permanently removes the SSH server and wipes every user's "
        "authorized_keys, cutting off remote SSH access to this machine.\n\n"
        "Continue?"
    ),
    "run_gui.state_pending": "pending",
    "run_gui.state_running": "running...",
    "run_gui.state_done": "done",
    "run_gui.state_failed": "failed",
    "run_gui.state_skipped": "skipped",
    "run_gui.profile_dialog_title": "Provisioning profile",
    "run_gui.profile_save": "_Save",
    "run_gui.profile_start_one_script": "Start 1 script",
    "run_gui.profile_start_n_scripts": "Start {count} scripts",
    "run_gui.profile_country_label": "Country:",
    "run_gui.profile_ui_language_label": "UI language:",
    "run_gui.profile_lang_english": "English",
    "run_gui.profile_lang_german": "Deutsch (German)",
    "run_gui.profile_keyboard_label": "Keyboard layout:",
    "run_gui.profile_menu_key_remap": (
        "Remap Menu key to </>/| (canonical Cyberbeest hardware only, German keyboard)"
    ),
    "run_gui.profile_timezone_label": "Timezone:",
    "run_gui.profile_touchpad_label": "Touchpad:",
    "run_gui.profile_touchpad_checkbox": (
        "Apply Cyberbeest touchpad tuning (tap-to-click everywhere, "
        "sensitivity/scrolling dialed in on reference hardware)"
    ),
    "run_gui.profile_sounds_label": "Sounds:",
    "run_gui.profile_sounds_checkbox": "Play the Cyberbeest startup and shutdown sounds, and set the volume to maximum",
    "run_gui.profile_plymouth_pointer_label": "Boot screen:",
    "run_gui.profile_plymouth_pointer_checkbox": "Show a mouse pointer on the boot screen and the disk password prompt",
    "run_gui.profile_dictation_model_label": "Dictation:",
    "run_gui.profile_dictation_model_checkbox": "Download the speech model for voice dictation (140–640 MB)",
    "run_gui.profile_vm_image_label": "VM image:",
    "run_gui.profile_vm_image_checkbox": "Download the Cyberbeest VM disk image (KVM)",
    "run_gui.profile_vm_update_label": "VM update:",
    "run_gui.profile_vm_update_checkbox": (
        "Update the Cyberbeest VM to the new version "
        "(the old VM is kept as a backup in Virtual Machine Manager)"
    ),
    "run_gui.profile_vm_update_space": (
        "Free disk space: {free}. Current VM: {current}. The update needs {needed}."
    ),
    "run_gui.profile_vm_update_previous_backup": (
        "The previous backup ({size}) will be deleted."
    ),
    "run_gui.profile_vm_update_no_space": (
        "Not enough free disk space for the update."
    ),
    "run_gui.profile_vm_update_tooltip": (
        "A newer version of the Cyberbeest VM is available. Updating downloads it "
        "(about {download}) and sets it up as a fresh VM: you start over with an empty "
        "VM and log in to your apps again.\n\n"
        "Your current VM is kept as a backup and stays available in Virtual Machine Manager, "
        "so nothing in it is lost. Only one backup is kept. The VM must be shut down "
        "during the update. Files in the VM-Shared folder are not affected."
    ),
    "run_gui.button_run_changed": "Run changed scripts",
    "run_gui.button_run_changed_count": "Run changed scripts ({count})",
    "run_gui.button_run_all": "Run all",
    "run_gui.button_run_selected": "Run selected",
    "run_gui.button_profile": "Profile...",
    "run_gui.button_select_all": "Select all",
    "run_gui.filter_placeholder": "Filter scripts…",
    "run_gui.button_stop": "Stop after current script",
    "run_gui.button_abort_download": "Abort download",
    "run_gui.button_view_source": "View source",
    "run_gui.view_source_title": "Source: {script}",
    "run_gui.status_abort_download_none": "No active download found to abort.",
    "run_gui.status_abort_download_killed": "Download aborted -- the current script should fail and exit shortly.",
    "run_gui.more_actions_tooltip": "More actions",
    "run_gui.menu_disable_autostart": "Disable auto-provisioning on login",
    "run_gui.menu_select_vm_scripts": "Select scripts for VM install",
    "run_gui.menu_switch_to_update": "Update...",
    "run_gui.timing_summary": "{elapsed} | {remaining} | {total}",
    "run_gui.status_idle": "Idle. Double-click a script below to run just that one.",
    "run_gui.status_idle_changed": "{count} changed scripts. Double-click a script below to run just that one.",
    "run_gui.todo_frame_title": "Things to do after the provisioning completed",
    "run_gui.log_hasnt_run_this_session": (
        "-- {script} hasn't run in this session; showing its log from a previous run --\n\n"
    ),
    "run_gui.log_hasnt_run_yet": "{script} hasn't been run yet. Double-click it to run.\n",
    "run_gui.status_running_script": "Running: {script}",
    "run_gui.status_running_script_elapsed": "Running: {script} ({elapsed})",
    "run_gui.status_nothing_to_run": "Nothing to run -- everything is already up to date.",
    "run_gui.status_nothing_selected": (
        "Nothing selected -- click (or ctrl/shift+click) one or more scripts below first."
    ),
    "run_gui.status_vm_scripts_selected": (
        "{count} scripts selected for VM install -- review below, then click \"Run selected\"."
    ),
    "run_gui.status_starting": "{label}: starting (enter sudo password if prompted)...",
    "run_gui.menu_run_script": "Run {script}",
    "run_gui.menu_run_scripts": "Run {count} selected scripts",
    "run_gui.menu_mark_dones": "Mark {count} selected scripts as done",
    "run_gui.menu_mark_done": "Mark {script} as done",
    "run_gui.status_marked_done": "Marked {count} script(s) as done",
    "run_gui.label_run_single": "Run {script}",
    "run_gui.dismiss_button": "Dismiss",
    "run_gui.action_open_desktop_settings": "Open Desktop Settings",
    "run_gui.action_open_password_settings": "Open Passwords & Boot",
    "run_gui.reboot_confirm_title": "Reboot now?",
    "run_gui.reboot_confirm_secondary": "This will restart the machine immediately.",
    "run_gui.confirm_run_title": "Run {script}?",
    "run_gui.log_opening_terminal": (
        "=== opening {script} in a terminal window (needs an interactive TTY) -- "
        "complete it there ===\n"
    ),
    "run_gui.log_stop_requested": "=== stop requested: skipping {count} remaining script(s) ===\n",
    "run_gui.log_skipped_declined": "=== {script} skipped (declined earlier; run it explicitly to be asked again) ===\n",
    "run_gui.log_skipped": "=== {script} skipped (not confirmed) ===\n",
    "run_gui.log_running_marker": "=== running {script} ===\n",
    "run_gui.log_done_marker": "=== {script} done ({duration}) ===\n",
    "run_gui.log_failed_marker": "=== {script} FAILED ({duration}, exit {status}) ===\n",
    "run_gui.log_failed_password": (
        "That looks like a wrong sudo password rather than a problem with "
        "{script} itself. Just run it again and re-enter the password.\n"
    ),
    "run_gui.log_stopping_dependency": "Stopping here since later scripts may depend on this one.\n",
    "run_gui.log_apt_retry": (
        "A package server had a temporary problem. Trying {script} again in "
        "{seconds} seconds (retry {attempt} of {total}).\n"
    ),
    "run_gui.status_stopped": "Stopped after current script.",
    "run_gui.status_failed": "Failed: {script} -- see log above.",
    "run_gui.status_finished": "Finished successfully. You can close this window.",
    "run_gui.todo_reboot_text": "Reboot to fully apply everything from this run.",
    "run_gui.todo_reboot_action": "Reboot Now",
    "run_gui.disable_autostart_confirm_title": "Disable auto-provisioning on login?",
    "run_gui.disable_autostart_message": (
        "This machine will no longer offer to run provisioning automatically at login."
    ),
    "run_gui.disable_autostart_pending_note": (
        "\n\n{count} script(s) haven't completed yet:\n{list}\n\n"
        "You can still run this tool by hand any time (beestify.sh)."
    ),
    "run_gui.status_disable_autostart_failed": "Could not remove {path}: {error}",
    "run_gui.status_autostart_disabled": (
        "Auto-provisioning on login disabled. Run beestify.sh by hand any time to pick up where you left off."
    ),
    "run_gui.status_stop_requested": "Stop requested -- finishing current script, then stopping...",

    "askpass.title": "Cyberbeest provisioning",
    "askpass.heading": "Enter your short password to run provisioning scripts as root:",
    "askpass.field_label": "Short password:",

    "update.title": "Cyberbeest Update",
    "update.confirm_message": (
        "This computer was built using the Cyberbeest <b>{track}</b> repository.\n\n"
        "Pull the latest updates from that repository?"
    ),
    "update.last_pull_message": "Last updated: {when} ({relative})",
    "update.last_pull_never": "Never updated before.",
    "update.version_label": "Version: {version}",

    "relative.just_now": "just now",
    "relative.minute_ago": "{n} minute ago",
    "relative.minutes_ago": "{n} minutes ago",
    "relative.hour_ago": "{n} hour ago",
    "relative.hours_ago": "{n} hours ago",
    "relative.day_ago": "{n} day ago",
    "relative.days_ago": "{n} days ago",
    "relative.month_ago": "{n} month ago",
    "relative.months_ago": "{n} months ago",
    "relative.year_ago": "{n} year ago",
    "relative.years_ago": "{n} years ago",
    "update.button_no": "Cancel",
    "update.button_yes": "Download Updates",
    "update.switch_button": "Switch track",
    "update.switch_menu_item": "Switch to {track} instead",
    "update.files_heading": "Changed files",
    "update.no_changes_message": "No changes since your last update.",
    "update.status_added": "Added",
    "update.status_modified": "Modified",
    "update.status_deleted": "Deleted",
    "update.status_renamed": "Renamed",
    "update.status_copied": "Copied",
    "update.status_other": "{code}",
    "update.column_file": "File",
    "update.column_comment": "Comment",
    "update.column_date": "Date",
    "update.diff_row_button": "Show file differences",
    "update.recheck_button_tooltip": "Check GitHub again",
    "update.recheck_failed_tooltip": "Couldn't reach GitHub -- try again in a moment.",
    "update.diff_dialog_title": "Differences: {path} ({date})",
    "update.diff_column_before": "Before",
    "update.diff_column_after": "After",
    "update.close_button": "Close",

    "clipboard.label_text": "Text",
    "clipboard.label_image": "Image",
    "clipboard.label_image_file": "Image + file",
    "clipboard.label_files": "File path(s)",
    "clipboard.label_unknown": "Unrecognized content",
    "clipboard.empty": "Clipboard is empty",
    "clipboard.clears_in": " — clears in {duration}",
    "clipboard.view_edit": "View / Edit…",
    "clipboard.show_image": "Show image",
    "clipboard.open_file": "Open file",
    "clipboard.show_in_folder": "Show in folder",
    "clipboard.show_in_folders": "Show in folders ({count} windows)",
    "clipboard.view": "View…",
    "clipboard.convert_png": "Convert to PNG",
    "clipboard.convert_jpeg": "Convert to JPEG",
    "clipboard.clear_clipboard": "Clear clipboard",
    "clipboard.auto_clear_settings": "Auto-clear settings…",
    "clipboard.window_title": "Clipboard",
    "clipboard.contains_image": "Clipboard contains an image",
    "clipboard.contains_files": "Clipboard contains file path(s):",
    "clipboard.contains_text": "Clipboard contains text (editable):",
    "clipboard.formatting_warning": "This entry also has formatting (e.g. HTML) that isn't shown here and will be lost if you edit or save.",
    "clipboard.contains_unknown": "Clipboard contains unrecognized content",
    "clipboard.close": "Close",
    "clipboard.save_changes": "Save changes",
    "clipboard.autoclear_title": "Clipboard Auto-Clear",
    "clipboard.autoclear_prompt": "Automatically clear the clipboard after:",
    "clipboard.never": "Never",

    "report.window_title": "Send Failure Report",
    "report.intro": (
        "{script} failed. You can send this report to the Cyberbeest team so "
        "we can fix it. This is exactly what will be sent -- edit or delete "
        "anything you like first."
    ),
    "report.privacy_note": (
        "Personal details like your name, network names and addresses have "
        "been replaced. The report contains no machine ID, and the server "
        "does not store your IP address."
    ),
    "report.no_log": "(no log file found)",
    "report.send": "Send",
    "report.cancel": "Cancel",
    "report.close": "Close",
    "report.sending": "Sending...",
    "report.sent": "Sent, thank you! Report ID: {reply}",
    "report.failed": "Could not send the report: {error}",
    "report.empty": "The report is empty -- nothing to send.",
    "report.too_large": "The report is too large (max 64 KB). Please shorten it.",
    "run_gui.todo_report_text": "{script} failed. Sending a report helps us fix it.",
    "run_gui.todo_report_action": "Send Report...",

    "vpn.window_title": "Cyberbeest VPN",
    "vpn.status_heading": "VPN Status",
    "vpn.disconnect": "Disconnect",
    "vpn.status_connected": "Connected: {name}",
    "vpn.status_not_connected_no_profiles": "Not connected. No profiles imported yet.",
    "vpn.status_not_connected": "Not connected.",
    "vpn.kill_switch_label": "Automatic kill switch:",
    "vpn.kill_switch_body": (
        "Any VPN config profile you import here gets a kill switch added "
        "automatically if it doesn't already have one — if the tunnel ever "
        "drops unexpectedly, your traffic is blocked instead of silently "
        "falling back to your raw connection."
    ),
    "vpn.providers_heading": "Known-supported VPNs (as of {date})",
    "vpn.open_button": "Open {name}",
    "vpn.install_button": "Install...",
    "vpn.signup_button": "Sign Up",
    "vpn.other_heading": "Any other VPN",
    "vpn.other_note": (
        "Any provider that hands out a WireGuard .conf file works, even "
        "if it's not listed above. Import it here — Cyberbeest adds a "
        "kill switch automatically if the config doesn't already have one."
    ),
    "vpn.import_button": "Import VPN Profile...",

    "vpn.mullvad_note": (
        "Account-number login, no email needed. Install via Cyberbeest "
        "Package Manager — opt-in because it runs its own background "
        "service once installed."
    ),
    "vpn.mullvad_badge": "No-log, audited",
    "vpn.mullvad_detail": (
        "Mullvad (Sweden) publishes a no-logs policy and has had "
        "it independently verified by outside auditors (Cure53, Assured AB). "
        "Signup needs no email or personal info at all — just a generated "
        "account number — so there's less to log even in principle."
    ),

    "vpn.protonvpn_note": (
        "Install via Cyberbeest Package Manager — same opt-in reasoning "
        "as Mullvad. Officially targets GNOME; still works on this "
        "Xfce machine."
    ),
    "vpn.protonvpn_badge": "No-log, audited",
    "vpn.protonvpn_detail": (
        "Proton VPN (Switzerland) publishes a no-logs policy, "
        "independently audited by SEC Consult in 2022. Same parent company "
        "as Proton Mail."
    ),

    "vpn.ivpn_note": "Sign up, download a WireGuard config, then Import it below.",
    "vpn.ivpn_badge": "No-log, audited",
    "vpn.ivpn_detail": (
        "IVPN (Gibraltar) publishes a no-logs policy, publishes "
        "its own third-party audit results, and maintains a warrant canary "
        "(a regularly-updated statement confirming it hasn't received a "
        "secret legal order — if it stops updating, that's the signal)."
    ),

    "vpn.airvpn_note": "Sign up, generate a WireGuard config, then Import it below.",
    "vpn.airvpn_badge": "No-log, unaudited",
    "vpn.airvpn_detail": (
        "AirVPN (Italy) claims a no-logs policy and has a solid "
        "reputation in the privacy community, but — unlike the three "
        "above — hasn't published an independent third-party audit "
        "confirming it. Italy is also an EU jurisdiction, considered a "
        "somewhat weaker legal shield than Sweden/Switzerland/Gibraltar "
        "by some privacy advocates, though this matters less if there's "
        "genuinely nothing logged to hand over."
    ),

    "vpn.menu_empty": "No VPN profiles imported yet",
    "vpn.menu_connected": "✓ {name} (connected)",
    "vpn.menu_connect": "Connect: {name}",
    "vpn.menu_import": "Import New Profile...",
    "vpn.menu_remove": "Remove Profile",
    "vpn.menu_hide_icon": "Remove Icon",
    "vpn.menu_hide_icon_connected": "Disconnect and Remove Icon",
    "vpn.show_icon_button": "Show VPN Icon",
    "vpn.status_icon_hidden": "VPN icon hidden ({count} profile(s) saved, not connected).",

    "sharedfolders.window_title": "Whitelisted Folders",
    "sharedfolders.intro": "Select the folders that are visible to protected apps.",
    "sharedfolders.col_folder": "Folder",
    "sharedfolders.col_contents": "Contents",
    "sharedfolders.counting": "Counting\u2026",
    "sharedfolders.count": "{folders}, {files}",
    "sharedfolders.choose": "Choose a folder to share with your apps",
    "sharedfolders.share": "Share",
    "sharedfolders.cancel": "Cancel",
    "sharedfolders.err_chars": "That folder name contains characters that can't be shared safely.",
    "sharedfolders.err_not_dir": "That is not a folder.",
    "sharedfolders.err_home": "Your whole home folder can't be shared. Pick a folder inside it instead.",
    "sharedfolders.err_hidden": "Hidden folders hold settings and keys, so they can't be shared.",
    "sharedfolders.err_location": "Only folders in your home folder or on removable drives can be shared.",
    "sharedfolders.err_firejail": "The sandbox doesn't accept that folder, so it was not added.",
    "sharedfolders.add_tip": "Share another folder with protected apps",
    "sharedfolders.remove_tip": "Stop sharing the selected folder",
    "sharedfolders.added": "Folder shared.",
    "sharedfolders.removed": "Folder removed.",
    "sharedfolders.restart_note": "Restart running apps to apply changes.",
    "sharedfolders.restart_btn": "Restart apps…",
    "sharedfolders.restart_q": "Restart these apps now?",
    "sharedfolders.restart_warn": "Unsaved work in them may be lost.",
    "sharedfolders.restart_do": "Restart",
    "sharedfolders.restarted": "Apps restarted.",
    "sharedfolders.folder_one": "{n} folder",
    "sharedfolders.folder_many": "{n} folders",
    "sharedfolders.file_one": "{n} file",
    "sharedfolders.file_many": "{n} files",
    "sharedfolders.missing": "Not found",
    "sharedfolders.none_running": "No protected apps are running.",
    "sharedfolders.step_closing": "Closing {app}…",
    "sharedfolders.step_starting": "Starting {app} again…",
    "sharedfolders.step_done": "Done: {n} app(s) restarted.",
    "sharedfolders.step_none": "Nothing could be restarted.",

    "connections.window_title": "Network connections by app",
    "connections.col_app": "App / remote address",
    "connections.col_port": "Port / count",
    "connections.col_direction": "Direction",
    "connections.col_host": "Host name (reverse DNS)",
    "connections.n_incoming": "{n} incoming",
    "connections.dir_incoming": "⬇ incoming",
    "connections.dir_outgoing": "outgoing",
    "connections.system_service": "system service",
    "connections.sandboxed": "sandboxed",
    "connections.unknown": "unknown",
    "connections.status": "{total} connections ({incoming} incoming), {apps} apps. Refreshes every {secs}s. Host names are reverse-DNS hints only.",

    "welcome.title": "Welcome to Cyberbeest",
    "welcome.heading": "Welcome to Cyberbeest",
    "welcome.sub": "A few things worth knowing:",
    "welcome.close": "Close",
    "welcome.never": "Don't show again",

    "welcome.s1_eyebrow": "01 · VOICE CONTROL",
    "welcome.s1_title": "You can talk to your computer!",
    "welcome.s1_lead": "Your computer is voice-controlled with local, completely private AI.",
    "welcome.f9_title": "Hold F9 to dictate in any app",
    "welcome.f9_text": "Hold the key, speak, let go. Your words are typed wherever the cursor is: in a message, a document or the browser. Works in 25 languages.",
    "welcome.win_title": "Press to open the start menu, hold to speak",
    "welcome.win_text": "Try “make the screen brighter” or “open Google”.",
    "welcome.s2_eyebrow": "02 · SECURITY",
    "welcome.s2_title": "How to lock or switch off in any emergency",
    "welcome.sec_lock_badge": "LOCK",
    "welcome.sec_lock_title": "Auto-lock",
    "welcome.sec_lock_text": "After a set time without mouse or keyboard activity, the screen locks by itself. A notification warns you 10 seconds before; moving the mouse keeps you logged in.",
    "welcome.sec_off_badge": "OFF",
    "welcome.sec_off_title": "Auto-shutdown",
    "welcome.sec_off_text": "Once locked for 60 minutes, the laptop switches itself fully off. Click the timer in the panel to choose another time.",
    "welcome.sec_lid_badge": "LID",
    "welcome.sec_lid_title": "Close the lid",
    "welcome.sec_lid_text": "Closing the lid locks the laptop instantly and turns the screen off.",
    "welcome.sec_4x_badge": "4×",
    "welcome.sec_4x_title": "Press the power key four times",
    "welcome.sec_4x_text": "Four quick presses in a row turn the laptop fully off at once.",
    "welcome.sec_hold_badge": "10 s",
    "welcome.sec_hold_title": "Press and hold the power key",
    "welcome.sec_hold_text": "If all else fails: hold the power key for 10 seconds. This cuts the power immediately.",
    "welcome.sec_note": "A single press of the power key opens a dialog with Lock, Restart and Shut Down. Your Cyberbeest is off only when all its blue LEDs are dark.",
    "welcome.s3_eyebrow": "03 · THE PANEL",
    "welcome.s3_title": "What the icons in the panel mean",
    "welcome.s3_lead": "Move the mouse over an icon in the panel to see what it does.",
    "welcome.s3_nohl": "The explanations below match the standard panel.",
    "welcome.s4_eyebrow": "04 · FACTS",
    "welcome.s4_title": "Random fact",
    "welcome.p_menu_n": "Menu",
    "welcome.p_menu": "All your apps, search and voice commands. The Windows key opens it too.",
    "welcome.p_launchers_n": "Quick launch",
    "welcome.p_launchers": "One click starts these apps. Hover over an icon to see its name.",
    "welcome.p_taskbar_n": "Open windows",
    "welcome.p_taskbar": "Every open app shows up here. Click to bring it to the front or minimise it.",
    "welcome.p_dictate_n": "Dictate",
    "welcome.p_dictate": "The voice-typing icon. Hold F9 or click it to speak; the speech model lives on this laptop.",
    "welcome.p_bluetooth_n": "Bluetooth",
    "welcome.p_bluetooth": "Bluetooth is off until you switch it on. Click the icon to set it up.",
    "welcome.p_volume_n": "Volume",
    "welcome.p_volume": "Click to turn speakers and microphone up or down.",
    "welcome.p_cpu_n": "Processor light",
    "welcome.p_cpu": "A red light sweeps back and forth, faster the harder the processor works.",
    "welcome.p_disk_n": "Disk activity",
    "welcome.p_disk": "A green light sweep that speeds up with every read or write on the disk.",
    "welcome.p_network_n": "Network activity",
    "welcome.p_network": "A blue light sweep that follows how much data flows through your network connection.",
    "welcome.p_memory_n": "Memory tank",
    "welcome.p_memory": "Fills like liquid as the memory (RAM) is used. The tooltip also shows swap and disk space.",
    "welcome.p_wattage_n": "Power draw",
    "welcome.p_wattage": "How many watts the laptop uses right now, and how much battery time is left.",
    "welcome.p_battery_n": "Battery",
    "welcome.p_battery": "Charge level. Click for the display brightness slider.",
    "welcome.p_status_n": "Lock timers & updates",
    "welcome.p_status": "Counts down to auto-lock and auto-shutdown and shows whether the last security-update check worked. Hover for your IP address.",
    "welcome.p_mic_n": "Microphone dot",
    "welcome.p_mic": "A flashing red dot means an app is recording from the microphone.",
    "welcome.p_clipboard_n": "Clipboard",
    "welcome.p_clipboard": "Shows what you copied. Click to view, edit or clear it. It empties itself after 15 minutes.",
    "welcome.p_vpn_n": "VPN",
    "welcome.p_vpn": "Connect or disconnect your VPN with one click, once you have imported a WireGuard file.",
    "welcome.p_connections_n": "Network connections",
    "welcome.p_connections": "Lists which apps are talking to the internet. A red mark shows an incoming connection.",
    "welcome.p_clock_n": "Clock",
    "welcome.p_clock": "Click for the calendar.",
    "welcome.s3_hint": "Hover over an icon above.",
    "welcome.facts_more": "Another fact",
    "welcome.facts_open": "All Facts",
    "welcome.hidden_title": "Welcome screen hidden",
    "welcome.hidden_body": "To see it again, press and hold the Windows key and say “welcome”.",
}
