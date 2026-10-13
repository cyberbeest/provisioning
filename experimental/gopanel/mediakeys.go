package main

import (
	"fmt"
	"log"
	"os/exec"
	"strconv"
	"strings"
	"sync/atomic"
	"time"

	"github.com/godbus/dbus/v5"
	"github.com/jezek/xgb/xproto"
)

// Media keys. The xfce4-pulseaudio-plugin grabs these while it runs; without it the
// keys would do nothing. Grabbing fails harmlessly when another client (the XFCE
// panel's plugin) already holds them.

const (
	kcMute, kcVolDown, kcVolUp = 121, 122, 123
	kcNext, kcPlay, kcPrev     = 171, 172, 173
	kcMicMute                  = 198
)

var mediaKeycodes = []xproto.Keycode{kcMute, kcVolDown, kcVolUp, kcNext, kcPlay, kcPrev, kcMicMute}

func grabMediaKeys() {
	// whatever modifiers are active (NumLock, CapsLock, AltGr, ...)
	for _, kc := range mediaKeycodes {
		for _, mods := range []uint16{xproto.ModMaskAny} {
			if err := xproto.GrabKeyChecked(xc, true, xroot, mods, kc, xproto.GrabModeAsync, xproto.GrabModeAsync).Check(); err != nil {
				log.Printf("media key %d (mods %#x) not grabbed: %v", kc, mods, err)
			}
		}
	}
}

// mediaKey handles a grabbed key press; false if it is not a media key.
func mediaKey(kc xproto.Keycode) bool {
	log.Println("media key", kc)
	defer func() {
		switch kc {
		case kcMute, kcVolUp, kcVolDown:
			go volumeOSD()
		}
	}()
	switch kc {
	case kcMute:
		go exec.Command("pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle").Run()
	case kcVolUp:
		go exec.Command("pactl", "set-sink-volume", "@DEFAULT_SINK@", "+5%").Run()
	case kcVolDown:
		go exec.Command("pactl", "set-sink-volume", "@DEFAULT_SINK@", "-5%").Run()
	case kcMicMute:
		go exec.Command("pactl", "set-source-mute", "@DEFAULT_SOURCE@", "toggle").Run()
	case kcPlay:
		go mprisCall("PlayPause")
	case kcNext:
		go mprisCall("Next")
	case kcPrev:
		go mprisCall("Previous")
	default:
		return false
	}
	return true
}

// mprisCall sends a method to the media player that is playing, else to the first one.
func mprisCall(method string) {
	conn, err := dbus.ConnectSessionBus()
	if err != nil {
		return
	}
	defer conn.Close()
	var names []string
	if conn.BusObject().Call("org.freedesktop.DBus.ListNames", 0).Store(&names) != nil {
		return
	}
	target := ""
	for _, n := range names {
		if !strings.HasPrefix(n, "org.mpris.MediaPlayer2.") {
			continue
		}
		if target == "" {
			target = n
		}
		v, err := conn.Object(n, "/org/mpris/MediaPlayer2").GetProperty("org.mpris.MediaPlayer2.Player.PlaybackStatus")
		if err == nil && fmt.Sprint(v.Value()) == "Playing" {
			target = n
			break
		}
	}
	if target != "" {
		conn.Object(target, "/org/mpris/MediaPlayer2").Call("org.mpris.MediaPlayer2.Player."+method, 0)
	}
}

var osdID atomic.Uint32

// volumeOSD shows the new volume as a notification (replacing the previous one), like the
// pulseaudio plugin does for its keys.
func volumeOSD() {
	time.Sleep(120 * time.Millisecond) // let pactl finish
	vol, muted := 0, pactl("get-sink-mute", "@DEFAULT_SINK@") == "Mute: yes\n"
	if f := strings.Fields(pactl("get-sink-volume", "@DEFAULT_SINK@")); len(f) > 4 {
		vol, _ = strconv.Atoi(strings.TrimSuffix(f[4], "%"))
	}
	icon, body := "audio-volume-high", fmt.Sprintf("%d%%", vol)
	switch {
	case muted || vol == 0:
		icon = "audio-volume-muted"
		if muted {
			body = tr("Volume muted")
		}
	case vol < 34:
		icon = "audio-volume-low"
	case vol < 67:
		icon = "audio-volume-medium"
	}
	conn, err := dbus.ConnectSessionBus()
	if err != nil {
		return
	}
	defer conn.Close()
	hints := map[string]dbus.Variant{
		"value":                           dbus.MakeVariant(int32(min(vol, 100))),
		"x-canonical-private-synchronous": dbus.MakeVariant("gopanel-volume"),
	}
	var id uint32
	call := conn.Object("org.freedesktop.Notifications", "/org/freedesktop/Notifications").Call(
		"org.freedesktop.Notifications.Notify", 0, "gopanel", osdID.Load(), icon, tr("Volume"), body, []string{}, hints, int32(1500))
	if call.Store(&id) == nil {
		osdID.Store(id)
	}
}
