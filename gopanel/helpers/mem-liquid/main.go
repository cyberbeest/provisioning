// mem-liquid: a square "tank" that fills like liquid to show RAM use. Port of
// lib/xfce-panel-plugins/mem-liquid.c, rendered per pixel from signed-distance shapes.
package main

import (
	"fmt"
	"image"
	"image/color"
	"log"
	"math"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync/atomic"
	"syscall"
	"time"

	"gopanel/gfx"
	"gopanel/procinfo"
	"gopanel/proto"
)

const (
	memSampleEvery = 2 * time.Second
	levelTimeConst = 1.4
	tankMargin     = 0.10
	tankCorner     = 0.16
	waveAmp        = 0.028
	wave1Freq      = 1.0
	wave2Freq      = 2.3
	wave1Speed     = 0.55
	wave2Speed     = 0.87
	warningLevel   = 0.80
	warnPulseSpeed = 4.2
	colorMidStop   = 0.75
	minFPS, maxFPS = 1, 6
)

var (
	bubbleX      = [6]float64{0.16, 0.34, 0.52, 0.71, 0.86, 0.26}
	bubbleSpeed  = [6]float64{0.055, 0.041, 0.067, 0.048, 0.061, 0.073}
	bubblePhase  = [6]float64{0.05, 0.42, 0.71, 0.18, 0.88, 0.55}
	bubbleRadius = [6]float64{0.020, 0.026, 0.016, 0.022, 0.018, 0.024}
	bubbleWobble = [6]float64{0.31, 0.24, 0.38, 0.27, 0.34, 0.22}

	glassBg     = [3]float64{0.08, 0.10, 0.13}
	glassBorder = [3]float64{0.55, 0.60, 0.65}
	colorLow    = [3]float64{0.20, 0.55, 0.90}
	colorMid    = [3]float64{0.95, 0.75, 0.15}
	colorHigh   = [3]float64{0.90, 0.15, 0.15}
	warnRed     = [3]float64{0.95, 0.10, 0.10}
	warnYellow  = [3]float64{1.0, 0.85, 0.10}
)

type settings struct {
	fps         int
	showPercent bool
	enabled     bool
	countMapped bool
	friendly    bool
	diskWarnPct int
}

func loadSettings() settings {
	s := settings{fps: 6, showPercent: true, enabled: true, countMapped: true, friendly: true, diskWarnPct: 80}
	home, _ := os.UserHomeDir()
	m, _ := filepath.Glob(filepath.Join(home, ".config/xfce4/panel/mem-liquid-*.rc"))
	if len(m) == 0 {
		return s
	}
	b, err := os.ReadFile(m[0])
	if err != nil {
		return s
	}
	log.Println("settings from", m[0])
	for _, ln := range strings.Split(string(b), "\n") {
		k, v, ok := strings.Cut(strings.TrimSpace(ln), "=")
		if !ok {
			continue
		}
		n, _ := strconv.Atoi(v)
		switch k {
		case "FPS":
			s.fps = min(max(n, minFPS), maxFPS)
		case "ShowPercent":
			s.showPercent = v == "true"
		case "Enabled":
			s.enabled = v == "true"
		case "CountMapped":
			s.countMapped = v == "true"
		case "FriendlyNames":
			s.friendly = v == "true"
		case "DiskWarningPercent":
			s.diskWarnPct = min(max(n, 50), 99)
		}
	}
	return s
}

type memInfo struct{ total, avail, free, buffers, cached, mapped, shmem, swapTotal, swapFree uint64 }

func readMemInfo() (memInfo, bool) {
	b, err := os.ReadFile("/proc/meminfo")
	if err != nil {
		return memInfo{}, false
	}
	var mi memInfo
	fields := map[string]*uint64{"MemTotal:": &mi.total, "MemAvailable:": &mi.avail, "MemFree:": &mi.free,
		"Buffers:": &mi.buffers, "Cached:": &mi.cached, "Mapped:": &mi.mapped, "Shmem:": &mi.shmem,
		"SwapTotal:": &mi.swapTotal, "SwapFree:": &mi.swapFree}
	for _, ln := range strings.Split(string(b), "\n") {
		f := strings.Fields(ln)
		if len(f) >= 2 {
			if p, ok := fields[f[0]]; ok {
				*p, _ = strconv.ParseUint(f[1], 10, 64)
			}
		}
	}
	return mi, mi.total > 0 && mi.avail > 0
}

