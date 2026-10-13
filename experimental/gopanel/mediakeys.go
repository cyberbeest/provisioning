package main

import (
	"fmt"
	"log"
	"os/exec"
	"strings"

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
	// with and without NumLock (Mod2) and CapsLock (Lock)
	for _, kc := range mediaKeycodes {
		for _, mods := range []uint16{0, xproto.ModMaskLock, xproto.ModMask2, xproto.ModMaskLock | xproto.ModMask2} {
			xproto.GrabKeyChecked(xc, true, xroot, mods, kc, xproto.GrabModeAsync, xproto.GrabModeAsync).Check()
		}
	}
}

// mediaKey handles a grabbed key press; false if it is not a media key.
func mediaKey(kc xproto.Keycode) bool {
	log.Println("media key", kc)
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
