// gopanel: a minimal X11 panel in pure Go (no cgo, no toolkit).
// Two jobs: (1) reserve a strip at the screen bottom via _NET_WM_STRUT_PARTIAL
// so the WM keeps other windows out of it, (2) lay out items in it: launcher icons, and frames sent by helper processes.
package main

import (
	"encoding/binary"
	"fmt"
	"image"
	"log"
	"os"
	"os/signal"
	"runtime/debug"
	"syscall"
	"time"

	"github.com/jezek/xgb"
	"github.com/jezek/xgb/dpms"
	"github.com/jezek/xgb/xproto"

	"gopanel/proto"
)

const version = "0.2.0"

const (
	panelH = 56
	slot   = 48
	pad    = 8
	bgCol  = 0x1e1e2e
	hiCol  = 0x45475a
)

var launchers []*launcher

// item is one thing in the panel: a launcher icon or a helper's frame.
type item struct {
	x, w, h int
	l       *launcher
	hc      *helperConn
}

func (it *item) image() *image.RGBA {
	if it.l != nil {
		return it.l.img
	}
	return it.hc.img
}

// vcsRevision returns the git revision Go embedded at build time, if any.
func vcsRevision() string {
	bi, ok := debug.ReadBuildInfo()
	if !ok {
		return ""
	}
	rev, dirty := "", ""
	for _, kv := range bi.Settings {
		switch kv.Key {
		case "vcs.revision":
			rev = kv.Value
			if len(rev) > 7 {
				rev = rev[:7]
			}
		case "vcs.modified":
			if kv.Value == "true" {
				dirty = "-dirty"
			}
		}
	}
	return rev + dirty
}

func atom(c *xgb.Conn, name string) xproto.Atom {
	r, err := xproto.InternAtom(c, false, uint16(len(name)), name).Reply()
	if err != nil {
		log.Fatal(err)
	}
	return r.Atom
}

func u32(v ...uint32) []byte {
	b := make([]byte, 4*len(v))
	for i, x := range v {
		binary.LittleEndian.PutUint32(b[4*i:], x)
	}
	return b
}