func sub(a, b uint64) uint64 {
	if a > b {
		return a - b
	}
	return 0
}

// usedKiB: default is MemTotal-MemAvailable. With countMapped, resident mmap'd pages
// (e.g. a multi-GB model file read on every pass) count as used, while ordinary
// passive file cache still counts as free headroom; Shmem is live data, not cache.
func usedKiB(mi memInfo, countMapped bool) uint64 {
	if !countMapped {
		return sub(mi.total, mi.avail)
	}
	passive := sub(sub(mi.cached, mi.mapped), mi.shmem)
	return sub(mi.total, mi.free+mi.buffers+passive)
}

type state struct {
	set                      settings
	level, target            float64
	warnLevel, warnTarget    float64
	swapFrac                 float64
	swapTotal, swapUsed      uint64
	memTotal, memUsed        uint64
	diskFrac                 float64
	diskTotal, diskUsed      uint64
	phase1, phase2, animTime float64
}

func (s *state) sample() {
	if mi, ok := readMemInfo(); ok {
		used := usedKiB(mi, s.set.countMapped)
		s.target = math.Min(1, float64(used)/float64(mi.total))
		s.memTotal, s.memUsed = mi.total, used
		s.warnTarget = math.Min(1, float64(usedKiB(mi, false))/float64(mi.total))
		s.swapFrac = 0
		if mi.swapTotal > 0 {
			s.swapFrac = math.Min(1, math.Max(0, 1-float64(mi.swapFree)/float64(mi.swapTotal)))
		}
		s.swapTotal, s.swapUsed = mi.swapTotal, sub(mi.swapTotal, mi.swapFree)
	}
	var st syscall.Statfs_t
	if syscall.Statfs("/", &st) == nil && st.Blocks > 0 {
		total := st.Blocks * uint64(st.Bsize)
		used := sub(total, st.Bavail*uint64(st.Bsize))
		s.diskFrac = math.Min(1, float64(used)/float64(total))
		s.diskTotal, s.diskUsed = total, used
	}
}

func (s *state) warning() bool {
	return s.warnLevel >= warningLevel || s.diskFrac >= float64(s.set.diskWarnPct)/100
}

func levelColor(f float64) [3]float64 {
	var out [3]float64
	if f <= colorMidStop {
		t := f / colorMidStop
		for i := range out {
			out[i] = colorLow[i] + (colorMid[i]-colorLow[i])*t
		}
	} else {
		t := (f - colorMidStop) / (1 - colorMidStop)
		for i := range out {
			out[i] = colorMid[i] + (colorHigh[i]-colorMid[i])*t
		}
	}
	return out
}

func clamp01(v float64) float64 { return math.Min(1, math.Max(0, v)) }

// rrDist is the signed distance (negative inside) to a rounded rectangle.
func rrDist(px, py, x, y, w, h, r float64) float64 {
	dx := math.Abs(px-(x+w/2)) - (w/2 - r)
	dy := math.Abs(py-(y+h/2)) - (h/2 - r)
	return math.Hypot(math.Max(dx, 0), math.Max(dy, 0)) + math.Min(math.Max(dx, dy), 0) - r
}

// px is a premultiplied float pixel.
type px [4]float64

func (p *px) over(rgb [3]float64, a float64) {
	for i := 0; i < 3; i++ {
		p[i] = rgb[i]*a + p[i]*(1-a)
	}
	p[3] = a + p[3]*(1-a)
}

func (s *state) surfaceHeight(xNorm, tankH float64) float64 {
	wave := math.Sin(2*math.Pi*wave1Freq*xNorm+s.phase1) + 0.5*math.Sin(2*math.Pi*wave2Freq*xNorm+s.phase2)
	return s.level*tankH + waveAmp*tankH*(wave/1.5)
}

