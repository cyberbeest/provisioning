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
    "timer.more_settings": "More settings…",

    "pw.window_title": "Cyberbeest Change Password",
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
    "pw.pkexec_error": "Could not start pkexec:",
    "pw.pty_error": "Could not open a pty:",
    "pw.change_failed_wrong_current": (
        "The password could not be changed. This usually means the current "
        "password was incorrect."
    ),

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
}
