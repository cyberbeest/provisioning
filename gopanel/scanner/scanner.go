// Package scanner is the shared engine for the vertical KITT-style scanners
// (io-scanner, network-scanner; ports of the C plugins of the same names): a short
// LED strip whose sweep speed follows a measured value, rate = factor * value^exponent.
package scanner

import (
	"image"
	"log"
	"math"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"gopanel/proto"
)

const (
	numLEDs         = 6
	ledGapFrac      = 0.22
	glowWidth       = 0.55 // kitt's 2.2 scaled by 6/24: a short bright streak
	glowCutoffSigma = 3.5
	widthFrac       = 0.6
	sampleEvery     = 500 * time.Millisecond
	minRedrawPx     = 1.0
)

// Source supplies the measurement. Sample is called every 500 ms; Value is the smoothed,
// unbounded number that drives the sweep; Tooltip is the hover text.
type Source interface {
	Sample()
	Value() float64
	Tooltip() string
}

type Config struct {
	Name                        string
	LedOn, LedOff               [3]float64
	Factor, Exponent            float64
	MinRate, MaxRate            float64
	FPS                         int
	OffIsBg, SineSweep, Enabled bool
}

// LoadRC overlays settings from ~/.config/xfce4/panel/<name>-*.rc, the file the C plugin used.
func (c *Config) LoadRC() {
	home, _ := os.UserHomeDir()
	m, _ := filepath.Glob(filepath.Join(home, ".config/xfce4/panel", c.Name+"-*.rc"))
	if len(m) == 0 {
		return
	}
	b, err := os.ReadFile(m[0])
	if err != nil {
		return
	}
	log.Println("settings from", m[0])
	for _, ln := range strings.Split(string(b), "\n") {
		k, v, ok := strings.Cut(strings.TrimSpace(ln), "=")
		if !ok {
			continue
		}
		f, _ := strconv.ParseFloat(v, 64)
		switch k {
		case "MinRate":
			c.MinRate = f
		case "MaxRate":
			c.MaxRate = f
		case "Factor":
			c.Factor = f
		case "Exponent":
			c.Exponent = f
		case "FPS":
			c.FPS = min(max(int(f), 1), 60)
		case "OffIsBg":
			c.OffIsBg = v == "true"
		case "SineSweep":
			c.SineSweep = v == "true"
		case "Enabled":
			c.Enabled = v == "true"
		}
	}
}

type layout struct{ barX, barY, barW, barH, pitch, ledH, radius float64 }

func computeLayout(w, h float64) layout {
	l := layout{barH: h * 0.92, barW: h * 0.5}
	l.barX, l.barY = (w-l.barW)/2, (h-l.barH)/2
	l.pitch = l.barH / numLEDs
	l.ledH = l.pitch * (1 - ledGapFrac)
	l.radius = math.Min(l.ledH, l.barW) / 2
	return l
}

func eyePos(phase float64, sine bool) float64 {
	frac := phase
	if phase > 1 {
		frac = 2 - phase
	}
	if sine {
		frac = (1 - math.Cos(frac*math.Pi)) / 2
	}
	return frac * (numLEDs - 1)
}

func rrCoverage(px, py, x, y, w, h, r float64) float64 {
	dx := math.Abs(px-(x+w/2)) - (w/2 - r)
	dy := math.Abs(py-(y+h/2)) - (h/2 - r)
	d := math.Hypot(math.Max(dx, 0), math.Max(dy, 0)) + math.Min(math.Max(dx, dy), 0) - r
	return math.Min(1, math.Max(0, 0.5-d))
}

