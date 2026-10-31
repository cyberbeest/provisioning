// kitt: Knight Rider LED sweep for gopanel, driven by CPU load. Port of
// lib/xfce-panel-plugins/kitt-scanner.c. Draws into an in-memory image and
// ships it to the panel over the helper socket; it never touches X.
package main

import (
	"bufio"
	"flag"
	"fmt"
	"image"
	"log"
	"math"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync/atomic"
	"time"

	"gopanel/procinfo"
	"gopanel/proto"
)

const (
	aspectRatio     = 4  // width = panel height * aspectRatio
	refLEDs         = 24 // LED count at the automatic width; other widths keep the LED size
	ledGapFrac      = 0.22
	glowWidth       = 2.2
	glowCutoffSigma = 3.5
	loadSampleEvery = 500 * time.Millisecond
	loadSmoothing   = 0.35
	idleLoad        = 0.12 // below this the scanner rests: the panel's own redraws would otherwise keep it moving
	minRedrawPx     = 1.0
)

var (
	ledOn  = [3]float64{1.0, 0.05, 0.0}
	ledOff = [3]float64{0.12, 0.0, 0.0} // housing colour, only with -housing
)

// cfg mirrors the settings of the C plugin. Defaults match kitt-scanner.c; they are
// overridden by the existing xfce rc file (if any), then by command-line flags.
var cfg = struct {
	fps              int
	minRate, maxRate float64
	gamma            float64
	linear, housing  bool
	disabled         bool // freeze at dead centre, no animation
	width            int  // slot width in px; 0 = panel height * aspectRatio
	rcPath           string
}{fps: 40, maxRate: 2.86, gamma: 1.0}

// loadXfceRC reads the first ~/.config/xfce4/panel/kitt-scanner-*.rc, so the helper
// behaves like the plugin the user already configured. Keys it doesn't know are ignored.
func loadXfceRC(path string) {
	if path == "" {
		home, _ := os.UserHomeDir()
		m, _ := filepath.Glob(filepath.Join(home, ".config/xfce4/panel/kitt-scanner-*.rc"))
		if len(m) == 0 {
			return
		}
		path = m[0]
	}
	f, err := os.Open(path)
	if err != nil {
		return
	}
	defer f.Close()
	cfg.rcPath = path
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		k, v, ok := strings.Cut(strings.TrimSpace(sc.Text()), "=")
		if !ok {
			continue
		}
		fl, _ := strconv.ParseFloat(v, 64)
		switch k {
		case "MinRate":
			cfg.minRate = fl
		case "MaxRate":
			cfg.maxRate = fl
		case "Gamma":
			cfg.gamma = fl
		case "FPS":
			cfg.fps = int(fl)
		case "OffIsBg":
			cfg.housing = v != "true"
		case "SineSweep":
			cfg.linear = v != "true"
		case "Width":
			cfg.width = int(fl)
		case "Enabled":
			cfg.disabled = v != "true"
		}
	}
	log.Println("settings from", path)
}

type layout struct {
	barX, barY, barW, barH, pitch, ledW, radius float64
	n                                           int
}

// persistWidth writes the automatic width into the rc file as Width=, so the
// Properties dialog shows the real number. The panel restarts us on the change,
// and the next start finds Width set, so this happens once.
func persistWidth(w int) {
	if cfg.width > 0 || cfg.rcPath == "" {
		return
	}
	b, err := os.ReadFile(cfg.rcPath)
	if err != nil {
		return
	}
	var out []string
	for _, l := range strings.Split(strings.TrimRight(string(b), "\n"), "\n") {
		if !strings.HasPrefix(strings.TrimSpace(l), "Width=") {
			out = append(out, l)
		}
	}
	out = append(out, fmt.Sprintf("Width=%d", w))
	os.WriteFile(cfg.rcPath, []byte(strings.Join(out, "\n")+"\n"), 0o644)
}

func computeLayout(w, h float64) layout {
	l := layout{barW: w * 0.92, barH: h * 0.5}
	l.barX, l.barY = (w-l.barW)/2, (h-l.barH)/2
	// LED size is fixed by the panel height (as at the automatic width); the width only
	// decides how many fit.
	refPitch := h * aspectRatio * 0.92 / refLEDs
	l.n = max(2, int(math.Round(l.barW/refPitch)))
	l.pitch = l.barW / float64(l.n)
	l.ledW = l.pitch * (1 - ledGapFrac)
	l.radius = math.Min(l.ledW, l.barH) / 2
	return l
}

func eyePos(phase float64, linear bool, n int) float64 {
	frac := phase
	if phase > 1 {
		frac = 2 - phase
	}
	if !linear {
		frac = (1 - math.Cos(frac*math.Pi)) / 2
	}
	return frac * float64(n-1)
}