func main() {
	if len(os.Args) > 1 && os.Args[1] == "version" {
		fmt.Println("gopanel", version, vcsRevision())
		return
	}
	if len(os.Args) > 1 { // gopanel reload | restart | quit
		ctlClient(os.Args[1])
		return
	}
	sig := make(chan os.Signal, 1) // register first: default SIGHUP action would kill us
	signal.Notify(sig, syscall.SIGHUP)
	launchers = loadPanelLaunchers()
	if len(launchers) == 0 {
		log.Fatal("no launchers found in xfce4-panel config")
	}

	c, err := xgb.NewConn()
	if err != nil {
		log.Fatal(err)
	}
	defer c.Close()
	scr := xproto.Setup(c).DefaultScreen(c)
	w, h := scr.WidthInPixels, scr.HeightInPixels

	wid, _ := xproto.NewWindowId(c)
	xproto.CreateWindow(c, scr.RootDepth, wid, scr.Root,
		0, int16(h-panelH), w, panelH, 0,
		xproto.WindowClassInputOutput, scr.RootVisual,
		xproto.CwBackPixel|xproto.CwEventMask,
		[]uint32{bgCol, xproto.EventMaskExposure | xproto.EventMaskButtonPress |
			xproto.EventMaskPointerMotion | xproto.EventMaskLeaveWindow})

	// Window type DOCK + strut: this is "where the rest of the desktop is".
	xproto.ChangeProperty(c, xproto.PropModeReplace, wid, atom(c, "_NET_WM_WINDOW_TYPE"),
		xproto.AtomAtom, 32, 1, u32(uint32(atom(c, "_NET_WM_WINDOW_TYPE_DOCK"))))
	xproto.ChangeProperty(c, xproto.PropModeReplace, wid, atom(c, "_NET_WM_STRUT_PARTIAL"),
		xproto.AtomCardinal, 32, 12, u32(0, 0, 0, panelH, 0, 0, 0, 0, 0, 0, 0, uint32(w)-1))
	xproto.ChangeProperty(c, xproto.PropModeReplace, wid, atom(c, "_NET_WM_STRUT"),
		xproto.AtomCardinal, 32, 4, u32(0, 0, 0, panelH))
	name := "gopanel"
	xproto.ChangeProperty(c, xproto.PropModeReplace, wid, xproto.AtomWmName,
		xproto.AtomString, 8, uint32(len(name)), []byte(name))

	gc, _ := xproto.NewGcontextId(c)
	xproto.CreateGC(c, gc, xproto.Drawable(wid), 0, nil)
	xproto.MapWindow(c, wid)

	var (
		items   []*item
		helpers []*helperConn
		hover   *item
		paused  bool
	)
	relayout := func() {
		items = items[:0]
		x := pad
		for _, l := range launchers {
			items = append(items, &item{x: x, w: slot, h: slot, l: l})
			x += slot + pad
		}
		for _, hc := range helpers {
			items = append(items, &item{x: x, w: hc.w, h: hc.h, hc: hc})
			x += hc.w + pad
		}
		hover = nil
	}
	relayout()

	// draw composites the item's premultiplied RGBA over the panel (or hover)
	// colour and pushes it to the window, in row chunks to stay under the X
	// request size limit.
	draw := func(it *item) {
		bg := uint32(bgCol)
		if it == hover && it.l != nil {
			bg = hiCol
		}
		br, bgn, bb := uint32(byte(bg>>16)), uint32(byte(bg>>8)), uint32(byte(bg))
		img := it.image()
		buf := make([]byte, it.w*it.h*4)
		for y := 0; y < it.h; y++ {
			src := img.Pix[y*img.Stride : y*img.Stride+it.w*4]
			dst := buf[y*it.w*4:]
			for x := 0; x < it.w; x++ {
				p, o := src[x*4:], x*4
				inv := 255 - uint32(p[3])
				dst[o] = byte(uint32(p[2]) + bb*inv/255)
				dst[o+1] = byte(uint32(p[1]) + bgn*inv/255)
				dst[o+2] = byte(uint32(p[0]) + br*inv/255)
			}
		}
		rows := 200000 / (it.w * 4)
		if rows < 1 {
			rows = 1
		}
		y0 := (panelH - it.h) / 2
		for y := 0; y < it.h; y += rows {
			n := rows
			if y+n > it.h {
				n = it.h - y
			}
			xproto.PutImage(c, xproto.ImageFormatZPixmap, xproto.Drawable(wid), gc,
				uint16(it.w), uint16(n), int16(it.x), int16(y0+y), 0, scr.RootDepth,
				buf[y*it.w*4:(y+n)*it.w*4])
		}
	}
	redrawAll := func() {
		xproto.ClearArea(c, false, wid, 0, 0, 0, 0)
		for _, it := range items {
			draw(it)
		}
	}
	hit := func(x int16) *item {
		for _, it := range items {
			if int(x) >= it.x && int(x) < it.x+it.w {
				return it
			}
		}
		return nil
	}
	setHover := func(it *item) {
		if it == hover {
			return
		}
		old := hover
		hover = it
		if old != nil {
			if old.hc != nil {
				old.hc.send("hover off")
			}
			draw(old)
		}
		if it != nil {
			if it.hc != nil {
				it.hc.send("hover on")
			}
			draw(it)
		}
	}

	cmds := make(chan string, 4)
	ctlServer(cmds)
	watchConfig(cmds)
	defer os.Remove(sockPath())
	hev := make(chan helperEvent, 16)
	helperServer(hev)
	defer os.Remove(proto.SockPath())
	go func() {
		for range sig {
			cmds <- "reload"
		}
	}()

	events := make(chan xgb.Event)
	go func() {
		for {
			ev, err := c.WaitForEvent()
			if ev == nil && err == nil {
				close(events)
				return
			}
			if ev != nil {
				events <- ev
			}
		}
	}()

	// Helpers are told to pause while the display is in standby: nothing to see,
	// and animation would only burn battery. (A locked-but-lit screen is not
	// detected yet; the C plugins also asked the screensaver over D-Bus.)
	dpmsOK := dpms.Init(c) == nil
	tick := time.NewTicker(2 * time.Second)
	defer tick.Stop()
	pauseLine := func() string {
		if paused {
			return "pause"
		}
		return "resume"
	}

	handle := func(ev xgb.Event) {
		switch e := ev.(type) {
		case xproto.ExposeEvent:
			if e.Count == 0 {
				redrawAll()
			}
		case xproto.MotionNotifyEvent:
			setHover(hit(e.EventX))
		case xproto.LeaveNotifyEvent:
			setHover(nil)
		case xproto.ButtonPressEvent:
			it := hit(e.EventX)
			switch {
			case it == nil:
			case it.hc != nil:
				it.hc.send(fmt.Sprintf("click %d %d %d", int(e.EventX)-it.x, int(e.EventY)-(panelH-it.h)/2, e.Detail))
			case e.Detail == 1:
				cmd := it.l.command()
				cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
				if err := cmd.Start(); err != nil {
					log.Println(err)
					return
				}
				go cmd.Wait()
			}
		}
	}

	for {
		select {
		case ev, ok := <-events:
			if !ok {
				return
			}
			handle(ev)
		case he := <-hev:
			switch he.kind {
			case "hello":
				helpers = append(helpers, he.hc)
				he.hc.send(pauseLine())
				relayout()
				redrawAll()
			case "image":
				he.hc.img = he.img
				for _, it := range items {
					if it.hc == he.hc {
						draw(it)
					}
				}
			case "bye":
				for i, hc := range helpers {
					if hc == he.hc {
						helpers = append(helpers[:i], helpers[i+1:]...)
						break
					}
				}
				relayout()
				redrawAll()
			}
		case <-tick.C:
			if !dpmsOK {
				continue
			}
			info, err := dpms.Info(c).Reply()
			if err != nil {
				continue
			}
			if off := info.State && info.PowerLevel != dpms.DPMSModeOn; off != paused {
				paused = off
				for _, hc := range helpers {
					hc.send(pauseLine())
				}
			}
		case cmd := <-cmds:
			switch cmd {
			case "reload": // re-read panel config and .desktop files, redraw
				log.Println("reload")
				if l := loadPanelLaunchers(); len(l) > 0 {
					launchers = l
					relayout()
					redrawAll()
				}
			case "restart": // replace this process with the (possibly rebuilt) binary
				os.Remove(sockPath())
				os.Remove(proto.SockPath())
				exe, _ := os.Executable()
				log.Fatal(syscall.Exec(exe, []string{exe}, os.Environ()))
			case "quit":
				return
			}
		}
	}
}
