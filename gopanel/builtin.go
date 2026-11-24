package main

import (
	"fmt"
	"image"
	"math"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"syscall"
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
	it.click = func(x, y, btn int) {
		switch btn {
		case 1:
			openPowerPopup(it.x + it.w/2)
		case 4:
			go stepBrightness(+5)
		case 5:
			go stepBrightness(-5)
		}
	}
	refresh := func() {
		pct := sysfsInt(bat + "/capacity")
		status := sysfsString(bat + "/status")
		level := (pct + 5) / 10 * 10 // icons exist in steps of 10
		state, text := "", ""
		switch {
		case status == "Charging":
			state, text = "-charging", tr("Charging")
		case status == "Full" || (pct >= 99 && batteryOnAC()):
			state, text = "-charged", tr("Fully charged")
			if level != 100 {
				state = ""
			}
		default:
			text = tr("Discharging")
			if p := sysfsInt(bat + "/power_now"); p > 0 {
				hours := float64(sysfsInt(bat+"/energy_now")) / float64(p)
				text = fmt.Sprintf("%s, %d:%02d %s", tr("Discharging"), int(hours), int((hours-float64(int(hours)))*60), tr("remaining"))
			}
		}
		name := fmt.Sprintf("battery-level-%d%s-symbolic", level, state)
		img := iconText(loadIcon(name), fmt.Sprintf("%d%%", pct), 2)
		tip := "<b>" + tr("Computer") + "</b>\n" + text
		powerText.Store(fmt.Sprintf("%s %d%%\n%s", tr("Battery"), pct, text))
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
	cmd := exec.Command("pactl", args...)
	cmd.Env = append(os.Environ(), "LC_ALL=C") // the output is parsed: not "Stumm: ja" on a German machine
	out, _ := cmd.Output()
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
		icon := loadIcon(name)
		if vol > 100 && !muted {
			icon = bulgeIcon(icon, 0.45) // over 100%: the loud icon swells
		}
		volPct.Store(int32(vol))
		if muted {
			volMuted.Store(1)
		} else {
			volMuted.Store(0)
		}
		tip := fmt.Sprintf("%s %d%%", tr("Volume"), vol)
		if muted {
			tip = tr("Volume muted")
		}
		it.post(itemUpdate{img: iconText(icon, "", 0), tip: &tip, w: panelH})
	}
	it.click = func(x, y, btn int) {
		switch btn {
		case 1:
			openVolumePopup(it.x + it.w/2)
		case 3:
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
			cmd.Env = append(os.Environ(), "LC_ALL=C") // matched against "sink" / "source" / "server"
			cmd.SysProcAttr = &syscall.SysProcAttr{Pdeathsig: syscall.SIGKILL}
			out, err := cmd.StdoutPipe()
			if err != nil || cmd.Start() != nil {
				select {
				case <-time.After(5 * time.Second):
					continue
				case <-it.dead:
					return
				}
			}
			trackSubscriber(cmd.Process)
			go func() { <-it.dead; cmd.Process.Kill() }()
			buf := make([]byte, 4096)
			var last time.Time
			for {
				n, err := out.Read(buf)
				if err != nil {
					break
				}
				s := string(buf[:n])
				if strings.Contains(s, "source") || strings.Contains(s, "server") {
					select {
					case popupRefresh <- struct{}{}:
					default:
					}
				}
				if (strings.Contains(s, "sink") || strings.Contains(s, "server")) && time.Since(last) > 100*time.Millisecond {
					last = time.Now()
					refresh()
				}
			}
			cmd.Process.Kill()
			cmd.Wait()
			untrackSubscriber(cmd.Process)
			select {
			case <-time.After(2 * time.Second):
			case <-it.dead:
				return
			}
		}
	}()
	return it
}

// pactl subscribe children must not outlive us: each one is a connection to the sound
// server, and leaked ones (the restart exec keeps our pid, so nothing reaped them) pile up
// and clog it. They are killed before restart/quit, and stale ones are swept at startup.
var (
	subMu   sync.Mutex
	subProc = map[int]*os.Process{}
)

