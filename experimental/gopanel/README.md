# gopanel (experimental)

Pure-Go X11 panel spike (no cgo). Reserves a bottom strip via `_NET_WM_STRUT_PARTIAL`
and draws the same launchers as the xfce4-panel launcher plugins.

Build: `go build -o gopanel .`  Run: `./gopanel` (alongside xfce4-panel)

    gopanel version   print version + git revision
    gopanel reload    re-read config and .desktop files (also SIGHUP, and automatic via inotify)
    gopanel restart   re-exec the binary (picks up a rebuild)
    gopanel quit

Control socket: `$XDG_RUNTIME_DIR/gopanel.sock`. Commands carry no data on purpose:
jailed apps in the same session can reach it.

Version lives in `main.go` (`const version`). Bump it on every behavior change.
