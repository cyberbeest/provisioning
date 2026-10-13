// gopanel: a minimal X11 panel in pure Go (no cgo, no toolkit).
// Two jobs: (1) reserve a strip at the screen bottom via _NET_WM_STRUT_PARTIAL
// so the WM keeps other windows out of it, (2) draw launcher icons in it.
package main

import (
	"encoding/binary"
	"fmt"
	"log"
	"os"
	"os/signal"
	"runtime/debug"
	"syscall"

	"github.com/jezek/xgb"
	"github.com/jezek/xgb/xproto"
)

const version = "0.1.0"

const (
	panelH = 56
	slot   = 48
	pad    = 8
	bgCol  = 0x1e1e2e
	hiCol  = 0x45475a
)

var launchers []*launcher

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

func slotX(i int) int { return pad + i*(slot+pad) }

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

	hover := -1
	draw := func(i int) {
		bg := uint32(bgCol)
		if i == hover {
			bg = hiCol
		}
		br, bgn, bb := byte(bg>>16), byte(bg>>8), byte(bg)
		buf := make([]byte, slot*slot*4)
		b := launchers[i].img.Bounds()
		for y := 0; y < slot; y++ {
			for x := 0; x < slot; x++ {
				r, g, bl, a := launchers[i].img.At(b.Min.X+x, b.Min.Y+y).RGBA() // premultiplied, 16-bit
				o := (y*slot + x) * 4
				inv := 0xffff - a
				buf[o] = byte((bl + uint32(bb)*257*inv/0xffff) >> 8)
				buf[o+1] = byte((g + uint32(bgn)*257*inv/0xffff) >> 8)
				buf[o+2] = byte((r + uint32(br)*257*inv/0xffff) >> 8)
			}
		}
		xproto.PutImage(c, xproto.ImageFormatZPixmap, xproto.Drawable(wid), gc,
			slot, slot, int16(slotX(i)), (panelH-slot)/2, 0, scr.RootDepth, buf)
	}
	hit := func(x int16) int {
		for i := range launchers {
			if int(x) >= slotX(i) && int(x) < slotX(i)+slot {
				return i
			}
		}
		return -1
	}
	setHover := func(i int) {
		if i == hover {
			return
		}
		old := hover
		hover = i
		if old >= 0 {
			draw(old)
		}
		if i >= 0 {
			draw(i)
		}
	}

	cmds := make(chan string, 4)
	ctlServer(cmds)
	watchConfig(cmds)
	defer os.Remove(sockPath())
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

	handle := func(ev xgb.Event) {
		switch e := ev.(type) {
		case xproto.ExposeEvent:
			for i := range launchers {
				draw(i)
			}
		case xproto.MotionNotifyEvent:
			setHover(hit(e.EventX))
		case xproto.LeaveNotifyEvent:
			setHover(-1)
		case xproto.ButtonPressEvent:
			if i := hit(e.EventX); i >= 0 && e.Detail == 1 {
				cmd := launchers[i].command()
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
		case cmd := <-cmds:
			switch cmd {
			case "reload": // re-read panel config and .desktop files, redraw
				log.Println("reload")
				if l := loadPanelLaunchers(); len(l) > 0 {
					launchers, hover = l, -1
					xproto.ClearArea(c, true, wid, 0, 0, 0, 0) // exposes -> redraw
				}
			case "restart": // replace this process with the (possibly rebuilt) binary
				os.Remove(sockPath())
				exe, _ := os.Executable()
				log.Fatal(syscall.Exec(exe, []string{exe}, os.Environ()))
			case "quit":
				return
			}
		}
	}
}