func (s *state) render(img *image.RGBA) {
	b := img.Bounds()
	w, h := float64(b.Dx()), float64(b.Dy())
	side := math.Min(w, h) * (1 - 2*tankMargin)
	tx, ty := (w-side)/2, (h-side)/2
	tw, th, tr := side, side, side*tankCorner
	col := levelColor(s.level)
	top := [3]float64{math.Min(1, col[0]+.2), math.Min(1, col[1]+.2), math.Min(1, col[2]+.2)}
	bot := [3]float64{col[0] * .7, col[1] * .7, col[2] * .7}
	borderW := math.Max(1, th*0.02)
	rimW := math.Max(1, th*0.01)

	for y := 0; y < b.Dy(); y++ {
		for x := 0; x < b.Dx(); x++ {
			cx, cy := float64(x)+.5, float64(y)+.5
			d := rrDist(cx, cy, tx, ty, tw, th, tr)
			var p px
			if clip := clamp01(0.5 - d); clip > 0 {
				var in px
				in.over(glassBg, 1)
				ySurf := ty + th - s.surfaceHeight(clamp01((cx-tx)/tw), th)
				if lc := clamp01(cy - ySurf + .5); lc > 0 {
					t := clamp01((cy - ty) / th)
					var c [3]float64
					for i := range c {
						c[i] = top[i] + (bot[i]-top[i])*t
					}
					in.over(c, lc)
				}
				in.over([3]float64{1, 1, 1}, 0.35*clamp01(rimW/2+.5-math.Abs(cy-ySurf)))
				for i := 0; i < 6; i++ {
					yFrac := math.Mod(s.animTime*bubbleSpeed[i]+bubblePhase[i], 1)
					bh := yFrac * (s.level * th)
					if bh < 2 {
						continue
					}
					bx := tx + bubbleX[i]*tw + 0.02*tw*math.Sin(s.animTime*bubbleWobble[i]+bubblePhase[i]*7)
					by := ty + th - bh
					fade := math.Min(1, math.Max(0.15, 1-yFrac))
					in.over([3]float64{1, 1, 1}, 0.25*fade*clamp01(0.5-(math.Hypot(cx-bx, cy-by)-bubbleRadius[i]*tw)))
				}
				for i := range p {
					p[i] = in[i] * clip
				}
			}
			p.over(glassBorder, 0.8*clamp01(borderW/2+.5-math.Abs(d)))
			o := y*img.Stride + x*4
			for i := 0; i < 4; i++ {
				img.Pix[o+i] = byte(clamp01(p[i])*255 + .5)
			}
		}
	}

	// Text overlays (percentage badge, warning mark), clipped to the tank.
	layer := image.NewRGBA(b)
	warn := s.warning()
	if s.set.showPercent {
		txt := fmt.Sprintf("%.0f", s.level*100)
		size, vert := th*0.30, 0.5
		if warn {
			size, vert = th*0.16, 0.87
		}
		drawCentered(layer, txt, size, tx+tw/2, ty+th*vert, true, color.RGBA{0, 0, 0, 140}, color.RGBA{235, 235, 235, 235}, 1)
	}
	if warn {
		pulse := 0.5 + 0.5*math.Sin(s.animTime*warnPulseSpeed)
		var m [3]float64
		for i := range m {
			m[i] = warnRed[i] + (warnYellow[i]-warnRed[i])*pulse
		}
		fill := color.RGBA{uint8(m[0] * 255), uint8(m[1] * 255), uint8(m[2] * 255), 255}
		drawCentered(layer, "!", th*0.85, tx+tw/2, ty+th/2, true, color.RGBA{0, 0, 0, 204}, fill, math.Max(1, th*0.035))
	}
	for y := 0; y < b.Dy(); y++ {
		for x := 0; x < b.Dx(); x++ {
			lo := y*layer.Stride + x*4
			if layer.Pix[lo+3] == 0 {
				continue
			}
			clip := clamp01(0.5 - rrDist(float64(x)+.5, float64(y)+.5, tx, ty, tw, th, tr))
			a := float64(layer.Pix[lo+3]) / 255 * clip
			if clip == 0 {
				continue
			}
			o := y*img.Stride + x*4
			for i := 0; i < 3; i++ {
				v := float64(layer.Pix[lo+i])/255*clip + float64(img.Pix[o+i])/255*(1-a)
				img.Pix[o+i] = byte(clamp01(v)*255 + .5)
			}
			img.Pix[o+3] = byte(clamp01(a+float64(img.Pix[o+3])/255*(1-a))*255 + .5)
		}
	}
}

