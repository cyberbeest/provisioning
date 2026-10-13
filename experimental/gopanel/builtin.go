package main

import (
	"fmt"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"time"
)

func sysfsString(path string) string {
	b, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(b))
}

func sysfsInt(path string) int {
	n, _ := strconv.Atoi(sysfsString(path))
	return n
}

func batteryOnAC() bool {
	for _, p := range []string{"ADP1", "AC", "ACAD", "AC0"} {
		if sysfsString("/sys/class/power_supply/"+p+"/online") == "1" {
			return true
		}
	}
	return false
}

// newPowerItem replicates xfce4-power-manager-plugin: battery icon plus percentage.
func newPowerItem() *item {
	const bat = "/sys/class/power_supply/BAT0"
	if _, err := os.Stat(bat); err != nil {
		return newItem("power") // no battery: empty, zero width
	}
	it := newItem("power")
	it.hl = true
	refresh := func() {
		pct := sysfsInt(bat + "/capacity")
		status := sysfsString(bat + "/status")
		level := (pct + 5) / 10 * 10 // icons exist in steps of 10
		state, text := "", ""
		switch {
		case status == "Charging":
			state, text = "-charging", "Charging"
		case status == "Full" || (pct >= 99 && batteryOnAC()):
			state, text = "-charged", "Fully charged"
			if level != 100 {
				state = ""
			}
		default:
			text = "Discharging"
			if p := sysfsInt(bat + "/power_now"); p > 0 {
				hours := float64(sysfsInt(bat+"/energy_now")) / float64(p)
				text = fmt.Sprintf("Discharging, %d:%02d remaining", int(hours), int((hours-float64(int(hours)))*60))
			}
		}
		name := fmt.Sprintf("battery-level-%d%s-symbolic", level, state)
		img := iconText(loadIcon(name), fmt.Sprintf("%d%%", pct), 2)
		tip := "<b>Computer</b>\n" + text
		it.post(itemUpdate{img: img, tip: &tip, w: img.Bounds().Dx() + 2*labelEdge})
	}
	go func() {
		for {
			refresh()
			select {
			case <-time.After(15 * time.Second):
			case <-it.dead:
				return
			}
		}
	}()
	return it
}

// pactl runs a pactl command and returns its output.
func pactl(args ...string) string {
	out, _ := exec.Command("pactl", args...).Output()
	return string(out)
}

// newVolumeItem replicates the xfce4-pulseaudio-plugin button: a volume icon; scroll
// changes the volume, middle click mutes, left click opens the mixer. Updates are
// pushed by `pactl subscribe`, so there is no polling.
func newVolumeItem() *item {
	it := newItem("volume")
	it.hl = true
	refresh := func() {
		vol, muted := 0, pactl("get-sink-mute", "@DEFAULT_SINK@") == "Mute: yes\n"
		if f := strings.Fields(pactl("get-sink-volume", "@DEFAULT_SINK@")); len(f) > 4 {
			vol, _ = strconv.Atoi(strings.TrimSuffix(f[4], "%"))
		}
		name := "audio-volume-high-symbolic"
		switch {
		case muted || vol == 0:
			name = "audio-volume-muted-symbolic"
		case vol < 34:
			name = "audio-volume-low-symbolic"
		case vol < 67:
			name = "audio-volume-medium-symbolic"
		}
		tip := fmt.Sprintf("Volume %d%%", vol)
		if muted {
			tip = "Volume muted"
		}
		it.post(itemUpdate{img: iconText(loadIcon(name), "", 0), tip: &tip, w: panelH})
	}
	it.click = func(x, y, btn int) {
		switch btn {
		case 1:
			if _, err := exec.LookPath("pavucontrol"); err == nil {
				run(exec.Command("pavucontrol"))
			}
		case 2:
			go exec.Command("pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle").Run()
		case 4:
			go exec.Command("pactl", "set-sink-volume", "@DEFAULT_SINK@", "+5%").Run()
		case 5:
			go exec.Command("pactl", "set-sink-volume", "@DEFAULT_SINK@", "-5%").Run()
		}
	}
	go func() {
		refresh()
		for !it.isDead() {
			cmd := exec.Command("pactl", "subscribe")
			out, err := cmd.StdoutPipe()
			if err != nil || cmd.Start() != nil {
				select {
				case <-time.After(5 * time.Second):
					continue
				case <-it.dead:
					return
				}
			}
			go func() { <-it.dead; cmd.Process.Kill() }()
			buf := make([]byte, 4096)
			var last time.Time
			for {
				n, err := out.Read(buf)
				if err != nil {
					break
				}
				s := string(buf[:n])
				if (strings.Contains(s, "sink") || strings.Contains(s, "server")) && time.Since(last) > 100*time.Millisecond {
					last = time.Now()
					refresh()
				}
			}
			cmd.Wait()
			select {
			case <-time.After(2 * time.Second):
			case <-it.dead:
				return
			}
		}
	}()
	return it
}
