# English strings for provisioning's Python GUI scripts. Always loaded by
# lib/i18n.py as the fallback layer, regardless of the active locale.
#
# Keys are dotted "script-or-area.thing" names, e.g. logout.title.
STRINGS = {
    "logout.title": "Log Out",
    "logout.lock": "Lock",
    "logout.restart": "Restart",
    "logout.shutdown": "Shut Down",
    "logout.cancel": "Cancel",

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
    "timer.auto_shutdown_while_locked": "Auto-shutdown while locked",
    "timer.use_same_time": "Use the same time for AC and battery",
    "timer.important": "IMPORTANT",
    "timer.no_auto_lock_note": "Auto-lock is off, so auto-shutdown is disabled",
    "timer.shutdown_after_both": "Shutdown after locked for:",
    "timer.on_ac": "On AC power:",
    "timer.on_battery": "On battery:",
    "timer.power_saving_while_locked": "Power saving while locked…",

    "lockpower.window_title": "Cyberbeest Extended Power Options",
    "lockpower.info": (
        "Once the screen has been locked this long, windows are minimized "
        "and the browser's CPU use is capped, to save power. Downloads and "
        "notification sounds keep working, just slower."
    ),
    "lockpower.minimize_after": "Minimize windows after (minutes):",
    "lockpower.limit_cpu": "Limit browser CPU to (%):",
    "lockpower.never": "Never",
    "lockpower.off": "Off",
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
    "update_genmon.close": "Close",

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
    "run_gui.profile_continue": "_Continue",
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
    "run_gui.button_run_changed": "Run changed only",
    "run_gui.button_run_all": "Run all",
    "run_gui.button_run_selected": "Run selected",
    "run_gui.button_stop": "Stop after current script",
    "run_gui.more_actions_tooltip": "More actions",
    "run_gui.menu_disable_autostart": "Disable auto-provisioning on login",
    "run_gui.menu_edit_profile": "Provisioning profile...",
    "run_gui.total_time": "Total run time this session: {duration}",
    "run_gui.status_idle": "Idle. Double-click a script below to run just that one.",
    "run_gui.todo_frame_title": "Things to do after the provisioning completed",
    "run_gui.status_installing_zenity": "Installing zenity -- see the terminal window...",
    "run_gui.log_zenity_not_found": (
        "zenity not found -- opening a terminal window to install it "
        "(enter your sudo password there)...\n"
    ),
    "run_gui.log_zenity_installed": "=== zenity installed ===\n",
    "run_gui.log_zenity_install_failed": (
        "=== failed to install zenity (exit {status}) -- install it manually "
        "(sudo apt-get install zenity) and restart this tool ===\n"
    ),
    "run_gui.status_zenity_install_failed": "zenity install failed -- see log above.",
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
    "run_gui.status_starting": "{label}: starting (enter sudo password if prompted)...",
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
    "run_gui.log_skipped": "=== {script} skipped (not confirmed) ===\n",
    "run_gui.log_running_marker": "=== running {script} ===\n",
    "run_gui.log_done_marker": "=== {script} done ({duration}) ===\n",
    "run_gui.log_failed_marker": "=== {script} FAILED ({duration}, exit {status}) ===\n",
    "run_gui.log_stopping_dependency": "Stopping here since later scripts may depend on this one.\n",
    "run_gui.status_stopped": "Stopped after current script.",
    "run_gui.status_failed": "Failed: {script} -- see log above.",
    "run_gui.status_finished": "Finished successfully.",
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
}