// drawCentered draws bold text centred on (cx,cy) with an outline/shadow colour behind the fill.
func drawCentered(dst *image.RGBA, text string, px float64, cx, cy float64, bold bool, shadow, fill color.RGBA, outline float64) {
	sp := func(c color.RGBA) []gfx.Span { return []gfx.Span{{Text: text, Scale: 1, Bold: bold, Color: c}} }
	m := gfx.Measure(sp(fill), px)
	x, y := int(cx-float64(m.W)/2+.5), int(cy-float64(m.H)/2+.5)
	if outline > 1.5 { // thick outline for the warning mark: ring of offsets
		for _, o := range [][2]int{{-1, -1}, {0, -1}, {1, -1}, {-1, 0}, {1, 0}, {-1, 1}, {0, 1}, {1, 1}} {
			gfx.Draw(dst, x+o[0], y+o[1], sp(shadow), px)
		}
	} else {
		gfx.Draw(dst, x+1, y+1, sp(shadow), px) // soft drop shadow
	}
	gfx.Draw(dst, x, y, sp(fill), px)
}

// unloadable is a program holding memory it gives back under pressure (a speech
// model, say). Programs announce themselves with a file in
// $XDG_RUNTIME_DIR/cyberbeest/unloadable/ holding "<pid>\t<label>\t<baseline KiB>"; the size shown is the pid's
// current RSS minus that baseline (model pages fault in lazily, so a fixed number goes stale).
type unloadable struct {
	label string
	kib   uint64
}

func procRSSKiB(pid int) uint64 {
	data, err := os.ReadFile("/proc/" + strconv.Itoa(pid) + "/status")
	if err != nil {
		return 0
	}
	for _, line := range strings.Split(string(data), "\n") {
		if f := strings.Fields(line); len(f) >= 2 && f[0] == "VmRSS:" {
			v, _ := strconv.ParseUint(f[1], 10, 64)
			return v
		}
	}
	return 0
}

func readUnloadables() []unloadable {
	dir := filepath.Join(os.Getenv("XDG_RUNTIME_DIR"), "cyberbeest", "unloadable")
	ents, err := os.ReadDir(dir)
	if err != nil || os.Getenv("XDG_RUNTIME_DIR") == "" {
		return nil
	}
	var out []unloadable
	for _, e := range ents {
		if strings.HasPrefix(e.Name(), ".") {
			continue
		}
		raw, err := os.ReadFile(filepath.Join(dir, e.Name()))
		if err != nil {
			continue
		}
		f := strings.Split(strings.TrimSpace(string(raw)), "\t")
		if len(f) < 3 {
			continue
		}
		pid, err := strconv.Atoi(f[0])
		if err != nil {
			continue
		}
		if kerr := syscall.Kill(pid, 0); kerr != nil && kerr != syscall.EPERM {
			continue // owner is gone: stale file
		}
		base, _ := strconv.ParseUint(f[2], 10, 64)
		out = append(out, unloadable{f[1], sub(procRSSKiB(pid), base)})
	}
	return out
}

func (s *state) tooltip(top []procinfo.MemProc) string {
	var b strings.Builder
	gib := func(kib uint64) float64 { return float64(kib) / 1048576 }
	fmt.Fprintf(&b, "RAM: %.0f%% used (%.1f / %.1f GiB)", s.target*100, gib(s.memUsed), gib(s.memTotal))
	if s.swapTotal > 0 {
		fmt.Fprintf(&b, "\nSwap: %.0f%% used (%.1f / %.1f GiB)", s.swapFrac*100, gib(s.swapUsed), gib(s.swapTotal))
	}
	if s.diskTotal > 0 {
		fmt.Fprintf(&b, "\nDisk: %.0f%% used (%.1f / %.1f GiB)", s.diskFrac*100, float64(s.diskUsed)/1073741824, float64(s.diskTotal)/1073741824)
	}
	memWarn := s.warnTarget >= warningLevel
	diskWarn := s.diskFrac >= float64(s.set.diskWarnPct)/100
	switch {
	case memWarn && diskWarn:
		b.WriteString("\n⚠ Memory contention and disk space are both tight")
	case memWarn:
		b.WriteString("\n⚠ Memory contention -- consider closing some programs")
	case diskWarn:
		b.WriteString("\n⚠ Disk space low -- consider freeing some up")
	default:
		switch {
		case s.target < 0.10:
			b.WriteString("\n= Idle =")
		case s.target < 0.40:
			b.WriteString("\n= Light load =")
		case s.target < 0.70:
			b.WriteString("\n= Steady =")
		default:
			b.WriteString("\n= Filling up =")
		}
	}
	if len(top) > 0 {
		b.WriteString("\n\nTop RAM:")
		for _, p := range top {
			gb := math.Max(float64(p.PssKiB)/1048576, 0.1)
			pct := 0.0
			if s.memTotal > 0 {
				pct = float64(p.PssKiB) / float64(s.memTotal) * 100
			}
			fmt.Fprintf(&b, "\n%s  %.1f GB (%.0f%%)", p.Name, gb, pct)
		}
	}
	if ul := readUnloadables(); len(ul) > 0 {
		b.WriteString("\n\nCan be freed when RAM runs short:")
		for _, u := range ul {
			if u.kib > 0 {
				fmt.Fprintf(&b, "\n%s  %.1f GB", u.label, math.Max(float64(u.kib)/1048576, 0.1))
			} else {
				fmt.Fprintf(&b, "\n%s", u.label)
			}
		}
	}
	return b.String()
}

