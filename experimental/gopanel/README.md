# gopanel (experimental)

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
instance refuses to start. Which panel starts at login is not wired up yet.
StatusNotifier icons need the watcher that xfce4-panel owns, so they vanish while it is stopped.

## Notes

- Version lives in `main.go` (`const version`); bump it on every behaviour change.
- All X image uploads must go through `putBGRX` (xutil.go): an oversized PutImage makes xgb
  desynchronise and hang the next reply.
- Control and helper sockets are reachable by same-uid jailed apps: commands carry no data,
  nothing can launch anything. Helpers can draw into the panel, though.
- Not done: XEmbed (legacy) tray, volume/clock/power popups, per-plugin settings dialogs,
  translations, screensaver-aware pausing (only DPMS standby pauses helpers).
