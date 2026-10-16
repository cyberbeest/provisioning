package main

import (
	"image/color"
	"math"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// An optional slow drift of the panel background through the pastels (Settings > Panel,
// BG_CYCLE= in panel.conf: off | 24h | 1h | 5m | 1m | 10s). The hue follows the wall clock, so it
// is continuous across restarts and the same on every monitor: with 24h it is the time of
// day (local midnight = hue 0), otherwise the Unix time modulo the cycle. Lightness stays
// high so the black text keeps its contrast. Everything that is painted over the background
// (hover, taskbar buttons) is derived from it.

var (
	curBg      uint32        = panelBg
	curHoverBg uint32        = hoverBg
	bgPeriod   time.Duration // 0: the fixed default colour
	bgTick     <-chan time.Time
	bgTicker   *time.Ticker

	tbDefaults = [4]color.RGBA{tbBorder, tbNormal, tbHover, tbActive}
)

func readPanelConf() map[string]string {
	m := map[string]string{}
	home, _ := os.UserHomeDir()
	b, err := os.ReadFile(filepath.Join(home, ".config/cyberbeest/panel.conf"))
	if err != nil {
		return m
	}
	for _, l := range strings.Split(string(b), "\n") {
		if k, v, ok := strings.Cut(strings.TrimSpace(l), "="); ok {
			m[k] = v
		}
	}
	return m
}

func bgPeriodOf(s string) time.Duration {
	switch s {
	case "24h":
		return 24 * time.Hour
	case "1h":
		return time.Hour
	case "5m":
		return 5 * time.Minute
	case "1m":
		return time.Minute
	case "10s":
		return 10 * time.Second
	}
	return 0
}

func hslToRGB(h, s, l float64) uint32 {
	c := (1 - math.Abs(2*l-1)) * s
	hp := math.Mod(h, 360) / 60
	x := c * (1 - math.Abs(math.Mod(hp, 2)-1))
	var r, g, b float64
	switch {
	case hp < 1:
		r, g, b = c, x, 0
	case hp < 2:
		r, g, b = x, c, 0
	case hp < 3:
		r, g, b = 0, c, x
	case hp < 4:
		r, g, b = 0, x, c
	case hp < 5:
		r, g, b = x, 0, c
	default:
		r, g, b = c, 0, x
	}
	m := l - c/2
	to := func(v float64) uint32 { return uint32(math.Round((v + m) * 255)) }
	return to(r)<<16 | to(g)<<8 | to(b)
}

// bgStyle is BG_STYLE= in panel.conf: "" (bold pastels) or "wild" (the lightness swings between
// light and very dark, see pastelAt).
var bgStyle string

// curDark is 0 on a light background and fades up to 1 as the background gets too dark for
// black ink: composite() then draws a white outline around everything and the taskbar
// switches to white text.
var curDark float64

// pastelAt is the background and hover colour for time t in a cycle of the given length.
func pastelAt(t time.Time, period time.Duration) (bg, hover uint32) {
	var phase float64
	if period == 24*time.Hour {
		h, m, s := t.Clock()
		phase = float64(h*3600+m*60+s) / 86400
	} else {
		phase = float64(t.UnixNano()%int64(period)) / float64(period)
	}
	hue := phase * 360
	if bgStyle == "wild" { // three light/dark swings per trip round the colour wheel
		l := 0.52 + 0.40*math.Sin(2*math.Pi*phase*3)
		hl := l + 0.08
		if l > 0.5 {
			hl = l - 0.08
		}
		return hslToRGB(hue, 0.85, l), hslToRGB(hue, 0.85, hl)
	}
	return hslToRGB(hue, 0.80, 0.78), hslToRGB(hue, 0.80, 0.70)
}

func luminance(c uint32) float64 {
	return (0.2126*float64(c>>16&0xff) + 0.7152*float64(c>>8&0xff) + 0.0722*float64(c&0xff)) / 255
}

// tbInk is the taskbar's text colour: black on light backgrounds, white once it is dark.
func tbInk(minimized bool) color.RGBA {
	switch {
	case curDark > 0.5 && minimized:
		return color.RGBA{0xb8, 0xb8, 0xb8, 255}
	case curDark > 0.5:
		return color.RGBA{255, 255, 255, 255}
	case minimized:
		return color.RGBA{0x70, 0x70, 0x70, 255}
	}
	return color.RGBA{0, 0, 0, 255}
}

func scaleRGB(c uint32, f float64) color.RGBA {
	s := func(v uint32) uint8 { return uint8(math.Min(255, math.Round(float64(v)*f))) }
	return color.RGBA{s(c >> 16 & 0xff), s(c >> 8 & 0xff), s(c & 0xff), 255}
}

// applyBgColors makes bg/hover the colours drawing uses, with the taskbar's button colours
// derived from it in the same proportions as the defaults have to the default background.
func applyBgColors(bg, hover uint32, def bool) {
	curBg, curHoverBg = bg, hover
	curDark = 0
	if !def {
		curDark = min(max((0.52-luminance(bg))/0.25, 0), 1)
	}
	if def {
		tbBorder, tbNormal, tbHover, tbActive = tbDefaults[0], tbDefaults[1], tbDefaults[2], tbDefaults[3]
		return
	}
	if curDark > 0 { // darkening a dark colour shows nothing: lighten instead, by the amount the dark theme asks for
		lift := func(t float64) color.RGBA {
			s := func(v uint32) uint8 { return uint8(math.Round(float64(v) + (255-float64(v))*t*curDark)) }
			return color.RGBA{s(bg >> 16 & 0xff), s(bg >> 8 & 0xff), s(bg & 0xff), 255}
		}
		tbBorder, tbNormal, tbHover, tbActive = lift(0.35), lift(0.10), lift(0.20), lift(0.30)
		return
	}
	tbBorder, tbNormal, tbHover, tbActive = scaleRGB(bg, 0.84), scaleRGB(bg, 0.955), scaleRGB(bg, 0.915), scaleRGB(bg, 0.86)
}

// tickFloor is the shortest time between colour steps; the wild style swings faster and needs finer steps.
func tickFloor() time.Duration {
	if bgStyle == "wild" {
		return 250 * time.Millisecond
	}
	return 500 * time.Millisecond
}