var stateForTip atomic.Pointer[state] // snapshot for the tooltip goroutine

func tooltipLoop(c *proto.Client, friendly bool, stop <-chan struct{}) {
	var last []procinfo.MemProc // previous Top RAM list, shown while the fresh scan runs
	for {
		if st := stateForTip.Load(); st != nil {
			c.SetTooltip(st.tooltip(last))
			last = procinfo.TopMem(3, friendly)
			c.SetTooltip(st.tooltip(last))
		}
		select {
		case <-time.After(3 * time.Second):
		case <-stop:
			return
		}
	}
}

func run(c *proto.Client) {
	s := &state{set: loadSettings()}
	img := image.NewRGBA(image.Rect(0, 0, c.Width, c.Height))
	var stopTip chan struct{}
	defer func() {
		if stopTip != nil {
			close(stopTip)
		}
	}()
	publish := func() { cp := *s; stateForTip.Store(&cp) }
	s.sample()
	s.level, s.warnLevel = s.target, s.warnTarget // start full rather than animating up from empty
	publish()
	send := func() bool { s.render(img); return c.SendImage(img) == nil }
	if !send() {
		return
	}

	sampleT := time.NewTicker(memSampleEvery)
	defer sampleT.Stop()
	tickT := time.NewTicker(time.Second / time.Duration(s.set.fps))
	defer tickT.Stop()
	paused, last := false, time.Now()
	for {
		var tickC <-chan time.Time
		if s.set.enabled && !paused {
			tickC = tickT.C
		}
		select {
		case ev, ok := <-c.Events:
			if !ok {
				return
			}
			switch ev {
			case "pause":
				paused = true
			case "resume":
				paused, last = false, time.Now()
			case "hover on":
				if stopTip == nil {
					stopTip = make(chan struct{})
					go tooltipLoop(c, s.set.friendly, stopTip)
				}
			case "hover off":
				if stopTip != nil {
					close(stopTip)
					stopTip = nil
				}
			}
		case <-sampleT.C:
			s.sample()
			if !s.set.enabled { // no animation: the level just follows the reading
				s.level, s.warnLevel = s.target, s.warnTarget
			}
			publish()
			if !paused && !send() {
				return
			}
		case now := <-tickC:
			dt := now.Sub(last).Seconds()
			last = now
			if dt <= 0 || dt > 1 {
				dt = 1 / float64(s.set.fps)
			}
			alpha := 1 - math.Exp(-dt/levelTimeConst)
			s.level += (s.target - s.level) * alpha
			s.warnLevel += (s.warnTarget - s.warnLevel) * alpha
			s.phase1 = math.Mod(s.phase1+dt*wave1Speed, 2*math.Pi)
			s.phase2 = math.Mod(s.phase2+dt*wave2Speed, 2*math.Pi)
			s.animTime += dt
			if !send() {
				return
			}
		}
	}
}

func main() {
	for {
		if !proto.ParentAlive() {
			return
		}
		c, err := proto.Dial("mem-liquid", func(h int) int { return h })
		if err != nil {
			time.Sleep(time.Second)
			continue
		}
		log.Printf("connected %dx%d", c.Width, c.Height)
		run(c)
		c.Close()
		time.Sleep(time.Second)
	}
}
