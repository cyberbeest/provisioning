# gopanel

A pure-Go X11 panel (no cgo, no toolkit) that mirrors the xfce4-panel plugin list.
Reserves a bottom strip via `_NET_WM_STRUT_PARTIAL`, lays out items, draws everything itself.

Build everything: `./build.sh`   Run: `./gopanel` (alongside xfce4-panel is fine)

    gopanel version   version + git revision
    gopanel reload    rebuild all items from the xfce4-panel config (also SIGHUP, and automatic via inotify)
    gopanel restart   re-exec the binary (helpers keep running and reconnect)
    gopanel quit      stop (also stops helpers the panel started)

## Items (built from xfce4-panel's plugin list, in order)

| xfce plugin        | gopanel                                                              |
|--------------------|----------------------------------------------------------------------|
| launcher           | .desktop launchers (icon theme + SVG), tooltip                       |
| separator          | gap or expanding spacer                                              |
| tasklist           | taskbar: EWMH windows, click/middle/right menu                       |
| systray            | StatusNotifier host (+ own watcher if none), icon menus (dbusmenu)   |
| pulseaudio         | volume icon, scroll, middle-click mute, click opens pavucontrol      |
| power-manager      | battery icon + percent                                               |
| clock              | date over time                                                       |
| genmon             | built-in runner (`<img> <txt> <tool> <click> <txtclick>`)            |
| kitt-scanner, mem-liquid, io-scanner, network-scanner, wattage-panel | helper processes, see below |
| whiskermenu        | application menu: categories from the XDG menu files, search, favorites, recent |

## Helpers

Separate processes (`helpers/<name>/<name>`) that the panel starts, adopts after `restart` and
restarts if they die. They never talk to X: they send frames or text over a unix socket.
See PROTOCOL.md. Shared code: `scanner/` (vertical LED scanners), `procinfo/` (top CPU/RAM),
`gfx/` (text with Pango-lite markup), `proto/` (helper-side client library).

## Running next to the XFCE panel

Right-click on empty panel space (separators, launchers, clock) opens a menu: Start/Stop XFCE
panel, Restart/Quit this panel. `xfce-panel-watchdog` (lib/xfce-panel-watchdog.sh) relaunches
a dead xfce4-panel, so Stop writes `$XDG_RUNTIME_DIR/cyberbeest-xfce-panel-stopped`, which the
watchdog respects until Start removes it (or the next login). Scripts that reload the panel
(lib/xfce-panel-reload.sh, panel-icon toggles) ignore the marker. The Whisker entry
"Cyberbeest Panel (experimental)" (cyberbeest-gopanel.desktop) starts this panel; a second
instance refuses to start.
When xfce4-panel is gone gopanel becomes the StatusNotifier watcher (and rescans the bus for items that
registered with the old one) and owns the XEmbed tray selection (xembed.go), so Telegram, nm-applet and
friends dock into it; `gopanel yield` hands the selection back before xfce4-panel starts.
Switching is done by cyberbeest-panel-choice.sh (also run at login via cyberbeest-panel-choice.desktop,
chosen in Cyberbeest Settings > Panel); cyberbeest-whisker-key.sh is the Windows-key binding.

## Monitors

