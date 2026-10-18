// gopanel: a minimal X11 panel in pure Go (no cgo, no toolkit).
// Two jobs: (1) reserve a strip at the screen bottom via _NET_WM_STRUT_PARTIAL
// so the WM keeps other windows out of it, (2) lay out items in it: launchers,
// built-in widgets (clock, genmon) and frames sent by helper processes.
// The item list mirrors the xfce4-panel plugin list (see config.go).
package main

import (
	"context"
	"encoding/binary"
	"fmt"
	"github.com/godbus/dbus/v5"
	"github.com/jezek/xgb/randr"
	"log"
	"net"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"runtime/debug"
	"runtime/pprof"
	"slices"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/jezek/xgb"
	"github.com/jezek/xgb/dpms"
	"github.com/jezek/xgb/xproto"

	"gopanel/proto"
)

const version = "0.23.4"

// startupQuiet is how long after launch new icons appear without a glow: the panel is still
// filling up then.
const startupQuiet = 25 * time.Second

var ctlCmds chan<- string // control commands into the main loop

var (
	xc            *xgb.Conn // shared X connection (goroutine-safe)
	xroot         xproto.Window
	drawItem      func(*item) // set by main: repaint one item (main goroutine only)
	toggleWhisker func()      // open/close the application menu (main goroutine only)
	cancelTipFn   func()
	whiskerAnchor int // screen x of the menu button
	taskbars      []*taskbar
	panelH        = 35 // overridden from the xfce4-panel config
	iconSize      = 28
	panelScreenY  uint16 // screen y of the panel's top edge
)

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
	startLockWatcher()
	sweepStaleSubscribers()
	sig := make(chan os.Signal, 1) // register first: default SIGHUP action would kill us
	signal.Notify(sig, syscall.SIGHUP)

	cfg := xfconfAll()
	panelH = atoi(cfg["/panels/panel-1/size"], panelH)
	iconSize = min(atoi(cfg["/panels/panel-1/icon-size"], iconSize), panelH-2)
	if iconSize < 8 {
		iconSize = panelH - 2
	}

	if conn, err := net.Dial("unix", sockPath()); err == nil { // before touching X
		conn.Close()
		log.Fatal("gopanel already running")
	}

	c, err := xgb.NewConn()
	if err != nil {
		log.Fatal(err)
	}
	defer c.Close()
	scr := xproto.Setup(c).DefaultScreen(c)
	initRandr(c, scr.Root)
	applyMonitorChoice(cfg)
	queryMonitor(c, scr)
	sw := uint16(monW)

	xc, xroot = c, scr.Root
	wid, _ := xproto.NewWindowId(c)
	panelWin = wid
	xproto.CreateWindow(c, scr.RootDepth, wid, scr.Root,
		int16(monX), int16(panelTopY()), sw, uint16(panelH), 0,
		xproto.WindowClassInputOutput, scr.RootVisual,
		xproto.CwBackPixel|xproto.CwEventMask,
		[]uint32{curBg, xproto.EventMaskExposure | xproto.EventMaskButtonPress |
			xproto.EventMaskPointerMotion | xproto.EventMaskLeaveWindow})

	// Window type DOCK + strut: this is "where the rest of the desktop is".
	xproto.ChangeProperty(c, xproto.PropModeReplace, wid, atom(c, "_NET_WM_WINDOW_TYPE"),
		xproto.AtomAtom, 32, 1, u32(uint32(atom(c, "_NET_WM_WINDOW_TYPE_DOCK"))))
	setStrut := func() {
		bottom := uint32(rootH - (monY + monH) + panelH)
		xproto.ChangeProperty(c, xproto.PropModeReplace, wid, atom(c, "_NET_WM_STRUT_PARTIAL"),
			xproto.AtomCardinal, 32, 12, u32(0, 0, 0, bottom, 0, 0, 0, 0, 0, 0, uint32(monX), uint32(monX+monW-1)))
		xproto.ChangeProperty(c, xproto.PropModeReplace, wid, atom(c, "_NET_WM_STRUT"),
			xproto.AtomCardinal, 32, 4, u32(0, 0, 0, bottom))
	}
	setStrut()
	name := "gopanel"
	xproto.ChangeProperty(c, xproto.PropModeReplace, wid, xproto.AtomWmName,
		xproto.AtomString, 8, uint32(len(name)), []byte(name))

	gc, _ := xproto.NewGcontextId(c)
	xproto.CreateGC(c, gc, xproto.Drawable(wid), 0, nil)
	xproto.MapWindow(c, wid)
	xscr, xgc = scr, gc

	// All panel drawing goes to a back pixmap and is copied to the window in one go, so a full
	// redraw never shows the cleared panel between the clear and the icons (that flickered
	// while things were still arriving at startup).
	backW := monW
	back, _ := xproto.NewPixmapId(c)
	xproto.CreatePixmap(c, scr.RootDepth, back, xproto.Drawable(wid), uint16(backW), uint16(panelH))
	bgGC, _ := xproto.NewGcontextId(c)
	xproto.CreateGC(c, bgGC, xproto.Drawable(back), xproto.GcForeground, []uint32{curBg})
	panelGCs.c, panelGCs.scr, panelGCs.gc, panelGCs.bgGC = c, scr, gc, bgGC
	tip := newTooltip(c, scr, gc)
	noticeTip = newTooltip(c, scr, gc)
	menus := newMenuMgr(c, scr, gc)
	wh := newWhisker(c, scr, gc)
	theWhisker = wh
	butlerC := make(chan butlerResult, 8)
	wh.bc = newButlerClient(butlerC)
	cmdOSD := newOSD(c, scr, gc)
	toggleWhisker = func() {
		cancelTipFn()
		wh.toggle(whiskerAnchor)
	}

	var (
		items   []*item
		helpers []*helperConn
		sups    = map[string]*supervisor{}
		hover   *item
		paused  bool
		curCfg  map[string][]string // the xfce4-panel config the item list was built from
		glowing bool                // a glow-tick is scheduled
	)
	startedAt := time.Now()
	curHover = func() *item { return hover }

	// relayout assigns x positions; expanding items share whatever width is left.
	relayout := func() {
		if swapped { // a replica's event handler is running: redo it once the swap is undone
			pendingRelayout = true
			return
		}
		for _, it := range items { // a tray keeps its recorded slot while the apps dock
			if it.hold > it.w {
				it.w = it.hold
			}
		}
		xs, ws := computeLayout(items, monW, false)
		for _, it := range items {
			it.x = xs[it]
			if it.expand {
				if nw := ws[it]; nw != it.w {
					it.w = nw
					if it.resize != nil {
						it.resize(nw)
					}
				}
			}
		}
		layoutReplicas()
		xt.place()
		scheduleRecord()
	}

	// draw composites the item's image (premultiplied RGBA, centred) over the panel or
	// hover colour and pushes the item's box to the window.
	drawTo := func(it *item, copyOut bool) {
		if it.w <= 0 {
			return
		}
		bg := curBg
		if it == hover && it.hl && hoverPanel == nil {
			bg = curHoverBg
		}
		need := it.w * panelH * 4
		if cap(it.drawBuf) < need { // reused between frames: animated items draw 20-40 times a second
			it.drawBuf = make([]byte, need)
		}
		buf := it.drawBuf[:need]
		compositeGlow(buf, it.w, it.img, it.hold > 0, bg, it.glow())
		putBGRX(c, xproto.Drawable(back), gc, scr.RootDepth, it.x, 0, it.w, panelH, buf)
		if copyOut {
			xproto.CopyArea(c, xproto.Drawable(back), xproto.Drawable(wid), gc, int16(it.x), 0, int16(it.x), 0, uint16(it.w), uint16(panelH))
		}
	}
	draw := func(it *item) {
		drawTo(it, true)
		drawReplicas(it)
	}
	drawItem = draw
	redrawAll := func() {
		xproto.PolyFillRectangle(c, xproto.Drawable(back), bgGC, []xproto.Rectangle{{X: 0, Y: 0, Width: uint16(backW), Height: uint16(panelH)}})
		for _, it := range items {
			drawTo(it, false)
		}
		xproto.CopyArea(c, xproto.Drawable(back), xproto.Drawable(wid), gc, 0, 0, 0, 0, uint16(backW), uint16(panelH))
		redrawReplicas()
	}
	reflow = func() {
		relayout()
		redrawAll()
	}
	// reposition moves the panel to the monitor pickMonitor chooses now (a no-op when that
	// monitor's rectangle is the one it is already on).
	// pushBg gives the windows and the fill GC the current background and redraws everything.
	pushBg := func() {
		xproto.ChangeGC(c, bgGC, xproto.GcForeground, []uint32{curBg})
		xproto.ChangeWindowAttributes(c, wid, xproto.CwBackPixel, []uint32{curBg})
		xt.repaintBg()
		for _, r := range replicas {
			xproto.ChangeWindowAttributes(c, r.win, xproto.CwBackPixel, []uint32{curBg})
		}
		for _, tb := range taskbars { // its button colours come from the background too
			if tb.w > 0 {
				tb.it.img = tb.renderImg(tb.w, nil)
			}
		}
		redrawAll()
	}
	// bgStep/setBgCycle run the background colour drift (bgcycle.go).
	bgStep := func(force bool) {
		if bgPeriod == 0 {
			return
		}
		bg, hover := pastelAt(time.Now(), bgPeriod)
		if bg == curBg && !force {
			return
		}
		applyBgColors(bg, hover, false)
		pushBg()
	}
	setBgCycle := func(d time.Duration) {
		if d == bgPeriod {
			return
		}
		bgPeriod = d
		if bgTicker != nil {
			bgTicker.Stop()
			bgTick = nil
		}
		if d == 0 {
			applyBgColors(panelBg, hoverBg, true)
			pushBg()
			return
		}
		bgTicker = time.NewTicker(max(d/360, tickFloor())) // one degree of hue per step
		bgTick = bgTicker.C
		bgStep(true)
	}
	lastSig := ""
	reposition := func() {
		queryMonitor(c, scr)
		sig := monitorSig() + "|" + panelOutput
		if sig == lastSig {
			return
		}
		lastSig = sig
		wh.close()
		menus.close()
		closePopup()
		xproto.ConfigureWindow(c, wid, xproto.ConfigWindowX|xproto.ConfigWindowY|xproto.ConfigWindowWidth|xproto.ConfigWindowHeight,
			[]uint32{uint32(monX), uint32(panelTopY()), uint32(monW), uint32(panelH)})
		setStrut()
		xproto.FreePixmap(c, back)
		backW = monW
		back, _ = xproto.NewPixmapId(c)
		xproto.CreatePixmap(c, scr.RootDepth, back, xproto.Drawable(wid), uint16(backW), uint16(panelH))
		rebuildReplicas(monRect{x: monX, y: monY, w: monW, h: monH})
		relayout()
		redrawAll()
	}
	hit := func(x int16) *item {
		for _, it := range items {
			if it.interactive() && int(x) >= it.x && int(x) < it.x+it.w {
				return it
			}
		}
		return nil
	}

	// Tooltips appear after the pointer rests on an item for a moment.
	type tipReq struct {
		it  *item
		rep *replica
	}
	tipC := make(chan tipReq, 1)
	var tipTimer *time.Timer
	cancelTip := func() {
		if tipTimer != nil {
			tipTimer.Stop()
		}
		tip.hide()
	}
	ptrX := 0 // last pointer x, screen coordinates
	tipText := func(it *item) string {
		if it.tipAt != nil {
			return it.tipAt(ptrX - it.x)
		}
		return it.tip
	}
	armTip := func(it *item) {
		// helpers send their tooltip lazily after "hover on", so an empty tip is still armed
		if it == nil || (it.tip == "" && it.tipAt == nil && it.kind != "helper") {
			return
		}
		rep := activeRep // the tooltip belongs to the panel the pointer is on
		tipTimer = time.AfterFunc(500*time.Millisecond, func() {
			select {
			case tipC <- tipReq{it, rep}:
			default:
			}
		})
	}
	cancelTipFn = cancelTip
	setHover := func(it *item) {
		if it == hover && activeRep == hoverPanel {
			return
		}
		old := hover
		hover, hoverPanel = it, activeRep // highlighted on the panel the pointer is on only
		cancelTip()
		if old != nil {
			if old.hover != nil {
				old.hover(false)
			}
			draw(old)
		}
		if it != nil {
			if it.hover != nil {
				it.hover(true)
			}
			draw(it)
			armTip(it)
		}
	}

	// startGlow keeps redrawing the glowing items until their glow has run out.
	startGlow := func() {
		if glowing {
			return
		}
		for _, it := range items {
			if it.glow() > 0 {
				glowing = true
				time.AfterFunc(50*time.Millisecond, func() { ctlCmds <- "glow-tick" })
				return
			}
		}
	}

	// reloadIncremental handles the common reload, a genmon icon appearing or disappearing,
	// without rebuilding anything else: the other items keep their state and are not redrawn
	// from scratch. It reports false when the change is anything else (the caller then does a
	// full install).
	reloadIncremental := func(cfg map[string][]string) bool {
		if curCfg == nil || cfg == nil || len(items) == 0 {
			return false
		}
		isGenmon := func(c map[string][]string, id string) bool {
			v := c["/plugins/plugin-"+id]
			return len(v) > 0 && v[0] == "genmon"
		}
		ids := cfg["/panels/panel-1/plugin-ids"]
		present := map[string]*item{}
		for _, it := range items {
			if it.kind == "genmon" {
				present[it.pid] = it
			}
		}
		wanted := map[string]bool{}
		var added, removed []string
		for _, id := range ids {
			if isGenmon(cfg, id) && iniFile(genmonRC(id))["Command"] != "" {
				wanted[id] = true
				if present[id] == nil {
					added = append(added, id)
				}
			}
		}
		for id := range present {
			if !wanted[id] {
				removed = append(removed, id)
			}
		}
		// everything but the genmon plugins must be unchanged
		skip := func(c map[string][]string, k string) bool {
			if k == "/panels/panel-1/plugin-ids" {
				return true
			}
			rest, ok := strings.CutPrefix(k, "/plugins/plugin-")
			if !ok {
				return false
			}
			id, _, _ := strings.Cut(rest, "/")
			return isGenmon(c, id) || isGenmon(curCfg, id)
		}
		same := func(a, b map[string][]string) bool {
			for k, v := range a {
				if !skip(a, k) && !slices.Equal(v, b[k]) {
					return false
				}
			}
			return true
		}
		if !same(cfg, curCfg) || !same(curCfg, cfg) {
			return false
		}
		nonGenmon := func(c map[string][]string) []string {
			var out []string
			for _, id := range c["/panels/panel-1/plugin-ids"] {
				if !isGenmon(c, id) {
					out = append(out, id)
				}
			}
			return out
		}
		if !slices.Equal(nonGenmon(cfg), nonGenmon(curCfg)) {
			return false
		}
		for id, it := range present { // a genmon whose command or period changed needs a restart
			if wanted[id] && it.sig != "" {
				rc := iniFile(genmonRC(id))
				if it.sig != rc["Command"]+"|"+rc["UpdatePeriod"] {
					return false
				}
			}
		}
		if len(added)+len(removed) == 0 {
			curCfg = cfg
			return true // e.g. a genmon rc written before its plugin id: nothing visible changes
		}
		log.Printf("reload: genmon icons +%v -%v", added, removed)
		kept := items[:0:0]
		for _, it := range items {
			if it.kind == "genmon" && !wanted[it.pid] {
				if hover == it {
					hover, hoverPanel = nil, nil
					cancelTip()
				}
				it.discard()
				continue
			}
			kept = append(kept, it)
		}
		items = kept
		for _, id := range added {
			g := newGenmonFromRC(id)
			if g == nil {
				continue
			}
			if time.Since(startedAt) > startupQuiet {
				g.glowFrom = time.Now()
			}
			at := 0 // after the last item of the nearest earlier plugin that has items
			for i := slices.Index(ids, id) - 1; i >= 0 && at == 0; i-- {
				for j := len(items) - 1; j >= 0; j-- {
					if items[j].pid == ids[i] {
						at = j + 1
						break
					}
				}
			}
			items = slices.Insert(items, at, g)
		}
		panelItems = items
		curCfg = cfg
		relayout()
		redrawAll()
		startGlow()
		return true
	}

	// install replaces the item list (initial build and reload): old items are
	// discarded, still-connected helpers are re-bound by name, and helper
	// supervisors are started/stopped to match.
	install := func(cfg map[string][]string) {
		applyMonitorChoice(cfg)
		reposition() // no-op unless the monitor setup or the choice changed
		bgStyle = readPanelConf()["BG_STYLE"]
		setBgCycle(bgPeriodOf(readPanelConf()["BG_CYCLE"]))
		hover, hoverPanel = nil, nil
		cancelTip()
		had := map[string]bool{}
		for _, it := range items {
			had[it.pid] = true
			it.discard()
		}
		for _, tb := range taskbars {
			tb.close()
		}
		taskbars = nil
		items = buildItems(cfg)
		panelItems = items
		if len(had) > 0 && time.Since(startedAt) > startupQuiet {
			for _, it := range items { // icons that were not there before: let them glow
				if !had[it.pid] && (it.kind == "genmon" || it.kind == "helper" || it.kind == "launcher") {
					it.glowFrom = time.Now()
				}
			}
		}
		curCfg = cfg
		want := map[string]bool{}
		for _, it := range items {
			if it.kind == "helper" {
				want[it.name] = true
				for _, hc := range helpers {
					if hc.name == it.name && it.hc == nil {
						bindHelper(it, hc)
					}
				}
			}
		}
		for n, s := range sups {
			if !want[n] {
				close(s.stop)
				delete(sups, n)
			}
		}
		for _, it := range items {
			if it.kind != "helper" {
				continue
			}
			if s := sups[it.name]; s != nil {
				s.watch(it) // a reload built a new item: the supervisor must watch that one, not the discarded one
				continue
			}
			s := &supervisor{name: it.name, stop: make(chan struct{})}
			s.watch(it)
			sups[it.name] = s
			go s.run()
		}
		reserveWidths(items)
		relayout()
		redrawAll()
		startGlow()
		time.AfterFunc(10*time.Second, func() { ctlCmds <- "unreserve" }) // helpers are only spawned after the supervisor's 4 s grace
		time.AfterFunc(20*time.Second, func() { ctlCmds <- "unreserve-late" })
	}

	cmds := make(chan string, 4)
	ctlCmds = cmds
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

	go reapZombies()
	install(cfg)
	reposition()    // creates the replica panels, if the setting asks for them
	xt.tryAcquire() // right away: while nobody owns the tray, apps show their icon as a stray window
	whReady := make(chan whiskerData, 1)
	go preloadWhisker(whReady)

	// Helpers are told to pause while the display is in standby or the screensaver
	// (lock screen) is active: nothing to see, and animation would only burn battery.
	dpmsC := make(chan bool, 1)
	hasDPMS := dpms.Init(c) == nil
	go func() { // own goroutine: a reply that never comes must not freeze the main loop
		bus, _ := dbus.ConnectSessionBus()
		for {
			time.Sleep(2 * time.Second)
			off := false
			if hasDPMS {
				if info, err := dpms.Info(c).Reply(); err == nil {
					off = info.State && info.PowerLevel != dpms.DPMSModeOn
				}
			}
			if !off && bus != nil {
				var active bool
				ctx, cancel := context.WithTimeout(context.Background(), time.Second)
				err := bus.Object("org.xfce.ScreenSaver", "/org/xfce/ScreenSaver").CallWithContext(ctx, "org.xfce.ScreenSaver.GetActive", 0).Store(&active)
				cancel()
				off = err == nil && active
			}
			select {
			case dpmsC <- off:
			default:
			}
		}
	}()
	pauseLine := func() string {
		if paused {
			return "pause"
		}
		return "resume"
	}

	grabMediaKeys()
	handle := func(ev xgb.Event) {
		if xt.handle(ev) {
			return
		}
		switch e := ev.(type) {
		case randr.ScreenChangeNotifyEvent, randr.NotifyEvent:
			// monitor plugged/unplugged, made primary, or resolution changed
			reposition()
		case xproto.KeyPressEvent:
			mediaKey(e.Detail)
		case xproto.ExposeEvent:
			if e.Count == 0 {
				redrawAll()
			}
		case xproto.PropertyNotifyEvent:
			// Another window took focus (a dictation typing back into its window,
			// the user switching windows): popups hold a keyboard grab that would
			// swallow its keystrokes, so let go of it.
			if e.Window == xroot && (wh.isOpen || menus.active()) {
				if r, err := xproto.GetAtomName(xc, e.Atom).Reply(); err == nil && r.Name == "_NET_ACTIVE_WINDOW" {
					wh.close()
					menus.close()
				}
			}
			for _, tb := range taskbars {
				tb.onProperty(e)
			}
		case xproto.MotionNotifyEvent:
			ptrX = int(e.EventX)
			it := hit(e.EventX)
			setHover(it)
			if it != nil && it.motion != nil {
				it.motion(ptrX - it.x)
			}
			if it != nil && it.tipAt != nil && tip.shown && tip.forIt == it { // moved to another icon
				if txt := tipText(it); txt == "" {
					tip.hide()
				} else if txt != tip.text {
					tip.show(it, txt, ptrX)
				}
			} else if it != nil && it.tipAt != nil && !tip.shown {
				cancelTip()
				armTip(it)
			}
		case xproto.LeaveNotifyEvent:
			setHover(nil)
		case xproto.ButtonPressEvent:
			cancelTip()
			it := hit(e.EventX)
			if e.Detail == 3 && it != nil && it.hasClick != nil && it.hasClick() {
				it.click(int(e.EventX)-it.x, int(e.EventY), 1) // one menu per icon: right click = left click
			} else if e.Detail == 3 && (it == nil || it.kind == "separator" || it.kind == "launcher" || it.kind == "whisker" || it.kind == "clock" || it.kind == "helper" || it.kind == "genmon") {
				panelMenu(int(e.EventX), cmds, it)
			} else if it != nil && it.click != nil {
				it.click(int(e.EventX)-it.x, int(e.EventY), int(e.Detail))
			}
		}
	}

	xtTick := xtrayTick()
	for {
		select {
		case <-xtTick:
			xt.tryAcquire()
			xt.refreshHidden()
		case ev, ok := <-events:
			if !ok {
				return
			}
			if ee, isExp := ev.(xproto.ExposeEvent); isExp && ee.Window == tip.win {
				tip.paint()
				continue
			}
			if ee, isExp := ev.(xproto.ExposeEvent); isExp && cmdOSD.shown && ee.Window == cmdOSD.win {
				cmdOSD.paint()
				continue
			}
			if ee, isExp := ev.(xproto.ExposeEvent); isExp && noticeTip.shown && ee.Window == noticeTip.win {
				noticeTip.paint()
				continue
			}
			if r := replicaOf(ev); r != nil {
				if _, isExp := ev.(xproto.ExposeEvent); isExp {
					r.flush()
				} else {
					withReplica(r, func() { handle(ev) })
				}
				continue
			}
			if popupHandle(ev) {
				continue
			}
			if menus.handle(ev) {
				continue
			}
			if wh.handle(ev) {
				continue
			}
			handle(ev)
		case r := <-butlerC:
			switch {
			case r.osdHide:
				cmdOSD.hideIf(r.gen)
				continue
			case r.ran:
				msg := r.osd
				if msg == "" {
					msg = r.reply
				}
				if r.ok {
					cmdOSD.show(msg, r.level, r.levelMax, butlerC)
				}
			}
			wh.onButler(r)
		case d := <-whReady:
			if !wh.loaded {
				wh.setData(d)
			}
		case req := <-menuReqs:
			cancelTip()
			closePopup()
			if req.rep != nil {
				withReplica(req.rep, func() { menus.open(req) })
			} else {
				menus.open(req)
			}
		case u := <-updates:
			it := u.it
			if it.isDead() {
				continue
			}
			it.reserved = false
			if u.img != nil {
				it.img = u.img
			}
			if u.tip != nil {
				it.tip = *u.tip
				if tip.shown && tip.forIt == it {
					if it.tip == "" {
						tip.hide()
					} else {
						tip.show(it, it.tip, it.x+it.w/2)
					}
				}
			}
			if u.w != it.w && !it.expand && u.w >= 0 && (u.w > 0 || u.force || u.img != nil) {
				it.w = u.w
				relayout()
				redrawAll()
				continue
			}
			draw(it)
		case rq := <-tipC:
			showTip := func() {
				it := rq.it
				if txt := tipText(it); it == hover && txt != "" && !it.isDead() {
					tip.show(it, txt, it.x+it.w/2)
				}
			}
			if rq.rep != nil {
				withReplica(rq.rep, showTip)
			} else {
				showTip()
			}
		case he := <-hev:
			switch he.kind {
			case "hello":
				var target *item
				for _, it := range items {
					if it.kind == "helper" && it.name == he.hc.name && it.hc == nil {
						target = it
						break
					}
				}
				if target == nil { // not in the panel configuration, or a duplicate: tell it to exit
					he.hc.send("quit")
					go func(hc *helperConn) { time.Sleep(300 * time.Millisecond); hc.kill() }(he.hc)
					continue
				}
				helpers = append(helpers, he.hc)
				bindHelper(target, he.hc)
				noticeIcon()
				he.hc.send(pauseLine())
				relayout()
				redrawAll()
			case "image":
				he.hc.img = he.img
				if it := itemFor(items, he.hc); it != nil {
					it.img = he.img
					draw(it)
				}
			case "label":
				if it := itemFor(items, he.hc); it != nil {
					it.img = nil
					if isStacked(it.name) {
						it.img = renderStacked(he.text, true)
					}
					if it.img == nil {
						it.img = renderLabel(he.text)
					}
					w := 0
					if it.img != nil {
						w = it.img.Bounds().Dx() + 2*labelEdge
						if isStacked(it.name) {
							w = it.img.Bounds().Dx() + labelEdge + 1 // tight on the right, the text is right-aligned
						}
					}
					if w != it.w {
						it.w = w
						relayout()
						redrawAll()
					} else {
						draw(it)
					}
				}
			case "tooltip":
				if it := itemFor(items, he.hc); it != nil {
					it.tip = he.text
					if tip.shown && tip.forIt == it {
						tip.show(it, it.tip, it.x+it.w/2)
					}
				}
			case "bye":
				for i, hc := range helpers {
					if hc == he.hc {
						helpers = append(helpers[:i], helpers[i+1:]...)
						break
					}
				}
				if it := itemFor(items, he.hc); it != nil {
					unbindHelper(it)
					if hover == it {
						hover = nil
						cancelTip()
					}
				}
				relayout()
				redrawAll()
			}
		case <-bgTick:
			if !paused { // nobody is looking: no redraws while the screen is off or locked
				bgStep(false)
			}
		case off := <-dpmsC:
			if off != paused {
				paused = off
				if !paused {
					bgStep(false) // catch up with the time that passed
				}
				for _, hc := range helpers {
					hc.send(pauseLine())
				}
			}
		case reply := <-itemsReq:
			reply <- itemsSnapshot(items)
		case cmd := <-cmds:
			if tok, ok := strings.CutPrefix(cmd, "whisker-list:"); ok { // typing paused: update the menu list
				n, _ := strconv.Atoi(tok)
				wh.listTick(n)
				continue
			}
			if tok, ok := strings.CutPrefix(cmd, "whisker-blink:"); ok {
				n, _ := strconv.Atoi(tok)
				wh.blinkTick(n)
				continue
			}
			if tok, ok := strings.CutPrefix(cmd, "whisker-cat:"); ok { // hover-open timer of a menu category
				n, _ := strconv.Atoi(tok)
				wh.catTick(n)
				continue
			}
			if name, ok := strings.CutPrefix(cmd, "helper-restart:"); ok { // internal (the socket does not accept it)
				for _, hc := range helpers {
					if hc.name == name {
						hc.send("quit") // exits; the supervisor starts it again, reading the new settings
					}
				}
				continue
			}
			switch cmd {
			case "reload": // re-read the xfce4-panel config, rebuild all items
				log.Println("reload")
				cfg := xfconfAll()
				if !reloadIncremental(cfg) {
					install(cfg)
				}
			case "glow-tick":
				glowing = false
				for _, it := range items {
					if !it.glowFrom.IsZero() {
						draw(it)
						if it.glow() == 0 {
							it.glowFrom = time.Time{}
						}
					}
				}
				startGlow()
			case "restart": // replace this process with the (possibly rebuilt) binary
				// Check before tearing anything down: a failed exec after that leaves no panel.
				exe := restartExe()
				if exe == "" {
					log.Printf("restart: cannot find the binary, keeping this panel running")
					continue
				}
				xt.parkIcons()
				killSubscribers()
				os.Remove(sockPath())
				os.Remove(proto.SockPath())
				log.Fatal(syscall.Exec(exe, []string{exe}, os.Environ()))
			case "menu":
				toggleWhisker()
			case "whisker-drag": // trailing repaint of a throttled scrollbar drag
				wh.dragTick()
			case "calendar", "volume", "power": // also handy for testing; toggles
				if curPop != nil {
					closePopup()
				} else if cmd == "calendar" {
					openCalendar(monW - 60)
				} else if cmd == "power" {
					openPowerPopup(monW - 300)
				} else {
					openVolumePopup(monW - 400)
				}
			case "profile": // 10 s CPU profile -> $XDG_RUNTIME_DIR/gopanel.prof (go tool pprof)
				go func() {
					f, err := os.Create(filepath.Join(os.Getenv("XDG_RUNTIME_DIR"), "gopanel.prof"))
					if err != nil {
						return
					}
					pprof.StartCPUProfile(f)
					time.Sleep(10 * time.Second)
					pprof.StopCPUProfile()
					f.Close()
				}()
			case "layout": // debugging: log every item's position
				for i, it := range items {
					log.Printf("layout %2d %-9s %-14s x=%4d w=%4d expand=%v reserved=%v", i, it.kind, it.name, it.x, it.w, it.expand, it.reserved)
				}
				if sniTray != nil {
					sniTray.mu.Lock()
					for _, ic := range sniTray.icons {
						log.Printf("tray id=%q title=%q tip=%q status=%s rank=%d", ic.id, ic.title, ic.tip, ic.status, trayRank(ic, trayOrder))
					}
					sniTray.mu.Unlock()
				}
			case "dismiss": // close every open popup (Dictate asks before it types)
				wh.close()
				menus.close()
				closePopup()
			case "notice-timeout:" + strconv.Itoa(noticeToken): // only the latest launch's timer counts
				noticeHide()
			case "notice-icon":
				if noticeTip.shown {
					noticeHide()
				}
			case "record-widths":
				saveWidths(items)
			case "unreserve": // cached widths that nobody confirmed: give the space back
				if unreserve(items, false) {
					relayout()
					redrawAll()
				}
				checkWidths(items)
			case "unreserve-late": // autostarted apps have had their time to dock: release the tray slot, start recording
				if unreserve(items, true) {
					for _, it := range items {
						if it.kind == "tray" || it.kind == "xtray" {
							it.w = 0 // recomputed from the icons actually docked
						}
					}
					if sniTray != nil {
						sniTray.render()
					}
					xt.sync()
				}
				recordArmed = true
				scheduleRecord()
			case "yield":
				xt.yieldTray()
			case "quit":
				xt.parkIcons()
				killSubscribers()
				for _, s := range sups {
					close(s.stop)
				}
				time.Sleep(200 * time.Millisecond) // let supervisors terminate their children
				return
			}
		}
	}
}