// cpuSampler reads /proc/stat and keeps an exponentially smoothed 0..1 load.
type cpuSampler struct {
	prevIdle, prevTotal uint64
	load                float64
}

func (s *cpuSampler) sample() {
	f, err := os.Open("/proc/stat")
	if err != nil {
		return
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	if !sc.Scan() {
		return
	}
	fields := strings.Fields(sc.Text())
	if len(fields) < 9 || fields[0] != "cpu" {
		return
	}
	var v [8]uint64
	var total uint64
	for i := 0; i < 8; i++ {
		for _, ch := range fields[i+1] {
			v[i] = v[i]*10 + uint64(ch-'0')
		}
		total += v[i]
	}
	idle := v[3] + v[4] // idle + iowait
	dIdle, dTotal := idle-s.prevIdle, total-s.prevTotal
	first := s.prevTotal == 0
	s.prevIdle, s.prevTotal = idle, total
	if first || dTotal == 0 {
		return
	}
	instant := math.Min(1, math.Max(0, 1-float64(dIdle)/float64(dTotal)))
	s.load += (instant - s.load) * loadSmoothing
}

// roundedRectCoverage is the anti-aliased coverage of pixel (px,py) by a
// rounded rectangle, from its signed distance field.
func roundedRectCoverage(px, py, x, y, w, h, r float64) float64 {
	cx, cy := x+w/2, y+h/2
	dx := math.Abs(px-cx) - (w/2 - r)
	dy := math.Abs(py-cy) - (h/2 - r)
	d := math.Hypot(math.Max(dx, 0), math.Max(dy, 0)) + math.Min(math.Max(dx, dy), 0) - r
	return math.Min(1, math.Max(0, 0.5-d))
}

func render(img *image.RGBA, eye float64) {
	for i := range img.Pix {
		img.Pix[i] = 0
	}
	b := img.Bounds()
	lay := computeLayout(float64(b.Dx()), float64(b.Dy()))
	cutoff := glowWidth * glowCutoffSigma
	for i := 0; i < lay.n; i++ {
		dist := math.Abs(float64(i) - eye)
		brightness := 0.0
		if dist <= cutoff {
			brightness = math.Exp(-(dist * dist) / (2 * glowWidth * glowWidth))
		}
		if brightness == 0 && !cfg.housing {
			continue
		}
		var col [3]float64
		var alpha float64
		if cfg.housing {
			for k := 0; k < 3; k++ {
				col[k] = ledOff[k] + (ledOn[k]-ledOff[k])*brightness
			}
			alpha = 1
		} else {
			col, alpha = ledOn, brightness
		}
		x := lay.barX + float64(i)*lay.pitch + (lay.pitch-lay.ledW)/2
		for py := int(math.Floor(lay.barY)) - 1; py <= int(math.Ceil(lay.barY+lay.barH)); py++ {
			for px := int(math.Floor(x)) - 1; px <= int(math.Ceil(x+lay.ledW)); px++ {
				if px < 0 || py < 0 || px >= b.Dx() || py >= b.Dy() {
					continue
				}
				a := alpha * roundedRectCoverage(float64(px)+0.5, float64(py)+0.5, x, lay.barY, lay.ledW, lay.barH, lay.radius)
				if a <= 0 {
					continue
				}
				o := py*img.Stride + px*4
				img.Pix[o] = byte(col[0]*a*255 + 0.5) // premultiplied
				img.Pix[o+1] = byte(col[1]*a*255 + 0.5)
				img.Pix[o+2] = byte(col[2]*a*255 + 0.5)
				img.Pix[o+3] = byte(a*255 + 0.5)
			}
		}
	}
}

func cpuStatus(load float64) string {
	switch {
	case load < 0.10:
		return "= Idle ="
	case load < 0.40:
		return "= Light load ="
	case load < 0.70:
		return "= Thinking hard ="
	case load < 0.90:
		return "= Working hard ="
	}
	return "= Maxed out ="
}

var loadBits atomic.Uint64 // smoothed load, shared with the tooltip goroutine

// tooltipLoop keeps the tooltip current while the pointer is over the slot. The
// per-process scan only runs from here, i.e. only while someone is looking.
func tooltipLoop(c *proto.Client, stop <-chan struct{}) {
	for {
		load := math.Float64frombits(loadBits.Load())
		base := fmt.Sprintf("CPU load: %.0f%%\n%s", load*100, cpuStatus(load))
		// One SetTooltip per cycle: setting the bare load text first and the
		// process list after the (slow) scan made the tooltip flicker.
		top := procinfo.TopCPU(3, true)
		if len(top) > 0 {
			var b strings.Builder
			b.WriteString(base + "\n\nTop CPU:")
			for _, p := range top {
				fmt.Fprintf(&b, "\n%s  %.0f%%", p.Name, p.Percent)
			}
			base = b.String()
		}
		c.SetTooltip(base)
		select {
		case <-time.After(3 * time.Second):
		case <-stop:
			return
		}
	}
}

func run(c *proto.Client) {
	var stopTip chan struct{}
	defer func() {
		if stopTip != nil {
			close(stopTip)
		}
	}()
	img := image.NewRGBA(image.Rect(0, 0, c.Width, c.Height))
	lay := computeLayout(float64(c.Width), float64(c.Height))
	var (
		cpu     cpuSampler
		phase   float64
		prevEye = eyePos(0, cfg.linear, lay.n)
		paused  bool
		last    = time.Now()
	)
	cpu.sample()
	if cfg.disabled {
		prevEye = eyePos(0.5, cfg.linear, lay.n) // dead centre, like the plugin's off switch
	}
	render(img, prevEye)
	if c.SendImage(img) != nil {
		return
	}

	if cfg.disabled {
		for range c.Events { // static frame; just wait for the panel to go away
		}
		return
	}

	sampleT := time.NewTicker(loadSampleEvery)
	defer sampleT.Stop()
	frameT := time.NewTicker(time.Second / time.Duration(min(max(cfg.fps, 1), 60)))
	defer frameT.Stop()

	for {
		var frameC <-chan time.Time
		if !paused {
			frameC = frameT.C
		}
		select {
		case ev, ok := <-c.Events:
			if !ok {
				return
			}
			switch ev {
			case "hover on":
				if stopTip == nil {
					stopTip = make(chan struct{})
					go tooltipLoop(c, stopTip)
				}
			case "hover off":
				if stopTip != nil {
					close(stopTip)
					stopTip = nil
				}
			case "pause":
				paused = true
			case "resume":
				paused = false
				last = time.Now()
			}
		case <-sampleT.C:
			if !paused {
				cpu.sample()
				loadBits.Store(math.Float64bits(cpu.load))
			}
		case now := <-frameC:
			dt := now.Sub(last).Seconds()
			last = now
			rate := cfg.minRate + (cfg.maxRate-cfg.minRate)*math.Pow(max(cpu.load-idleLoad, 0)/(1-idleLoad), cfg.gamma)
			if rate <= 0 {
				continue
			}
			// Always accumulate phase, so slow drift batches up until it crosses a pixel.
			phase = math.Mod(phase+dt*rate, 2)
			eye := eyePos(phase, cfg.linear, lay.n)
			if math.Abs(eye-prevEye)*lay.pitch < minRedrawPx {
				continue
			}
			prevEye = eye
			render(img, eye)
			if c.SendImage(img) != nil {
				return
			}
		}
	}
}

func main() {
	rc := flag.String("rc", "", "xfce plugin rc file to read settings from (default: first kitt-scanner-*.rc)")
	flag.IntVar(&cfg.width, "width", cfg.width, "slot width in pixels (default: 4x panel height)")
	flag.IntVar(&cfg.fps, "fps", cfg.fps, "frames per second (1-60)")
	flag.Float64Var(&cfg.minRate, "min-rate", cfg.minRate, "sweeps/sec at 0% CPU load")
	flag.Float64Var(&cfg.maxRate, "max-rate", cfg.maxRate, "sweeps/sec at 100% CPU load")
	flag.Float64Var(&cfg.gamma, "gamma", cfg.gamma, "load exponent: >1 suppresses low load, <1 boosts it")
	flag.BoolVar(&cfg.linear, "linear", cfg.linear, "constant-speed sweep instead of easing at the ends")
	flag.BoolVar(&cfg.housing, "housing", cfg.housing, "opaque dim-red housing behind unlit LEDs")
	// The rc file is read before flags are parsed so explicit flags win.
	for i, a := range os.Args {
		if a == "-rc" || a == "--rc" {
			if i+1 < len(os.Args) {
				*rc = os.Args[i+1]
			}
		}
	}
	loadXfceRC(*rc)
	flag.Parse()
	for {
		if !proto.ParentAlive() {
			return // the panel that started us is gone
		}
		c, err := proto.Dial("kitt", func(h int) int {
			if cfg.width > 0 {
				return cfg.width
			}
			return h * aspectRatio
		})
		if err != nil {
			time.Sleep(time.Second) // panel not up yet (or restarting): keep trying
			continue
		}
		log.Printf("connected %dx%d fps=%d rate=%g..%g gamma=%g linear=%v housing=%v disabled=%v", c.Width, c.Height, cfg.fps, cfg.minRate, cfg.maxRate, cfg.gamma, cfg.linear, cfg.housing, cfg.disabled)
		persistWidth(c.Width)
		run(c)
		c.Close()
		time.Sleep(time.Second)
	}
}