The panel lives on one monitor: `MONITOR=` in `~/.config/cyberbeest/panel.conf` (Settings > Panel, shown
with 2+ monitors) is `auto` (output named in the xfce4-panel config, else primary, else leftmost), an
output name, or `all`. With `all` every other monitor gets a replica: its own window, strut and layout
(taskbar and spacers use that monitor's width), same items. XEmbed tray icons are real windows and stay on
the main panel; replicas leave that slot out. Events on a replica run through `withReplica` (panels.go),
which makes it the current panel (monitor globals, item x/width) for the duration. Setting changes and
monitor changes (RandR screen/output/CRTC events, `gopanel reload`) rebuild the replicas.
Test without hardware: Xvfb + `xrandr --setmonitor` (delete the `screen` monitor via `--output screen --off`),
gopanel under `dbus-run-session` with its own HOME and XDG_RUNTIME_DIR.

## Shipping

No binary is shipped or published. `../../69-cyberbeest-panel.sh` builds panel + helpers on each machine
from this source (`-trimpath`, `CGO_ENABLED=0`, `-mod=readonly`: the Go modules are downloaded at build time
and checked against the hashes in `go.sum`). The Go 1.26 compiler (`golang-1.26-go`, trixie-backports,
~50 MB download) is installed for the build and purged right after, unless it was already installed, in which case it is
left alone. The build is skipped when the source hash matches `~/.local/lib/gopanel/.srchash`; a failed build keeps the
installed panel. Then 69- unpacks to `~/.local/lib/gopanel`,
links `~/.local/bin/gopanel`, installs the switcher and the autostart entry, and `gopanel restart`s a running panel.
It never switches panels or writes `panel.conf`; the user picks the panel in Settings > Panel.
On the dev machine the development build runs;
installing 69- there would put the installed build first in `~/.local/bin`, so don't (or remove the link).

## Notes

- Version lives in `main.go` (`const version`); bump it on every behaviour change.
- All X image uploads must go through `putBGRX` (xutil.go): an oversized PutImage makes xgb
  desynchronise and hang the next reply.
- Control and helper sockets are reachable by same-uid jailed apps: commands carry no data,
  nothing can launch anything. Helpers can draw into the panel, though.
- Popups (popup.go, popups_ui.go): clock click = month calendar, volume click = slider + mute + mixer
  (right click = pavucontrol). `gopanel calendar|volume` toggles them, e.g. for testing.
- Power button click = battery text + brightness slider (logind SetBrightness; scroll on the button
  also changes it) + links to power settings; `gopanel power` toggles it.
- If gopanel dies while the XFCE panel is stopped, xfce-panel-watchdog drops the marker after ~15 s and the
  XFCE panel returns (so the desktop is never left without a panel).
- Multi-monitor: the panel sits at the bottom of the primary monitor (RandR) and follows resolution or
  monitor changes (monitor.go; popups/menus/tooltips position against that monitor). Tested by resizing a
  nested X display; not tested with a real second monitor.
- German: i18n.go translates calendar, popups, menus and tooltips when /etc/default/locale is de_*
  (`GOPANEL_LANG=de_DE` forces it for testing).
- Media keys (mediakeys.go): volume up/down, mute, mic mute, play/pause/next/prev (MPRIS). The pulseaudio
  plugin of xfce4-panel normally grabs these; gopanel grabs them too and loses harmlessly if it runs alongside.
- Whisker: right-click on an app = add/remove favorite, add to desktop.
- Helpers also pause while the screensaver (lock screen) is active, not just in DPMS standby.
- Layout: launchers sit directly after the menu button (before the expanding taskbar), so they never move
  while the rest fills in. Item widths of the last run are cached (~/.cache/gopanel/widths.tsv) and reserved at
  startup, so tray/helpers/genmon appear in place instead of pushing things around; unconfirmed reservations
  are released after 3 s.
- Helpers: duplicates (a restarted panel racing a surviving helper) are told to `quit` and exit instead of
  reconnecting forever; the supervisor waits 4 s for survivors before spawning; zombie helpers from before an
  exec-restart are reaped.
- Right-click on a helper or genmon item adds "Properties…" to the panel menu: lib/cyberbeest-settings.py
  --rc FILE shows a generic editor for the plugin's xfce rc file (checkbox / number / colour / text per key);
  saving makes gopanel restart that helper (it exits on `quit`, the supervisor respawns it with the new settings).
- Two-line labels (label.go renderStacked): text of the wattage helper and of the status genmon (autolock/
  shutdown timers) is split into two balanced lines, saving ~110 px. Which items: one name/command substring
  per line in ~/.config/gopanel/stacked.conf (default: wattage-panel, panel-status-genmon).
- XEmbed icons of apps that also have a StatusNotifier icon (blueman registers both) are hidden, so no blank slot.
- Volume sliders go up to 150% (orange past the 100% tick) like pavucontrol; wheel over the taskbar cycles windows.
- Volume popup has a second section for the microphone (default source: slider + mute).
- Free width goes to the taskbar first (up to a full-width button per window), the expanding separator
  gets the rest -- buttons are no longer squeezed next to empty space.
- Volume keys show an OSD notification (speaker + bar).
- Memory (2026-10-13, PSS): gopanel with its 5 helper processes ~64 MB; xfce4-panel with its 15 plugin
  wrappers ~108 MB (idle, 25 s after start). PSS splits shared libraries across their users, so GTK's share
  in the XFCE number is flattered by other GTK apps running.
- Not done: per-plugin settings dialogs, (the XFCE tasklist does not reorder buttons by drag either).