func itemFor(items []*item, hc *helperConn) *item {
	for _, it := range items {
		if it.hc == hc {
			return it
		}
	}
	return nil
}

// bindHelper attaches a connected helper to its panel item.
func bindHelper(it *item, hc *helperConn) {
	it.hc, it.reserved = hc, false
	it.conn.Store(true)
	it.w, it.img, it.hl = hc.w, hc.img, false
	it.click = func(x, y, btn int) { hc.send(fmt.Sprintf("click %d %d %d", x, y, btn)) }
	it.hover = func(on bool) {
		if on {
			hc.send("hover on")
		} else {
			hc.send("hover off")
		}
	}
}

func unbindHelper(it *item) {
	it.hc = nil
	it.conn.Store(false)
	it.w, it.img, it.tip, it.click, it.hover = 0, nil, "", nil, nil
}

// xfcePanelRunning reports whether the stock xfce4-panel is up.
func xfcePanelRunning() bool {
	return exec.Command("pgrep", "-x", "xfce4-panel").Run() == nil
}

// panelMenu is the right-click menu of the panel background: switch the stock
// XFCE panel on or off, restart or quit this panel.
func panelMenu(x int, cmds chan<- string, over *item) {
	xfce := &menuItem{id: 1, label: tr("Start XFCE panel")}
	if xfcePanelRunning() {
		xfce = &menuItem{id: 1, label: tr("Stop XFCE panel")}
	}
	items := []*menuItem{{id: 4, label: tr("Panel settings…")}, {sep: true}, xfce, {sep: true}, {id: 2, label: tr("Restart this panel")}, {id: 3, label: tr("Quit this panel")}}
	if over != nil && over.kind == "launcher" && over.lid != "" {
		items = append([]*menuItem{{id: 20, label: tr("Remove from panel")}, {sep: true}}, items...)
	}
	if over != nil && over.rc != "" && over.kind != "genmon" { // the plugin's own entry, like the XFCE panel's plugin menu
		items = append([]*menuItem{{id: 10, label: propsLabel(over.title)}, {sep: true}}, items...)
	}
	menuReqs <- menuReq{rep: activeRep,
		items:   items,
		anchorX: x,
		onSelect: func(mi *menuItem) {
			switch mi.id {
			case 20:
				go removeLauncher(over.lid, over.lfile, over.title, cmds)
			case 10:
				title := over.title
				if title == "" {
					title = filepath.Base(over.rc)
				}
				run(exec.Command(os.ExpandEnv("$HOME/.local/bin/cyberbeest-settings.py"), "--rc", over.rc, "--title", title, "--kind", over.ptype))
			case 4:
				run(exec.Command(os.ExpandEnv("$HOME/.local/bin/cyberbeest-settings.py"), "--tab=panel"))
			case 1:
				go toggleXfcePanel()
			case 2:
				go func() { cmds <- "restart" }()
			case 3:
				go func() {
					if !xfcePanelRunning() { // never leave the desktop without a panel
						toggleXfcePanel()
					}
					cmds <- "quit"
				}()
			}
		},
	}
}

