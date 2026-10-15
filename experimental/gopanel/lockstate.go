package main

import (
	"sync"
	"time"

	"github.com/godbus/dbus/v5"
)

// Screen-lock state, shared by everything that should go quiet while the desktop is locked
// (currently the genmon runner). Both screensaver D-Bus names expose GetActive() and an
// ActiveChanged(b) signal; xfce4-screensaver uses org.xfce.ScreenSaver, others the
// freedesktop one. The signal drives the state; a slow resync poll covers a missed signal.
var (
	lockMu     sync.Mutex
	lockActive bool
	lockCh     = make(chan struct{})
)

var screensaverIfaces = []struct{ iface, path string }{
	{"org.xfce.ScreenSaver", "/org/xfce/ScreenSaver"},
	{"org.freedesktop.ScreenSaver", "/org/freedesktop/ScreenSaver"},
}

func screenLocked() bool {
	lockMu.Lock()
	defer lockMu.Unlock()
	return lockActive
}

// lockChanged returns a channel closed on the next lock/unlock transition.
func lockChanged() <-chan struct{} {
	lockMu.Lock()
	defer lockMu.Unlock()
	return lockCh
}

func setScreenLocked(v bool) {
	lockMu.Lock()
	defer lockMu.Unlock()
	if v == lockActive {
		return
	}
	lockActive = v
	close(lockCh)
	lockCh = make(chan struct{})
}

func queryScreensaverActive(conn *dbus.Conn) bool {
	for _, s := range screensaverIfaces {
		var active bool
		call := conn.Object(s.iface, dbus.ObjectPath(s.path)).Call(s.iface+".GetActive", 0)
		if call.Err == nil && call.Store(&active) == nil && active {
			return true
		}
	}
	return false
}

// startLockWatcher runs for the life of the panel. Without a session bus the state stays
// "unlocked" and nothing is ever paused.
func startLockWatcher() {
	conn, err := dbus.ConnectSessionBus()
	if err != nil {
		return
	}
	for _, s := range screensaverIfaces {
		conn.AddMatchSignal(dbus.WithMatchInterface(s.iface), dbus.WithMatchMember("ActiveChanged"))
	}
	sigs := make(chan *dbus.Signal, 8)
	conn.Signal(sigs)
	setScreenLocked(queryScreensaverActive(conn))
	go func() {
		resync := time.NewTicker(time.Minute)
		defer resync.Stop()
		for {
			select {
			case s := <-sigs:
				if s.Name == "org.xfce.ScreenSaver.ActiveChanged" || s.Name == "org.freedesktop.ScreenSaver.ActiveChanged" {
					// Re-query rather than trust the body: both names may be live.
					setScreenLocked(queryScreensaverActive(conn))
				}
			case <-resync.C:
				setScreenLocked(queryScreensaverActive(conn))
			}
		}
	}()
}
