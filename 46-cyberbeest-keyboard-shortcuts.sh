#!/bin/bash
# Installs Cyberbeest's keyboard-shortcut customizations, cloned from the
# dev machine's live xfce4-keyboard-shortcuts.xml (found to be missing from
# provisioning entirely on 2026-08-26, after the Super key didn't open
# Whisker on a freshly provisioned machine):
#   - Super_L opens the Whisker menu (xfce4-popup-whiskermenu).
#   - Ctrl+Alt+Delete and the power key open cyberbeest-logout (installed by
#     09-cyberbeest-logout-dialog.sh) instead of their Xfce defaults.
# Everything else in this file is Debian's own stock xfce4-keyboard-shortcuts
# defaults (window-manager bindings, screenshot keys, etc.) -- shipped as a
# full channel file rather than a partial diff since that's what xfconf
# itself works in, same as 16-power-lock-config.sh's channel files.
# Depends on: 09-cyberbeest-logout-dialog.sh (cyberbeest-logout must exist at
# the path below), 12-xfce-panel-layout.sh (Whisker must be plugin-1 for
# xfce4-popup-whiskermenu to have anything to pop open).
# Written to disk only, like 00a-touchpad-tap-global.sh -- see that script's
# comment for why a live xfconf-query push is avoided for this kind of
# session-wide setting. A logout/reboot is needed to pick this up.
# Idempotent: safe to re-run (backs up any pre-existing file the first time,
# as *.pre-cyberbeest).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/46-cyberbeest-keyboard-shortcuts.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing keyboard-shortcut customizations ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
XML_DIR="$TARGET_HOME/.config/xfce4/xfconf/xfce-perchannel-xml"
DEST="$XML_DIR/xfce4-keyboard-shortcuts.xml"

install -d -o "$TARGET_USER" -g "$TARGET_USER" "$XML_DIR"
if [ -e "$DEST" ] && [ ! -e "$DEST.pre-cyberbeest" ]; then
	cp "$DEST" "$DEST.pre-cyberbeest"
fi

cat > "$DEST" <<EOF
<?xml version="1.1" encoding="UTF-8"?>