// toggleXfcePanel stops or starts the stock panel. The xfce-panel-watchdog user
// service relaunches a dead panel within seconds, so a stop leaves a marker file
// it respects; a start removes the marker and lets the watchdog bring the panel
// up with the proper session environment, launching it directly only if the
// watchdog (not installed everywhere) does not.
func toggleXfcePanel() {
	if !xfcePanelRunning() {
		ctlCmds <- "yield" // so its systray can own the XEmbed tray selection
		time.Sleep(300 * time.Millisecond)
	}
	dir := os.Getenv("XDG_RUNTIME_DIR")
	if dir == "" {
		dir = os.TempDir()
	}
	marker := filepath.Join(dir, "cyberbeest-xfce-panel-stopped")
	if xfcePanelRunning() {
		os.WriteFile(marker, nil, 0o600)
		exec.Command("xfce4-panel", "--quit").Run()
		return
	}
	os.Remove(marker)
	for i := 0; i < 14; i++ {
		time.Sleep(500 * time.Millisecond)
		if xfcePanelRunning() {
			return
		}
	}
	exec.Command("systemd-run", "--user", "--collect", "--quiet", "-p", "KillMode=process", // see cyberbeest-panel-choice.sh
		"--setenv=DISPLAY", "--setenv=XAUTHORITY", "--setenv=XDG_CURRENT_DESKTOP", "--setenv=XDG_SESSION_TYPE",
		"xfce4-panel").Run()
}