func (c *Config) render(img *image.RGBA, eye float64) {
	for i := range img.Pix {
		img.Pix[i] = 0
	}
	b := img.Bounds()
	lay := computeLayout(float64(b.Dx()), float64(b.Dy()))
	cutoff := glowWidth * glowCutoffSigma
	for i := 0; i < numLEDs; i++ {
		dist := math.Abs(float64(i) - eye)
		br := 0.0
		if dist <= cutoff {
			br = math.Exp(-(dist * dist) / (2 * glowWidth * glowWidth))
		}
		if br == 0 && c.OffIsBg {
			continue
		}
		col, alpha := c.LedOn, br
		if !c.OffIsBg {
			for k := 0; k < 3; k++ {
				col[k] = c.LedOff[k] + (c.LedOn[k]-c.LedOff[k])*br
			}
			alpha = 1
		}
		y := lay.barY + float64(i)*lay.pitch + (lay.pitch-lay.ledH)/2
		for py := int(math.Floor(y)) - 1; py <= int(math.Ceil(y+lay.ledH)); py++ {
			for px := int(math.Floor(lay.barX)) - 1; px <= int(math.Ceil(lay.barX+lay.barW)); px++ {
				if px < 0 || py < 0 || px >= b.Dx() || py >= b.Dy() {
					continue
				}
				a := alpha * rrCoverage(float64(px)+.5, float64(py)+.5, lay.barX, y, lay.barW, lay.ledH, lay.radius)
				if a <= 0 {
					continue
				}
				o := py*img.Stride + px*4
				img.Pix[o] = byte(col[0]*a*255 + .5) // premultiplied
				img.Pix[o+1] = byte(col[1]*a*255 + .5)
				img.Pix[o+2] = byte(col[2]*a*255 + .5)
				img.Pix[o+3] = byte(a*255 + .5)
			}
		}
	}
}

func run(c Config, src Source, cl *proto.Client) {
	img := image.NewRGBA(image.Rect(0, 0, cl.Width, cl.Height))
	lay := computeLayout(float64(cl.Width), float64(cl.Height))
	phase, paused := 0.0, false
	prevEye := eyePos(0, c.SineSweep)
	if !c.Enabled {
		prevEye = eyePos(0.5, c.SineSweep) // dead centre, like the plugin's off switch
	}
	src.Sample()
	c.render(img, prevEye)
	if cl.SendImage(img) != nil {
		return
	}
	var stopTip chan struct{}
	defer func() {
		if stopTip != nil {
			close(stopTip)
		}
	}()
	tipLoop := func(stop <-chan struct{}) {
		for {
			cl.SetTooltip(src.Tooltip())
			select {
			case <-time.After(3 * time.Second):
			case <-stop:
				return
			}
		}
	}
	if !c.Enabled {
		for ev := range cl.Events {
			if ev == "hover on" && stopTip == nil {
				stopTip = make(chan struct{})
				go tipLoop(stopTip)
			}
		}
		return
	}

	sampleT := time.NewTicker(sampleEvery)
	defer sampleT.Stop()
	frameT := time.NewTicker(time.Second / time.Duration(c.FPS))
	defer frameT.Stop()
	last := time.Now()
	for {
		var frameC <-chan time.Time
		if !paused {
			frameC = frameT.C
		}
		select {
		case ev, ok := <-cl.Events:
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
					go tipLoop(stopTip)
				}
			case "hover off":
				if stopTip != nil {
					close(stopTip)
					stopTip = nil
				}
			}
		case <-sampleT.C:
			if !paused {
				src.Sample()
			}
		case now := <-frameC:
			dt := now.Sub(last).Seconds()
			last = now
			rate := c.MinRate + c.Factor*math.Pow(math.Max(src.Value(), 0), c.Exponent)
			rate = math.Min(math.Max(rate, c.MinRate), c.MaxRate)
			if rate <= 0 {
				continue
			}
			phase = math.Mod(phase+dt*rate, 2)
			eye := eyePos(phase, c.SineSweep)
			if math.Abs(eye-prevEye)*lay.pitch < minRedrawPx {
				continue
			}
			prevEye = eye
			c.render(img, eye)
			if cl.SendImage(img) != nil {
				return
			}
		}
	}
}

// Main connects to the panel and runs until the panel's parent process disappears.
func Main(c Config, src Source) {
	c.LoadRC()
	log.Printf("%s: fps=%d rate=%g..%g factor=%g exp=%g", c.Name, c.FPS, c.MinRate, c.MaxRate, c.Factor, c.Exponent)
	for {
		if !proto.ParentAlive() {
			return
		}
		cl, err := proto.Dial(c.Name, func(h int) int { return int(math.Round(float64(h) * widthFrac)) })
		if err != nil {
			time.Sleep(time.Second)
			continue
		}
		run(c, src, cl)
		cl.Close()
		time.Sleep(time.Second)
	}
}