<channel name="xfce4-keyboard-shortcuts" version="1.0">
  <property name="commands" type="empty">
    <property name="default" type="empty">
      <property name="&lt;Alt&gt;F1" type="empty"/>
      <property name="&lt;Alt&gt;F2" type="empty">
        <property name="startup-notify" type="empty"/>
      </property>
      <property name="&lt;Alt&gt;F3" type="empty">
        <property name="startup-notify" type="empty"/>
      </property>
      <property name="&lt;Primary&gt;&lt;Alt&gt;Delete" type="empty"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;l" type="empty"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;t" type="empty"/>
      <property name="XF86Display" type="empty"/>
      <property name="&lt;Super&gt;p" type="empty"/>
      <property name="&lt;Primary&gt;Escape" type="empty"/>
      <property name="XF86WWW" type="empty"/>
      <property name="HomePage" type="empty"/>
      <property name="XF86Mail" type="empty"/>
      <property name="Print" type="empty"/>
      <property name="&lt;Alt&gt;Print" type="empty"/>
      <property name="&lt;Shift&gt;Print" type="empty"/>
      <property name="&lt;Super&gt;e" type="empty"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;f" type="empty"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;Escape" type="empty"/>
      <property name="&lt;Primary&gt;&lt;Shift&gt;Escape" type="empty"/>
      <property name="&lt;Super&gt;r" type="empty">
        <property name="startup-notify" type="empty"/>
      </property>
      <property name="&lt;Alt&gt;&lt;Super&gt;s" type="empty"/>
    </property>
    <property name="custom" type="empty">
      <property name="&lt;Alt&gt;F2" type="string" value="xfce4-appfinder --collapsed">
        <property name="startup-notify" type="bool" value="true"/>
      </property>
      <property name="&lt;Alt&gt;Print" type="string" value="xfce4-screenshooter -w"/>
      <property name="&lt;Super&gt;r" type="string" value="xfce4-appfinder -c">
        <property name="startup-notify" type="bool" value="true"/>
      </property>
      <property name="XF86WWW" type="string" value="exo-open --launch WebBrowser"/>
      <property name="XF86Mail" type="string" value="exo-open --launch MailReader"/>
      <property name="&lt;Alt&gt;F3" type="string" value="xfce4-appfinder">
        <property name="startup-notify" type="bool" value="true"/>
      </property>
      <property name="Print" type="string" value="xfce4-screenshooter"/>
      <property name="&lt;Primary&gt;Escape" type="string" value="xfdesktop --menu"/>
      <property name="&lt;Shift&gt;Print" type="string" value="xfce4-screenshooter -r"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;Delete" type="string" value="$TARGET_HOME/.local/bin/cyberbeest-logout"/>
      <property name="&lt;Alt&gt;&lt;Super&gt;s" type="string" value="orca"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;t" type="string" value="exo-open --launch TerminalEmulator"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;f" type="string" value="thunar"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;l" type="string" value="xflock4"/>
      <property name="&lt;Alt&gt;F1" type="string" value="xfce4-popup-applicationsmenu"/>
      <property name="&lt;Super&gt;p" type="string" value="xfce4-display-settings --minimal"/>
      <property name="&lt;Primary&gt;&lt;Shift&gt;Escape" type="string" value="xfce4-taskmanager"/>
      <property name="&lt;Super&gt;e" type="string" value="thunar"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;Escape" type="string" value="xkill"/>
      <property name="HomePage" type="string" value="exo-open --launch WebBrowser"/>
      <property name="XF86Display" type="string" value="xfce4-display-settings --minimal"/>
      <property name="override" type="bool" value="true"/>
      <property name="Super_L" type="string" value="xfce4-popup-whiskermenu"/>
      <property name="XF86PowerOff" type="string" value="$TARGET_HOME/.local/bin/cyberbeest-logout"/>
    </property>
  </property>
  <property name="xfwm4" type="empty">
    <property name="default" type="empty">
      <property name="&lt;Alt&gt;Insert" type="empty"/>
      <property name="Escape" type="empty"/>
      <property name="Left" type="empty"/>
      <property name="Right" type="empty"/>
      <property name="Up" type="empty"/>
      <property name="Down" type="empty"/>
      <property name="&lt;Alt&gt;Tab" type="empty"/>
      <property name="&lt;Alt&gt;&lt;Shift&gt;Tab" type="empty"/>
      <property name="&lt;Alt&gt;Delete" type="empty"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;Down" type="empty"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;Left" type="empty"/>
      <property name="&lt;Shift&gt;&lt;Alt&gt;Page_Down" type="empty"/>
      <property name="&lt;Alt&gt;F4" type="empty"/>
      <property name="&lt;Alt&gt;F6" type="empty"/>
      <property name="&lt;Alt&gt;F7" type="empty"/>
      <property name="&lt;Alt&gt;F8" type="empty"/>
      <property name="&lt;Alt&gt;F9" type="empty"/>
      <property name="&lt;Alt&gt;F10" type="empty"/>
      <property name="&lt;Alt&gt;F11" type="empty"/>
      <property name="&lt;Alt&gt;F12" type="empty"/>
      <property name="&lt;Primary&gt;&lt;Shift&gt;&lt;Alt&gt;Left" type="empty"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;End" type="empty"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;Home" type="empty"/>
      <property name="&lt;Primary&gt;&lt;Shift&gt;&lt;Alt&gt;Right" type="empty"/>
      <property name="&lt;Primary&gt;&lt;Shift&gt;&lt;Alt&gt;Up" type="empty"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;KP_1" type="empty"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;KP_2" type="empty"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;KP_3" type="empty"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;KP_4" type="empty"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;KP_5" type="empty"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;KP_6" type="empty"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;KP_7" type="empty"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;KP_8" type="empty"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;KP_9" type="empty"/>
      <property name="&lt;Alt&gt;space" type="empty"/>
      <property name="&lt;Shift&gt;&lt;Alt&gt;Page_Up" type="empty"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;Right" type="empty"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;d" type="empty"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;Up" type="empty"/>
      <property name="&lt;Super&gt;Tab" type="empty"/>
      <property name="&lt;Primary&gt;F1" type="empty"/>
      <property name="&lt;Primary&gt;F2" type="empty"/>
      <property name="&lt;Primary&gt;F3" type="empty"/>
      <property name="&lt;Primary&gt;F4" type="empty"/>
      <property name="&lt;Primary&gt;F5" type="empty"/>
      <property name="&lt;Primary&gt;F6" type="empty"/>
      <property name="&lt;Primary&gt;F7" type="empty"/>
      <property name="&lt;Primary&gt;F8" type="empty"/>
      <property name="&lt;Primary&gt;F9" type="empty"/>
      <property name="&lt;Primary&gt;F10" type="empty"/>
      <property name="&lt;Primary&gt;F11" type="empty"/>
      <property name="&lt;Primary&gt;F12" type="empty"/>
      <property name="&lt;Super&gt;KP_Left" type="empty"/>
      <property name="&lt;Super&gt;KP_Right" type="empty"/>
      <property name="&lt;Super&gt;KP_Down" type="empty"/>
      <property name="&lt;Super&gt;KP_Up" type="empty"/>
      <property name="&lt;Super&gt;KP_Page_Up" type="empty"/>
      <property name="&lt;Super&gt;KP_Home" type="empty"/>
      <property name="&lt;Super&gt;KP_End" type="empty"/>
      <property name="&lt;Super&gt;KP_Next" type="empty"/>
    </property>
    <property name="custom" type="empty">
      <property name="&lt;Primary&gt;F12" type="string" value="workspace_12_key"/>
      <property name="&lt;Super&gt;KP_Down" type="string" value="tile_down_key"/>
      <property name="&lt;Alt&gt;F4" type="string" value="close_window_key"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;KP_3" type="string" value="move_window_workspace_3_key"/>
      <property name="&lt;Primary&gt;F2" type="string" value="workspace_2_key"/>
      <property name="&lt;Primary&gt;F6" type="string" value="workspace_6_key"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;Down" type="string" value="down_workspace_key"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;KP_9" type="string" value="move_window_workspace_9_key"/>
      <property name="&lt;Super&gt;KP_Up" type="string" value="tile_up_key"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;End" type="string" value="move_window_next_workspace_key"/>
      <property name="&lt;Primary&gt;F8" type="string" value="workspace_8_key"/>
      <property name="&lt;Primary&gt;&lt;Shift&gt;&lt;Alt&gt;Left" type="string" value="move_window_left_key"/>
      <property name="&lt;Super&gt;KP_Right" type="string" value="tile_right_key"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;KP_4" type="string" value="move_window_workspace_4_key"/>
      <property name="Right" type="string" value="right_key"/>
      <property name="Down" type="string" value="down_key"/>
      <property name="&lt;Primary&gt;F3" type="string" value="workspace_3_key"/>
      <property name="&lt;Shift&gt;&lt;Alt&gt;Page_Down" type="string" value="lower_window_key"/>
      <property name="&lt;Primary&gt;F9" type="string" value="workspace_9_key"/>
      <property name="&lt;Alt&gt;Tab" type="string" value="cycle_windows_key"/>
      <property name="&lt;Primary&gt;&lt;Shift&gt;&lt;Alt&gt;Right" type="string" value="move_window_right_key"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;Right" type="string" value="right_workspace_key"/>
      <property name="&lt;Alt&gt;F6" type="string" value="stick_window_key"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;KP_5" type="string" value="move_window_workspace_5_key"/>
      <property name="&lt;Primary&gt;F11" type="string" value="workspace_11_key"/>
      <property name="&lt;Alt&gt;F10" type="string" value="maximize_window_key"/>
      <property name="&lt;Alt&gt;Delete" type="string" value="del_workspace_key"/>
      <property name="&lt;Super&gt;Tab" type="string" value="switch_window_key"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;d" type="string" value="show_desktop_key"/>
      <property name="&lt;Primary&gt;F4" type="string" value="workspace_4_key"/>
      <property name="&lt;Super&gt;KP_Page_Up" type="string" value="tile_up_right_key"/>
      <property name="&lt;Alt&gt;F7" type="string" value="move_window_key"/>
      <property name="Up" type="string" value="up_key"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;KP_6" type="string" value="move_window_workspace_6_key"/>
      <property name="&lt;Alt&gt;F11" type="string" value="fullscreen_key"/>
      <property name="&lt;Alt&gt;space" type="string" value="popup_menu_key"/>
      <property name="&lt;Super&gt;KP_Home" type="string" value="tile_up_left_key"/>
      <property name="Escape" type="string" value="cancel_key"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;KP_1" type="string" value="move_window_workspace_1_key"/>
      <property name="&lt;Super&gt;KP_Next" type="string" value="tile_down_right_key"/>
      <property name="&lt;Super&gt;KP_Left" type="string" value="tile_left_key"/>
      <property name="&lt;Shift&gt;&lt;Alt&gt;Page_Up" type="string" value="raise_window_key"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;Home" type="string" value="move_window_prev_workspace_key"/>
      <property name="&lt;Alt&gt;&lt;Shift&gt;Tab" type="string" value="cycle_reverse_windows_key"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;Left" type="string" value="left_workspace_key"/>
      <property name="&lt;Alt&gt;F12" type="string" value="above_key"/>
      <property name="&lt;Primary&gt;&lt;Shift&gt;&lt;Alt&gt;Up" type="string" value="move_window_up_key"/>
      <property name="&lt;Primary&gt;F5" type="string" value="workspace_5_key"/>
      <property name="&lt;Alt&gt;F8" type="string" value="resize_window_key"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;KP_7" type="string" value="move_window_workspace_7_key"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;KP_2" type="string" value="move_window_workspace_2_key"/>
      <property name="&lt;Super&gt;KP_End" type="string" value="tile_down_left_key"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;Up" type="string" value="up_workspace_key"/>
      <property name="&lt;Alt&gt;F9" type="string" value="hide_window_key"/>
      <property name="&lt;Primary&gt;F7" type="string" value="workspace_7_key"/>
      <property name="&lt;Primary&gt;F10" type="string" value="workspace_10_key"/>
      <property name="Left" type="string" value="left_key"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;KP_8" type="string" value="move_window_workspace_8_key"/>
      <property name="&lt;Alt&gt;Insert" type="string" value="add_workspace_key"/>
      <property name="&lt;Primary&gt;F1" type="string" value="workspace_1_key"/>
      <property name="override" type="bool" value="true"/>
    </property>
  </property>
  <property name="providers" type="array">
    <value type="string" value="xfwm4"/>
    <value type="string" value="commands"/>
  </property>
</channel>
EOF
chown "$TARGET_USER:$TARGET_USER" "$DEST"

echo "Wrote $DEST" | tee -a "$LOG"
echo "=== $(date) : done. Reboot (or log out/in) to pick this up. ===" | tee -a "$LOG"
echo "MANUAL_TODO: Reboot (or log out/in) for the Super/Ctrl+Alt+Del/power-key shortcuts to take effect." | tee -a "$LOG"
