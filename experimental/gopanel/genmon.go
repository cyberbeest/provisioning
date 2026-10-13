package main

import (
	"context"
	"image"
	"image/color"
	"image/draw"
	_ "image/png"
	"os"
	"os/exec"
	"regexp"
	"strings"
	"sync"
	"syscall"
	"time"

	xdraw "golang.org/x/image/draw"
	"gopanel/gfx"
)

var tagRe = regexp.MustCompile(`(?s)<(img|txt|tool|click|txtclick|bar|imgclick)>(.*?)</(?:img|txt|tool|click|txtclick|bar|imgclick)>`)

// run starts a command detached from the panel (own session, reaped in the background).
func run(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	if err := cmd.Start(); err != nil {
		return
	}
	go cmd.Wait()
}

func shell(line string) *exec.Cmd { return exec.Command("sh", "-c", line) }

// loadPNG decodes an image file, scaled down (never up) to at most maxH tall.
func loadPNG(path string, maxH int) *image.RGBA {
	f, err := os.Open(path)
	if err != nil {
		return nil
	}
	defer f.Close()
	src, _, err := image.Decode(f)
	if err != nil {
		return nil
	}
	b := src.Bounds()
	w, h := b.Dx(), b.Dy()
	if h > maxH {
		w, h = w*maxH/h, maxH
	}
	dst := image.NewRGBA(image.Rect(0, 0, w, h))
	if w == b.Dx() && h == b.Dy() {
		draw.Draw(dst, dst.Bounds(), src, b.Min, draw.Over)
	} else {
		xdraw.CatmullRom.Scale(dst, dst.Bounds(), src, b, draw.Over, nil)
	}
	return dst
}

// newGenmonItem runs an xfce genmon command periodically. Output tags handled:
// <img> <txt> <tool> <click> <txtclick>. The command runs in this goroutine, so
// a slow script only delays its own item.
func newGenmonItem(command string, periodMs int) *item {
	it := newItem("genmon")
	it.hl = true
	stack := isStacked(command)
	if periodMs < 250 {
		periodMs = 30000
	}
	ink := color.RGBA{0, 0, 0, 255}
	const gap, edge = 3, 4
	type zone struct {
		imgW   int
		imgCmd string
		txtCmd string
	}
	var (
		zmu sync.Mutex
		cur zone
	)
	it.click = func(x, y, btn int) {
		if btn != 1 {
			return
		}
		zmu.Lock()
		z := cur
		zmu.Unlock()
		cmd := z.txtCmd
		if x < z.imgW+edge {
			cmd = z.imgCmd
		}
		if cmd == "" { // only one handler defined: it applies everywhere
			cmd = z.imgCmd + z.txtCmd
		}
		if cmd != "" {
			run(shell(cmd))
		}
	}

	refresh := func() {
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		out, err := exec.CommandContext(ctx, "sh", "-c", command).Output()
		if err != nil && len(out) == 0 {
			return
		}
		var iconPath, txt, tip, imgClick, txtClick string
		for _, m := range tagRe.FindAllStringSubmatch(string(out), -1) {
			v := strings.TrimSpace(m[2])
			switch m[1] {
			case "img":
				iconPath = v
			case "txt":
				txt = m[2]
			case "tool":
				tip = m[2]
			case "click", "imgclick":
				imgClick = v
			case "txtclick":
				txtClick = v
			}
		}
		var icon *image.RGBA
		if iconPath != "" {
			icon = loadPNG(iconPath, panelH-4)
		}
		spans := gfx.ParseMarkup(txt, ink)
		px := 13.0
		var tm gfx.Metrics
		var stackedImg *image.RGBA
		if stack {
			stackedImg = renderStacked(txt)
		}
		if stackedImg != nil {
			tm = gfx.Metrics{W: stackedImg.Bounds().Dx(), H: stackedImg.Bounds().Dy()}
		} else if strings.TrimSpace(txt) != "" {
			tm = gfx.Measure(spans, px)
		}
		iw, ih := 0, 0
		if icon != nil {
			iw, ih = icon.Bounds().Dx(), icon.Bounds().Dy()
		}
		w := iw + tm.W
		if iw > 0 && tm.W > 0 {
			w += gap
		}
		h := max(ih, tm.H, 1)
		img := image.NewRGBA(image.Rect(0, 0, max(w, 1), h))
		if icon != nil {
			draw.Draw(img, image.Rect(0, (h-ih)/2, iw, (h-ih)/2+ih), icon, image.Point{}, draw.Over)
		}
		if tm.W > 0 {
			x := iw
			if iw > 0 {
				x += gap
			}
			if stackedImg != nil {
				draw.Draw(img, image.Rect(x, (h-tm.H)/2, x+tm.W, (h-tm.H)/2+tm.H), stackedImg, image.Point{}, draw.Over)
			} else {
				gfx.Draw(img, x, (h-tm.H)/2, spans, px)
			}
		}
		zmu.Lock()
		cur = zone{imgW: iw, imgCmd: imgClick, txtCmd: txtClick}
		zmu.Unlock()
		if w == 0 {
			it.post(itemUpdate{img: img, tip: &tip, w: 0})
			return
		}
		it.post(itemUpdate{img: img, tip: &tip, w: w + 2*edge})
	}

	go func() {
		for {
			refresh()
			select {
			case <-time.After(time.Duration(periodMs) * time.Millisecond):
			case <-it.dead:
				return
			}
		}
	}()
	return it
}