func trackSubscriber(p *os.Process)   { subMu.Lock(); subProc[p.Pid] = p; subMu.Unlock() }
func untrackSubscriber(p *os.Process) { subMu.Lock(); delete(subProc, p.Pid); subMu.Unlock() }

func killSubscribers() {
	subMu.Lock()
	for _, p := range subProc {
		p.Kill()
	}
	subMu.Unlock()
}

// sweepStaleSubscribers kills our own user's `pactl subscribe` processes that are orphans
// (parent init or the systemd user manager) or children of this pid left over from before an exec restart.
func sweepStaleSubscribers() {
	me := os.Getpid()
	ents, _ := os.ReadDir("/proc")
	for _, e := range ents {
		pid, err := strconv.Atoi(e.Name())
		if err != nil || pid == me {
			continue
		}
		cmd, _ := os.ReadFile("/proc/" + e.Name() + "/cmdline")
		if string(cmd) != "pactl\x00subscribe\x00" {
			continue
		}
		st, _ := os.ReadFile("/proc/" + e.Name() + "/stat")
		i := strings.LastIndexByte(string(st), ')')
		f := strings.Fields(string(st[i+1:]))
		if len(f) < 2 {
			continue
		}
		ppid, _ := strconv.Atoi(f[1])
		pcomm, _ := os.ReadFile("/proc/" + f[1] + "/comm") // orphans go to the systemd --user subreaper
		if ppid != 1 && ppid != me && strings.TrimSpace(string(pcomm)) != "systemd" {
			continue
		}
		var fi os.FileInfo
		if fi, err = os.Stat("/proc/" + e.Name()); err != nil {
			continue
		}
		if sys, ok := fi.Sys().(*syscall.Stat_t); ok && int(sys.Uid) == os.Getuid() {
			syscall.Kill(pid, syscall.SIGKILL)
		}
	}
}

// bulgeIcon returns img with a fisheye bulge: the centre is magnified by 1/a (0 < a <= 1)
// and the magnification fades to none at the edge of the box, so the shape swells
// outwards. Each output pixel averages 4x4 bilinear samples of the source.
func bulgeIcon(img *image.RGBA, a float64) *image.RGBA {
	b := img.Bounds()
	w, h := b.Dx(), b.Dy()
	out := image.NewRGBA(b)
	cx, cy := float64(w)/2, float64(h)/2
	at := func(x, y int) (r, g, bl, al float64) {
		if x < 0 || y < 0 || x >= w || y >= h {
			return
		}
		i := img.PixOffset(b.Min.X+x, b.Min.Y+y)
		return float64(img.Pix[i]), float64(img.Pix[i+1]), float64(img.Pix[i+2]), float64(img.Pix[i+3])
	}
	const n = 4
	for y := 0; y < h; y++ {
		for x := 0; x < w; x++ {
			var sr, sg, sb, sa float64
			for j := 0; j < n; j++ {
				for i := 0; i < n; i++ {
					dx := (float64(x) + (float64(i)+0.5)/n - cx) / cx
					dy := (float64(y) + (float64(j)+0.5)/n - cy) / cy
					if r2 := dx*dx + dy*dy; r2 < 1 {
						f := a + (1-a)*r2
						dx, dy = dx*f, dy*f
					}
					px, py := dx*cx+cx-0.5, dy*cy+cy-0.5
					x0, y0 := int(math.Floor(px)), int(math.Floor(py))
					fx, fy := px-float64(x0), py-float64(y0)
					for k, wt := range [4]float64{(1 - fx) * (1 - fy), fx * (1 - fy), (1 - fx) * fy, fx * fy} {
						r, g, bl, al := at(x0+k&1, y0+k>>1)
						sr, sg, sb, sa = sr+r*wt, sg+g*wt, sb+bl*wt, sa+al*wt
					}
				}
			}
			o := out.PixOffset(b.Min.X+x, b.Min.Y+y)
			out.Pix[o], out.Pix[o+1], out.Pix[o+2], out.Pix[o+3] = byte(sr/(n*n)+0.5), byte(sg/(n*n)+0.5), byte(sb/(n*n)+0.5), byte(sa/(n*n)+0.5)
		}
	}
	return out
}
