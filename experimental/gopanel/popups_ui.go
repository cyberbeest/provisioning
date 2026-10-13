package main

import (
	"fmt"
	"github.com/godbus/dbus/v5"
	"github.com/jezek/xgb/xproto"
	"image"
	"image/color"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

// ---- calendar (clock click) -----------------------------------------------------------

func openCalendar(anchorX int) {
	const cw, ch, titleH, headH, pad = 32, 26, 30, 22, 8
	w, h := 7*cw+2*pad, titleH+headH+6*ch+pad
	cur := func() time.Time {
		n := time.Now()
		return time.Date(n.Year(), n.Month(), 1, 0, 0, 0, 0, time.Local)
	}
	shown := cur()
	p := &popup{w: w, h: h}
	p.paint = func(img *image.RGBA) {
		title := monthTitle(shown)
		textAt(img, (w-textW(title))/2, 6, title, menuInk, true, labelPx, 0)
		textAt(img, pad+8, 6, "‹", menuInk, true, labelPx+3, 0)
		textAt(img, w-pad-18, 6, "›", menuInk, true, labelPx+3, 0)
		for i := 0; i < 7; i++ {
			d := weekdayShort(time.Weekday((i + 1) % 7))
			textAt(img, pad+i*cw+(cw-textW(d))/2, titleH+3, d, menuDimInk, false, labelPx, 0)
		}
		off := (int(shown.Weekday()) + 6) % 7 // Monday first
		today := time.Now()
		for i := 0; i < 42; i++ {
			day := shown.AddDate(0, 0, i-off)
			x, y := pad+(i%7)*cw, titleH+headH+(i/7)*ch
			ink := menuInk
			if day.Month() != shown.Month() {
				ink = menuDimInk
			}
			if day.Year() == today.Year() && day.YearDay() == today.YearDay() {
				fillRect(img, image.Rect(x+2, y+1, x+cw-2, y+ch-1), menuHilite)
				ink = menuWhite
			}
			s := fmt.Sprint(day.Day())
			textAt(img, x+(cw-textW(s))/2, y+(ch-int(labelPx))/2-2, s, ink, false, labelPx, 0)
		}
	}
	step := func(n int) { shown = shown.AddDate(0, n, 0); p.repaint() }
	p.press = func(x, y, btn int) {
		switch {
		case btn == 4:
			step(-1)
		case btn == 5:
			step(1)
		case btn == 1 && y < titleH && x < 48:
			step(-1)
		case btn == 1 && y < titleH && x > w-48:
			step(1)
		case btn == 1 && y < titleH:
			shown = cur()
			p.repaint()
		}
	}
	p.key = func(code xproto.Keycode) {
		switch code {
		case 113, 112: // Left, Page Up
			step(-1)
		case 114, 117: // Right, Page Down
			step(1)
		}
	}
	openPopup(p, anchorX)
}

// ---- volume slider (volume button click) -------------------------------------------

var volPct, volMuted atomic.Int32 // kept up to date by the volume item

func openVolumePopup(anchorX int) {
	const w, h, pad, trackY = 240, 118, 16, 48
	p := &popup{w: w, h: h}
	last := -1
	set := func(x int) {
		v := min(max((x-pad)*100/(w-2*pad), 0), 100)
		volPct.Store(int32(v))
		p.repaint()
		if v != last {
			last = v
			go exec.Command("pactl", "set-sink-volume", "@DEFAULT_SINK@", fmt.Sprintf("%d%%", v)).Run()
		}
	}
	row := func(i int) (int, int) { return 74 + i*20, 74 + i*20 + 20 } // text rows below the slider
	p.paint = func(img *image.RGBA) {
		v := int(volPct.Load())
		textAt(img, pad, 10, tr("Volume"), menuInk, true, labelPx, 0)
		pct := fmt.Sprintf("%d%%", v)
		textAt(img, w-pad-textW(pct), 10, pct, menuInk, false, labelPx, 0)
		drawSlider(img, pad, w-pad, trackY, v)
		mark := "☐"
		if volMuted.Load() != 0 {
			mark = "☑"
		}
		y0, _ := row(0)
		textAt(img, pad, y0, mark+"  "+tr("Mute"), menuInk, false, labelPx, 0)
		y1, _ := row(1)
		textAt(img, pad, y1, tr("Audio Mixer…"), menuInk, false, labelPx, 0)
	}
	dragging := false
	p.press = func(x, y, btn int) {
		switch {
		case btn == 4:
			set(int(volPct.Load())*(w-2*pad)/100 + pad + 5*(w-2*pad)/100)
		case btn == 5:
			set(int(volPct.Load())*(w-2*pad)/100 + pad - 5*(w-2*pad)/100)
		case btn != 1:
		case y >= trackY-10 && y <= trackY+16:
			dragging = true
			set(x)
		default:
			if y0, y1 := row(0); y >= y0 && y < y1 {
				volMuted.Store(1 - volMuted.Load())
				p.repaint()
				go exec.Command("pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle").Run()
			} else if y0, y1 = row(1); y >= y0 && y < y1 {
				closePopup()
				if _, err := exec.LookPath("pavucontrol"); err == nil {
					run(exec.Command("pavucontrol"))
				}
			}
		}
	}
	p.motion = func(x, y int, held bool) {
		if dragging && held {
			set(x)
		}
	}
	p.release = func() { dragging = false }
	p.key = func(code xproto.Keycode) {
		switch code {
		case 113, 116: // Left, Down
			set(int(volPct.Load())*(w-2*pad)/100 + pad - 5*(w-2*pad)/100)
		case 114, 111: // Right, Up
			set(int(volPct.Load())*(w-2*pad)/100 + pad + 5*(w-2*pad)/100)
		}
	}
	openPopup(p, anchorX)
}

// ---- power popup (battery button click) --------------------------------------------------

var powerText atomic.Value // string: "Battery 82%\nDischarging, 2:56 remaining"

func backlightPath() string {
	if m, _ := filepath.Glob("/sys/class/backlight/*"); len(m) > 0 {
		return m[0]
	}
	return ""
}

// brightness returns the backlight level as a percentage, or -1 without a backlight.
func brightness() int {
	d := backlightPath()
	if d == "" {
		return -1
	}
	if mx := sysfsInt(d + "/max_brightness"); mx > 0 {
		return sysfsInt(d+"/brightness") * 100 / mx
	}
	return -1
}

var logind struct {
	sync.Mutex
	conn *dbus.Conn
}

// setBrightness asks logind (no root needed for the session's own backlight); pct is clamped to 5..100.
func setBrightness(pct int) {
	d := backlightPath()
	if d == "" {
		return
	}
	pct = min(max(pct, 5), 100)
	val := uint32(sysfsInt(d+"/max_brightness") * pct / 100)
	logind.Lock()
	defer logind.Unlock()
	if logind.conn == nil {
		c, err := dbus.ConnectSystemBus()
		if err != nil {
			return
		}
		logind.conn = c
	}
	logind.conn.Object("org.freedesktop.login1", "/org/freedesktop/login1/session/auto").
		Call("org.freedesktop.login1.Session.SetBrightness", 0, "backlight", filepath.Base(d), val)
}

func stepBrightness(delta int) {
	if b := brightness(); b >= 0 {
		setBrightness(b + delta)
	}
}

func openPowerPopup(anchorX int) {
	const w, pad, trackY = 260, 16, 94
	text, _ := powerText.Load().(string)
	lines := strings.Split(text, "\n")
	bright := brightness()
	h := 142
	if bright < 0 {
		h = 100
	}
	p := &popup{w: w, h: h}
	last := bright
	set := func(x int) {
		v := min(max((x-pad)*100/(w-2*pad), 5), 100)
		bright = v
		p.repaint()
		if v != last {
			last = v
			go setBrightness(v)
		}
	}
	rows := func() (int, int) { return h - 46, h - 26 }
	p.paint = func(img *image.RGBA) {
		for i, l := range lines {
			textAt(img, pad, 10+i*20, l, menuInk, i == 0, labelPx, 0)
		}
		if bright >= 0 {
			textAt(img, pad, 58, tr("Display brightness"), menuInk, false, labelPx, 0)
			pct := fmt.Sprintf("%d%%", bright)
			textAt(img, w-pad-textW(pct), 58, pct, menuInk, false, labelPx, 0)
			drawSlider(img, pad, w-pad, trackY-12, bright)
		}
		y0, _ := rows()
		textAt(img, pad, y0, tr("Power Manager Settings…"), menuInk, false, labelPx, 0)
		textAt(img, pad, y0+20, tr("Extended power options…"), menuInk, false, labelPx, 0)
	}
	dragging := false
	p.press = func(x, y, btn int) {
		switch {
		case btn == 4 && bright >= 0:
			set(pad + (bright+5)*(w-2*pad)/100)
		case btn == 5 && bright >= 0:
			set(pad + (bright-5)*(w-2*pad)/100)
		case btn != 1:
		case bright >= 0 && y >= trackY-24 && y <= trackY+4:
			dragging = true
			set(x)
		default:
			y0, _ := rows()
			switch {
			case y >= y0 && y < y0+20:
				closePopup()
				run(exec.Command("xfce4-power-manager-settings"))
			case y >= y0+20 && y < y0+40:
				closePopup()
				run(exec.Command(os.ExpandEnv("$HOME/.local/bin/cyberbeest-settings.py"), "--tab=power"))
			}
		}
	}
	p.motion = func(x, y int, held bool) {
		if dragging && held {
			set(x)
		}
	}
	p.release = func() { dragging = false }
	openPopup(p, anchorX)
}

// drawSlider paints a horizontal slider (track y..y+6, handle around it) between x0 and x1.
func drawSlider(img *image.RGBA, x0, x1, y, pct int) {
	fillRect(img, image.Rect(x0, y, x1, y+6), color.RGBA{0xd8, 0xd6, 0xd2, 255})
	fx := x0 + pct*(x1-x0)/100
	fillRect(img, image.Rect(x0, y, fx, y+6), menuHilite)
	fillRect(img, image.Rect(fx-5, y-6, fx+5, y+12), color.RGBA{0xf6, 0xf5, 0xf4, 255})
	fillRect(img, image.Rect(fx-5, y-6, fx+5, y-5), menuBorder)
	fillRect(img, image.Rect(fx-5, y+11, fx+5, y+12), menuBorder)
	fillRect(img, image.Rect(fx-5, y-6, fx-4, y+12), menuBorder)
	fillRect(img, image.Rect(fx+4, y-6, fx+5, y+12), menuBorder)
}
