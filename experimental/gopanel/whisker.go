package main

import (
	"image"
	"image/color"
	"image/draw"
	"os"
	"os/exec"
	"os/user"
	"path/filepath"
	"strconv"
	"strings"
	"sync/atomic"
	"time"

	"github.com/jezek/xgb"
	"github.com/jezek/xgb/xproto"
	"gopanel/appmenu"
	"gopanel/gfx"
)

// Whisker-style application menu: header with user and session buttons, search box,
// application list on the left, categories on the right.

const (
	whW, whH     = 600, 650
	whHeaderH    = 52
	whSearchY    = 56
	whSearchH    = 32
	whListTop    = 96
	whListBottom = whH - 8
	whListX      = 8
	whListW      = 402
	whCatX       = 416
	whCatW       = 176
	whAppRowH    = 40
	whHeadRowH   = 26                     // section header of a pane (Recently Used / Favorites in Quickstart)
	whCatHover   = 300 * time.Millisecond // how long the pointer must rest on a category before it opens
	whCmdMin     = 0.80                   // matcher score a command needs to appear among the search results
	whCatRowH    = 34
	whAppIcon    = 32
	whCatIcon    = 22
)

var (
	whBg      = color.RGBA{0xf6, 0xf5, 0xf4, 255}
	whBorder  = color.RGBA{0xb4, 0xb2, 0xae, 255}
	whListBg  = color.RGBA{255, 255, 255, 255}
	whSel     = color.RGBA{0xd8, 0xd5, 0xd0, 255}
	whHover   = color.RGBA{0xe6, 0xe4, 0xe1, 255}
	whFocus   = color.RGBA{0x35, 0x84, 0xe4, 255}
	whInk     = color.RGBA{0, 0, 0, 255}
	whDim     = color.RGBA{0x88, 0x88, 0x88, 255}
	whSepLine = color.RGBA{0xcf, 0xcd, 0xc9, 255}
)

// special categories in front of the real ones
const (
	catQuick = iota // Recently Used on top, Favorites below, each half the height with its own scrollbar
	catCmds         // every Butler command
	catAll
	catFirstReal
)

type whisker struct {
	appsLoaded time.Time // applications-dir mtime the menu data was built from
	c          *xgb.Conn
	scr        *xproto.ScreenInfo
	gc         xproto.Gcontext

	win    xproto.Window
	back   xproto.Pixmap // off-screen copy of the window: paints go here, then one CopyArea
	x, y   int
	isOpen bool

	cats   []*appmenu.Category
	all    []*appmenu.Entry
	byID   map[string]*appmenu.Entry
	loaded bool

	favIDs, recentIDs            []string
	catIdx                       int
	query                        []rune
	rows                         []wrow // what the app pane shows (apps, commands, section headers)
	tops                         []int  // tops[i] = y of row i in the list; tops[len(rows)] = total height
	userSel                      bool   // the selection was moved on purpose (keys/hover): keep it when results change
	bc                           *butlerClient
	bseq                         int           // sequence number of the last matcher request
	hits                         []butlerHit   // matcher results for the current query
	allCmds                      []butlerHit   // the whole command catalog (Commands page)
	scoredApps                   []scoredEntry // app search results for the current query
	confirmID                    string        // command waiting for a second Enter
	ranID, ranMsg                string        // last command run from the open menu and the server's answer
	ranOK                        bool
	valueHit                     *butlerHit // a command that is asking for a number, and what was typed so far
	valueBuf                     []rune
	ranAt                        time.Time
	catToken                     int  // identifies the pending hover-open of a category
	dragging                     bool // the scrollbar thumb of pane dragPane is held
	dragPane, dragOff, dragY     int  // dragOff: where in the thumb it was grabbed; dragY: latest pointer y
	dragAt                       time.Time
	dragTimer                    bool
	panes                        []pane // the app list is one pane, or two stacked halves in Quickstart
	catScroll                    int
	hoverRow, hoverCat, hoverBtn int
	selRow                       int         // keyboard selection in the app list
	ctx                          *whiskerCtx // right-click menu of an app row, drawn inside the window

	icons    map[string]*image.RGBA
	userName string
	avatar   *image.RGBA
	btnIcons [2]*image.RGBA
	keymap   []xproto.Keysym
	kpc      int // keysyms per keycode
	minKC    xproto.Keycode
	cfg      map[string][]string

	superArmed bool             // Super was released since opening, so pressing it again closes the menu
	superRel   xproto.Timestamp // time of the last Super release (auto-repeat sends release+press with equal times)
}

type rowKind int

const (
	rowApp rowKind = iota
	rowCmd
)

// pane is a vertically scrolling part of the app list: rows [from,to) under an optional title.
type pane struct {
	title, empty string // empty: what to show when it has no rows
	y, h         int    // position and size inside the list area
	from, to     int
	scroll       int
}

func (p pane) cy() int { // top of the rows
	if p.title == "" {
		return p.y
	}
	return p.y + whHeadRowH
}

func (p pane) ch() int { return p.y + p.h - p.cy() }

type wrow struct {
	kind rowKind
	e    *appmenu.Entry // rowApp
	hit  *butlerHit     // rowCmd
}

func (r wrow) key() string {
	switch r.kind {
	case rowApp:
		return "app:" + r.e.ID
	case rowCmd:
		return "cmd:" + r.hit.ID
	}
	return ""
}

type scoredEntry struct {
	e *appmenu.Entry
	s int
}

func newWhisker(c *xgb.Conn, scr *xproto.ScreenInfo, gc xproto.Gcontext) *whisker {
	w := &whisker{c: c, scr: scr, gc: gc, icons: map[string]*image.RGBA{}, hoverRow: -1, hoverCat: -1, hoverBtn: -1, selRow: -1}
	if u, err := user.Current(); err == nil {
		w.userName = u.Username
	}
	return w
}

type whiskerData struct {
	cats []*appmenu.Category
	all  []*appmenu.Entry
}

// preload runs off the main goroutine at startup: it builds the menu and resolves every
// icon path (filling the disk cache), so the first open is quick.
func preloadWhisker(out chan<- whiskerData) {
	cats, all, err := appmenu.Load()
	if err != nil {
		return
	}
	for _, e := range all {
		findIcons(e.Icon, whAppIcon)
	}
	for _, c := range cats {
		findIcons(c.Icon, whCatIcon)
	}
	FlushIconCache()
	out <- whiskerData{cats, all}
}

func (w *whisker) loadData() {
	cats, all, err := appmenu.Load()
	if err != nil {
		return
	}
	w.setData(whiskerData{cats, all})
}

func (w *whisker) setData(d whiskerData) {
	cats, all := d.cats, d.all
	w.cats, w.all, w.loaded = cats, all, true
	if w.appsLoaded.IsZero() {
		w.appsLoaded = appsStamp()
	}
	w.byID = map[string]*appmenu.Entry{}
	for _, e := range all {
		w.byID[e.ID] = e
	}
}

func (w *whisker) icon(name string, size int) *image.RGBA {
	key := name + "@" + string(rune('0'+size/8))
	if im, ok := w.icons[key]; ok {
		return im
	}
	var im *image.RGBA
	if name != "" {
		if filepath.IsAbs(name) || len(findIcons(name, size)) > 0 {
			im = loadIconSized(name, size)
		}
	}
	if im == nil {
		im = loadIconSized("application-x-executable", size)
	}
	w.icons[key] = im
	return im
}

// xfconf property helpers (whisker settings live in xfce4-panel's channel).
func (w *whisker) prop(name string) []string { return w.cfg["/plugins/plugin-"+whiskerID+"/"+name] }

var whiskerID = "201"

func (w *whisker) refreshConfig() {
	w.cfg = xfconfAll()
	w.favIDs = w.prop("favorites")
	w.recentIDs = w.prop("recent")
}

func (w *whisker) cmdFromCfg(key, def string) string {
	if v := w.prop(key); len(v) == 1 && v[0] != "" {
		return v[0]
	}
	return def
}

func (w *whisker) toggle(anchorX int) {
	if w.isOpen {
		w.close()
		return
	}
	w.open(anchorX)
}

// appsStamp is the newest mtime among the applications directories: installing or
// removing a .desktop file touches its directory, so a change means the menu is stale.
func appsStamp() time.Time {
	var newest time.Time
	dirs := []string{filepath.Join(os.Getenv("HOME"), ".local/share/applications")}
	for _, d := range strings.Split(os.Getenv("XDG_DATA_DIRS"), ":") {
		if d != "" {
			dirs = append(dirs, filepath.Join(d, "applications"))
		}
	}
	dirs = append(dirs, "/usr/share/applications", "/usr/local/share/applications")
	for _, d := range dirs {
		if st, err := os.Stat(d); err == nil && st.ModTime().After(newest) {
			newest = st.ModTime()
		}
	}
	return newest
}

func (w *whisker) open(anchorX int) {
	if stamp := appsStamp(); !w.loaded || stamp.After(w.appsLoaded) {
		w.appsLoaded = stamp
		w.loadData()
	}
	w.refreshConfig()
	w.query = nil
	w.catScroll, w.hoverRow, w.hoverCat, w.hoverBtn, w.selRow = 0, -1, -1, -1, -1
	w.catIdx = catQuick
	if v := w.prop("default-category"); len(v) == 1 && v[0] == "2" {
		w.catIdx = catAll
	}
	w.hits, w.scoredApps, w.confirmID, w.userSel, w.ranMsg = nil, nil, "", false, ""
	w.valueHit, w.valueBuf = nil, nil
	if w.bc != nil {
		w.bc.Warm()
	}
	if w.avatar == nil {
		home, _ := os.UserHomeDir()
		face := filepath.Join(home, ".face")
		if _, err := os.Stat(face); err != nil {
			if v := w.prop("button-icon"); len(v) == 1 {
				face = v[0]
			}
		}
		w.avatar = loadPNG(face, 32)
		for i, n := range []string{"system-lock-screen-symbolic", "system-log-out-symbolic"} {
			w.btnIcons[i] = w.icon(n, 24)
		}
	}
	w.rebuildList()
	if w.keymap == nil {
		setup := xproto.Setup(w.c)
		w.minKC = setup.MinKeycode
		n := byte(setup.MaxKeycode-setup.MinKeycode) + 1
		w.loadKeymap(n)
	}

	w.x = min(max(monX+anchorX, monX), monX+monW-whW)
	w.y = monY + monH - panelH - whH
	wid, _ := xproto.NewWindowId(w.c)
	xproto.CreateWindow(w.c, w.scr.RootDepth, wid, w.scr.Root, int16(w.x), int16(w.y), whW, whH, 0,
		xproto.WindowClassInputOutput, w.scr.RootVisual,
		xproto.CwOverrideRedirect|xproto.CwEventMask, []uint32{1, xproto.EventMaskExposure | xproto.EventMaskKeyPress | xproto.EventMaskKeyRelease})
	xproto.MapWindow(w.c, wid)
	w.win, w.isOpen = wid, true
	whiskerOpen.Store(true)
	w.back, _ = xproto.NewPixmapId(w.c)
	xproto.CreatePixmap(w.c, w.scr.RootDepth, w.back, xproto.Drawable(wid), whW, whH)
	w.superArmed, w.superRel = !w.superHeld(), 0
	xproto.GrabPointer(w.c, false, wid, xproto.EventMaskButtonPress|xproto.EventMaskButtonRelease|xproto.EventMaskPointerMotion,
		xproto.GrabModeAsync, xproto.GrabModeAsync, xproto.WindowNone, xproto.CursorNone, xproto.TimeCurrentTime)
	xproto.GrabKeyboard(w.c, false, wid, xproto.TimeCurrentTime, xproto.GrabModeAsync, xproto.GrabModeAsync)
	w.paintAll()
}

// whiskerOpen tells the control socket ("whisker?") whether the menu is up: Dictate then types into its search box.
var whiskerOpen atomic.Bool

// loadKeymap reads the keyboard mapping of n keycodes; also after a MappingNotify, since xdotool
// remaps a spare keycode to type characters the layout lacks (umlauts).
func (w *whisker) loadKeymap(n byte) {
	if r, err := xproto.GetKeyboardMapping(w.c, w.minKC, n).Reply(); err == nil {
		w.keymap, w.kpc = r.Keysyms, int(r.KeysymsPerKeycode)
	}
}

func (w *whisker) close() {
	if !w.isOpen {
		return
	}
	xproto.UngrabPointer(w.c, xproto.TimeCurrentTime)
	xproto.UngrabKeyboard(w.c, xproto.TimeCurrentTime)
	xproto.DestroyWindow(w.c, w.win)
	xproto.FreePixmap(w.c, w.back)
	w.isOpen = false
	whiskerOpen.Store(false)
	w.ctx = nil
}

// ---- data for the app pane ----------------------------------------------------------

func (w *whisker) entriesByIDs(ids []string) []*appmenu.Entry {
	var out []*appmenu.Entry
	for _, id := range ids {
		if e := w.byID[id]; e != nil {
			out = append(out, e)
		}
	}
	return out
}

func (w *whisker) rebuildList() {
	w.hoverRow, w.selRow, w.userSel = -1, -1, false
	if len(w.query) > 0 {
		w.scoredApps = w.search(string(w.query))
		w.hits = nil
		w.confirmID, w.ranMsg = "", ""
		if w.bc != nil {
			w.bseq = w.bc.Ask(string(w.query))
		}
		w.setRows(w.searchRows())
		w.selRow = w.firstSelectable()
		return
	}
	w.hits, w.bseq = nil, 0
	var rows []wrow
	apps := func(es []*appmenu.Entry) {
		for _, e := range es {
			rows = append(rows, wrow{kind: rowApp, e: e})
		}
	}
	switch {
	case w.catIdx == catQuick:
		apps(w.entriesByIDs(w.recentIDs))
		nRecent := len(rows)
		apps(w.entriesByIDs(w.favIDs))
		w.setPanes(rows, nRecent)
		return
	case w.catIdx == catCmds:
		for i := range w.allCmds {
			rows = append(rows, wrow{kind: rowCmd, hit: &w.allCmds[i]})
		}
		w.setRows(rows)
		w.panes[0].empty = tr("No commands available")
		return
	case w.catIdx == catAll:
		apps(w.all)
	default:
		apps(w.cats[w.catIdx-catFirstReal].Entries)
	}
	w.setRows(rows)
}

// setRows installs the rows as one pane, and the y offsets that scrolling and hit-testing use.
func (w *whisker) setRows(rows []wrow) {
	w.setPanes(rows, -1)
}

// setPanes installs the rows; split >= 0 cuts them into Recently Used (rows before split) and
// Favorites in two stacked panes of equal height.
func (w *whisker) setPanes(rows []wrow, split int) {
	w.rows = rows
	w.tops = make([]int, len(rows)+1)
	for i := range rows {
		w.tops[i+1] = w.tops[i] + whAppRowH
	}
	h := w.listHeight()
	if split < 0 {
		w.panes = []pane{{h: h, to: len(rows)}}
		return
	}
	w.panes = []pane{
		{title: tr("Recently Used"), empty: tr("No recently used applications"), y: 0, h: h / 2, to: split},
		{title: tr("Favorites"), empty: tr("No favorites yet"), y: h / 2, h: h - h/2, from: split, to: len(rows)},
	}
}

func (w *whisker) firstSelectable() int {
	if len(w.rows) > 0 {
		return 0
	}
	return -1
}

// searchRows merges the app matches with the matcher's commands: a command goes after the
// strong app matches (name equals/starts with the query) and before the weaker ones.
func (w *whisker) searchRows() []wrow {
	var cmds []wrow
	for i := range w.hits {
		// a second command only when it is nearly as good as the best one
		if h := &w.hits[i]; h.Score >= whCmdMin && len(cmds) < 2 && (len(cmds) == 0 || h.Score >= w.hits[0].Score*0.9) {
			cmds = append(cmds, wrow{kind: rowCmd, hit: h})
		}
	}
	var rows []wrow
	placed := false
	for _, a := range w.scoredApps {
		if !placed && a.s < 90 {
			rows, placed = append(rows, cmds...), true
		}
		rows = append(rows, wrow{kind: rowApp, e: a.e})
	}
	if !placed {
		rows = append(rows, cmds...)
	}
	return rows
}

// onButler takes a matcher result for the current query; older ones are dropped.
func (w *whisker) onButler(r butlerResult) {
	if r.cmdList != nil {
		w.allCmds = r.cmdList
		if w.isOpen && len(w.query) == 0 && w.catIdx == catCmds {
			w.rebuildList()
			w.paintAll()
		}
		return
	}
	if !w.isOpen {
		return
	}
	switch {
	case r.ran:
		w.ranID, w.ranMsg, w.ranOK, w.ranAt = r.id, r.reply, r.ok, time.Now()
		w.put(w.paintList(), whListX, whListTop)
		out := w.bc.out
		time.AfterFunc(1500*time.Millisecond, func() {
			select {
			case out <- butlerResult{clear: true}:
			default:
			}
		})
		return
	case r.clear:
		if w.ranMsg != "" && time.Since(w.ranAt) >= 1400*time.Millisecond {
			w.ranMsg = ""
			w.put(w.paintList(), whListX, whListTop)
		}
		return
	}
	if w.valueHit != nil || r.seq != w.bseq || len(w.query) == 0 {
		return
	}
	w.hits = r.hits
	var keep string
	if w.userSel && w.selRow >= 0 && w.selRow < len(w.rows) {
		keep = w.rows[w.selRow].key()
	}
	w.setRows(w.searchRows())
	w.selRow = w.firstSelectable()
	for i, rw := range w.rows {
		if keep != "" && rw.key() == keep {
			w.selRow = i
		}
	}
	w.put(w.paintList(), whListX, whListTop)
}

// search ranks name matches above generic name, keywords, comment and command matches.
func (w *whisker) search(q string) []scoredEntry {
	q = strings.ToLower(strings.TrimSpace(q))
	var hits []scoredEntry
	for _, e := range w.all {
		name := strings.ToLower(e.Name)
		s := 0
		switch {
		case name == q:
			s = 100
		case strings.HasPrefix(name, q):
			s = 90
		case strings.Contains(name, " "+q):
			s = 80
		case strings.Contains(name, q):
			s = 70
		case strings.Contains(strings.ToLower(e.GenericName), q):
			s = 50
		default:
			for _, k := range e.Keywords {
				if strings.Contains(strings.ToLower(k), q) {
					s = 40
					break
				}
			}
			if s == 0 && strings.Contains(strings.ToLower(e.Comment), q) {
				s = 30
			}
			if s == 0 && strings.Contains(strings.ToLower(e.Exec), q) {
				s = 20
			}
		}
		if s > 0 {
			hits = append(hits, scoredEntry{e, s})
		}
	}
	// stable by score (entries are already name-sorted)
	var out []scoredEntry
	for s := 100; s > 0; s-- {
		for _, h := range hits {
			if h.s == s {
				out = append(out, h)
			}
		}
	}
	return out
}

func (w *whisker) catCount() int { return catFirstReal + len(w.cats) }

func (w *whisker) catName(i int) string {
	switch i {
	case catQuick:
		return tr("Quickstart")
	case catCmds:
		return tr("Commands")
	case catAll:
		return tr("All Applications")
	}
	return w.cats[i-catFirstReal].Name
}

func (w *whisker) catIcon(i int) string {
	switch i {
	case catQuick:
		return "emblem-favorite"
	case catCmds:
		return "system-run"
	case catAll:
		return "applications-other"
	}
	return w.cats[i-catFirstReal].Icon
}

// ---- rendering -----------------------------------------------------------------------

func rect(img *image.RGBA, r image.Rectangle, c color.RGBA) {
	draw.Draw(img, r, image.NewUniform(c), image.Point{}, draw.Src)
}

func frame(img *image.RGBA, r image.Rectangle, c color.RGBA) {
	rect(img, image.Rect(r.Min.X, r.Min.Y, r.Max.X, r.Min.Y+1), c)
	rect(img, image.Rect(r.Min.X, r.Max.Y-1, r.Max.X, r.Max.Y), c)
	rect(img, image.Rect(r.Min.X, r.Min.Y, r.Min.X+1, r.Max.Y), c)
	rect(img, image.Rect(r.Max.X-1, r.Min.Y, r.Max.X, r.Max.Y), c)
}

func blit(img *image.RGBA, src *image.RGBA, x, y int) {
	if src == nil {
		return
	}
	b := src.Bounds()
	draw.Draw(img, image.Rect(x, y, x+b.Dx(), y+b.Dy()), src, b.Min, draw.Over)
}

func textAt(img *image.RGBA, x, y int, text string, c color.RGBA, bold bool, px float64, maxW int) {
	t := []rune(text)
	for len(t) > 0 {
		s := string(t)
		if len(t) < len([]rune(text)) {
			s += "…"
		}
		sp := []gfx.Span{{Text: s, Scale: 1, Bold: bold, Color: c}}
		if maxW <= 0 || gfx.Measure(sp, px).W <= maxW {
			gfx.Draw(img, x, y, sp, px)
			return
		}
		t = t[:len(t)-1]
	}
}

func (w *whisker) paintHeader() *image.RGBA {
	img := image.NewRGBA(image.Rect(0, 0, whW, whHeaderH))
	rect(img, img.Bounds(), whBg)
	blit(img, w.avatar, 10, 10)
	textAt(img, 52, 14, w.userName, whInk, true, 17, 300)
	for i, ic := range w.btnIcons {
		x := whW - 8 - (2-i)*44 + 8
		if i == w.hoverBtn {
			rect(img, image.Rect(x-4, 8, x+36, 44), whHover)
		}
		blit(img, ic, x+4, 14)
	}
	return img
}

func btnRect(i int) image.Rectangle {
	x := whW - 8 - (2-i)*44 + 8
	return image.Rect(x-4, 8, x+36, 44)
}

func (w *whisker) paintSearch() *image.RGBA {
	img := image.NewRGBA(image.Rect(0, 0, whW, whSearchH+4))
	rect(img, img.Bounds(), whBg)
	r := image.Rect(8, 0, whW-8, whSearchH)
	rect(img, r, color.RGBA{255, 255, 255, 255})
	frame(img, r, whFocus)
	frame(img, r.Inset(1), whFocus)
	textAt(img, 18, 7, "\U0001F50D︎", whDim, false, 14, 0)
	text := string(w.query)
	if w.valueHit != nil {
		text = w.valueSentence()
	}
	if text == "" {
		textAt(img, 40, 8, "", whDim, false, 13, 0)
	} else {
		textAt(img, 40, 8, text, whInk, false, 13, whW-80)
		tw := gfx.Measure([]gfx.Span{{Text: text, Scale: 1, Color: whInk}}, 13).W
		rect(img, image.Rect(40+min(tw, whW-80)+1, 7, 40+min(tw, whW-80)+2, 25), whInk)
	}
	if text == "" {
		rect(img, image.Rect(40, 7, 41, 25), whInk)
	}
	return img
}

func (w *whisker) listHeight() int { return whListBottom - whListTop }

func (w *whisker) paintList() *image.RGBA {
	img := image.NewRGBA(image.Rect(0, 0, whListW, w.listHeight()))
	rect(img, img.Bounds(), whListBg)
	for pi := range w.panes {
		p := &w.panes[pi]
		if p.title != "" {
			rect(img, image.Rect(0, p.y, whListW, p.cy()), whBg)
			if pi > 0 {
				rect(img, image.Rect(0, p.y, whListW, p.y+1), whBorder)
			}
			textAt(img, 12, p.y+5, p.title, whInk, true, 12, whListW-24)
		}
		draw.Draw(img, image.Rect(0, p.cy(), whListW, p.cy()+p.ch()), w.paintPane(p), image.Point{}, draw.Src)
	}
	frame(img, img.Bounds(), whBorder)
	return img
}

// paintPane draws the visible rows of one pane, with its scrollbar.
func (w *whisker) paintPane(p *pane) *image.RGBA {
	h := p.ch()
	img := image.NewRGBA(image.Rect(0, 0, whListW, h))
	rect(img, img.Bounds(), whListBg)
	base := w.tops[p.from]
	for i := p.from; i < p.to && w.tops[i]-base-p.scroll < h; i++ {
		y := w.tops[i] - base - p.scroll
		if y+whAppRowH <= 0 {
			continue
		}
		r := w.rows[i]
		switch {
		case i == w.selRow:
			rect(img, image.Rect(0, y, whListW, y+whAppRowH), whSel)
		case i == w.hoverRow:
			rect(img, image.Rect(0, y, whListW, y+whAppRowH), whHover)
		}
		if r.kind == rowCmd {
			rect(img, image.Rect(0, y, 3, y+whAppRowH), whFocus) // accent bar: this row is a command
			blit(img, w.icon("system-run", whAppIcon), 6, y+(whAppRowH-whAppIcon)/2)
			title := r.hit.Sentence
			if w.valueHit != nil && w.valueHit.ID == r.hit.ID {
				title = w.valueSentence()
			}
			textAt(img, 46, y+3, title, whInk, true, 13, whListW-56)
			sub := tr("Command") + "  ·  " + r.hit.Category
			switch {
			case w.valueHit != nil && w.valueHit.ID == r.hit.ID:
				sub = tr("Type a number, Enter runs it, Esc goes back")
			case r.hit.NeedsValue:
				sub = tr("Add a value, for example 50")
			case w.confirmID == r.hit.ID:
				sub = tr("Press Enter again to confirm")
			case w.ranID == r.hit.ID && w.ranMsg != "":
				sub = "✓  " + w.ranMsg
				if !w.ranOK {
					sub = "✗  " + w.ranMsg
				}
			}
			textAt(img, 46, y+20, sub, whDim, false, 13, whListW-56)
			continue
		}
		e := r.e
		blit(img, w.icon(e.Icon, whAppIcon), 6, y+(whAppRowH-whAppIcon)/2)
		textAt(img, 46, y+3, e.Name, whInk, true, 13, whListW-56)
		sub := e.Comment
		if sub == "" {
			sub = e.GenericName
		}
		textAt(img, 46, y+20, sub, whInk, false, 13, whListW-56)
	}
	if p.to == p.from {
		msg := p.empty
		if msg == "" {
			msg = "No applications"
		}
		textAt(img, 12, 12, msg, whDim, false, 13, 0)
	}
	w.scrollbar(img, w.tops[p.to]-base, p.scroll)
	return img
}

func (w *whisker) scrollbar(img *image.RGBA, total, scroll int) {
	h := img.Bounds().Dy()
	if total <= h {
		return
	}
	bh := max(h*h/total, 24)
	by := (h - bh) * scroll / (total - h)
	rect(img, image.Rect(img.Bounds().Dx()-9, by+2, img.Bounds().Dx()-3, by+bh-2), color.RGBA{0xb0, 0xae, 0xaa, 255})
}

func (w *whisker) catRowY(i int) int { // y within the category pane
	y := i*whCatRowH + 2
	if i >= catFirstReal {
		y += 8 // separator gap
	}
	return y - w.catScroll
}

func (w *whisker) paintCats() *image.RGBA {
	h := w.listHeight()
	img := image.NewRGBA(image.Rect(0, 0, whCatW, h))
	rect(img, img.Bounds(), whBg)
	for i := 0; i < w.catCount(); i++ {
		y := w.catRowY(i)
		if y+whCatRowH < 0 || y > h {
			continue
		}
		if i == catFirstReal {
			rect(img, image.Rect(4, y-5, whCatW-12, y-4), whSepLine)
		}
		sel := len(w.query) == 0 && i == w.catIdx
		switch {
		case sel:
			rect(img, image.Rect(0, y, whCatW-8, y+whCatRowH), whSel)
		case i == w.hoverCat:
			rect(img, image.Rect(0, y, whCatW-8, y+whCatRowH), whHover)
		}
		blit(img, w.icon(w.catIcon(i), whCatIcon), 8, y+(whCatRowH-whCatIcon)/2)
		textAt(img, 40, y+(whCatRowH-16)/2, w.catName(i), whInk, false, 13, whCatW-56)
	}
	total := w.catRowY(w.catCount()-1) + w.catScroll + whCatRowH + 8
	w.scrollbar(img, total, w.catScroll)
	return img
}

// put paints img into the back pixmap and copies just that area to the window.
func (w *whisker) put(img *image.RGBA, x, y int) {
	w.putBack(img, x, y)
	b := img.Bounds()
	w.flush(x, y, b.Dx(), b.Dy())
}

func (w *whisker) flush(x, y, wd, ht int) {
	xproto.CopyArea(w.c, xproto.Drawable(w.back), xproto.Drawable(w.win), w.gc, int16(x), int16(y), int16(x), int16(y), uint16(wd), uint16(ht))
}

func (w *whisker) putBack(img *image.RGBA, x, y int) {
	b := img.Bounds()
	buf := make([]byte, b.Dx()*b.Dy()*4)
	for i := 0; i < b.Dx()*b.Dy(); i++ {
		p := img.Pix[i*4:]
		buf[i*4], buf[i*4+1], buf[i*4+2] = p[2], p[1], p[0]
	}
	putBGRX(w.c, xproto.Drawable(w.back), w.gc, w.scr.RootDepth, x, y, b.Dx(), b.Dy(), buf)
}

func (w *whisker) paintAll() {
	bg := image.NewRGBA(image.Rect(0, 0, whW, whH))
	rect(bg, bg.Bounds(), whBg)
	frame(bg, bg.Bounds(), whBorder)
	w.putBack(bg, 0, 0)
	w.putBack(w.paintHeader(), 0, 0)
	w.putBack(w.paintSearch(), 0, whSearchY)
	w.putBack(w.paintList(), whListX, whListTop)
	w.putBack(w.paintCats(), whCatX, whListTop)
	w.flush(0, 0, whW, whH) // one copy, so the user never sees a half-painted frame
	go FlushIconCache()
}

// ---- input ---------------------------------------------------------------------------

func (w *whisker) launch(e *appmenu.Entry) {
	l := &launcher{exec: e.Exec, dir: e.Path, term: e.Terminal, name: e.Name}
	run(l.command())
	noticeStart(l.name)
	w.noteRecent(e.ID)
	w.close()
}

// valueSentence is the asking command's sentence with the typed digits in place of the dots.
func (w *whisker) valueSentence() string {
	v := string(w.valueBuf)
	if v == "" {
		v = "…"
	}
	return strings.Replace(w.valueHit.Sentence, "…", v, 1)
}

// valueKey handles typing while a command asks for its number: digits, BackSpace, Enter, Esc.
func (w *whisker) valueKey(ks xproto.Keysym) {
	digit := -1
	switch {
	case ks >= '0' && ks <= '9':
		digit = int(ks - '0')
	case ks >= 0xffb0 && ks <= 0xffb9: // keypad
		digit = int(ks - 0xffb0)
	}
	switch {
	case ks == 0xff1b: // Escape: back to the search text
		w.valueHit, w.valueBuf = nil, nil
	case ks == 0xff08: // BackSpace: leave when nothing is left to delete
		if len(w.valueBuf) == 0 {
			w.valueHit = nil
		} else {
			w.valueBuf = w.valueBuf[:len(w.valueBuf)-1]
		}
	case ks == 0xff0d || ks == 0xff8d: // Return
		if len(w.valueBuf) == 0 {
			return
		}
		// the server reads the number from the sentence, like any typed command
		id := w.valueHit.ID
		text := w.valueSentence()
		if len(w.query) > 0 {
			text = strings.TrimSpace(string(w.query)) + " " + string(w.valueBuf) + "%"
		}
		w.valueHit, w.valueBuf = nil, nil
		if len(w.query) > 0 { // the search box now shows the full sentence: Enter repeats it, editing changes it
			w.query = []rune(text)
			w.rebuildList()
		}
		w.ranID = id
		if w.bc != nil {
			w.bc.Run(id, text)
		}
	case digit >= 0 && len(w.valueBuf) < 3:
		w.valueBuf = append(w.valueBuf, rune('0'+digit))
	}
	w.paintAll()
}

// runCommand runs a matcher command. Commands that need a value or a second Enter stay open.
func (w *whisker) runCommand(h *butlerHit) {
	if h.NeedsValue {
		hit := *h
		w.valueHit, w.valueBuf = &hit, nil
		w.paintAll()
		return
	}
	if h.Confirm && w.confirmID != h.ID {
		w.confirmID = h.ID
		w.put(w.paintList(), whListX, whListTop)
		return
	}
	// the menu stays open: run it again, or edit the sentence
	w.confirmID, w.ranMsg = "", ""
	w.ranID = h.ID
	if w.bc != nil {
		w.bc.Run(h.ID, string(w.query))
	}
}

// activate runs the row: launches the app or runs the command.
func (w *whisker) activate(i int) {
	if i < 0 || i >= len(w.rows) {
		return
	}
	switch r := w.rows[i]; r.kind {
	case rowApp:
		w.launch(r.e)
	case rowCmd:
		w.runCommand(r.hit)
	}
}

// moveSel moves the keyboard selection by d rows, skipping section headers.
func (w *whisker) moveSel(d int) {
	if len(w.rows) == 0 {
		return
	}
	step := 1
	if d < 0 {
		step = -1
	}
	i := w.selRow
	if i < 0 {
		i = -1
		if d < 0 {
			i = len(w.rows)
		}
	}
	for n := 0; n < absInt(d); n++ {
		j := i + step
		if j < 0 || j >= len(w.rows) {
			break
		}
		i = j
	}
	if i < 0 || i >= len(w.rows) {
		i = w.firstSelectable()
	}
	w.selRow, w.userSel = i, true
	if i >= 0 {
		w.ensureVisible(i)
	}
	w.put(w.paintList(), whListX, whListTop)
}

func absInt(n int) int {
	if n < 0 {
		return -n
	}
	return n
}

func (w *whisker) noteRecent(id string) {
	max := 10
	if v := w.prop("recent-items-max"); len(v) == 1 {
		if n := atoi(v, 10); n > 0 {
			max = n
		}
	}
	ids := []string{id}
	for _, r := range w.recentIDs {
		if r != id && len(ids) < max {
			ids = append(ids, r)
		}
	}
	w.recentIDs = ids
	go setXfconfArray("/plugins/plugin-"+whiskerID+"/recent", ids)
}

// setXfconfArray stores a string array property in xfce4-panel's channel.
func setXfconfArray(prop string, vals []string) {
	args := []string{"-c", "xfce4-panel", "-p", prop, "-n", "-a"}
	for _, v := range vals {
		args = append(args, "-t", "string", "-s", v)
	}
	exec.Command("xfconf-query", args...).Run()
}

// paneAtY is the pane under window y, or -1.
func (w *whisker) paneAtY(py int) int {
	rel := py - whListTop
	for i, p := range w.panes {
		if rel >= p.y && rel < p.y+p.h {
			return i
		}
	}
	return -1
}

// listRowAt is the row under window y, or -1 (pane titles are not rows).
func (w *whisker) listRowAt(py int) int {
	pi := w.paneAtY(py)
	if pi < 0 {
		return -1
	}
	p := w.panes[pi]
	rel := py - whListTop
	if rel < p.cy() {
		return -1
	}
	off := rel - p.cy() + p.scroll
	for i := p.from; i < p.to; i++ {
		if off < w.tops[i+1]-w.tops[p.from] {
			return i
		}
	}
	return -1
}

func (w *whisker) catAtY(py int) int {
	for i := 0; i < w.catCount(); i++ {
		y := w.catRowY(i) + whListTop
		if py >= y && py < y+whCatRowH {
			return i
		}
	}
	return -1
}

// scrollbarPane is the pane whose scrollbar strip is under window (px, py), or -1.
func (w *whisker) scrollbarPane(px, py int) int {
	if px < whListX+whListW-16 || px >= whListX+whListW {
		return -1
	}
	pi := w.paneAtY(py)
	if pi < 0 || py-whListTop < w.panes[pi].cy() || w.tops[w.panes[pi].to]-w.tops[w.panes[pi].from] <= w.panes[pi].ch() {
		return -1
	}
	return pi
}

// thumb is the scrollbar thumb of pane pi: its height and top (the same maths as scrollbar()).
func (w *whisker) thumb(pi int) (bh, top int) {
	p := w.panes[pi]
	h, total := p.ch(), w.tops[p.to]-w.tops[p.from]
	bh = max(h*h/total, 24)
	return bh, (h - bh) * p.scroll / (total - h)
}

// dragStart grabs the thumb where it was hit, or centres it on the pointer when the click was beside it.
func (w *whisker) dragStart(pi, py int) {
	bh, top := w.thumb(pi)
	rel := py - whListTop - w.panes[pi].cy()
	w.dragging, w.dragPane, w.dragOff = true, pi, bh/2
	if rel >= top && rel < top+bh {
		w.dragOff = rel - top
		return
	}
	w.dragScroll(pi, py)
}

// catTick opens the hovered category when the pointer has rested on it since the timer started.
func (w *whisker) catTick(tok int) {
	if !w.isOpen || tok != w.catToken || w.hoverCat < 0 || len(w.query) > 0 || w.hoverCat == w.catIdx {
		return
	}
	w.catIdx = w.hoverCat
	w.rebuildList()
	w.put(w.paintList(), whListX, whListTop)
	w.put(w.paintCats(), whCatX, whListTop)
}

// dragTick repaints for the latest pointer position at most every 16 ms. Painting the list takes
// longer than the pointer needs to send motion events, and handling every one lags behind the mouse.
func (w *whisker) dragTick() {
	if !w.dragging || !w.isOpen {
		w.dragTimer = false
		return
	}
	if wait := 16*time.Millisecond - time.Since(w.dragAt); wait > 0 {
		if !w.dragTimer {
			w.dragTimer = true
			time.AfterFunc(wait, func() { ctlCmds <- "whisker-drag" })
		}
		return
	}
	w.dragTimer = false
	w.dragAt = time.Now()
	w.dragScroll(w.dragPane, w.dragY)
}

// dragScroll moves the thumb of pane pi so it follows window y.
func (w *whisker) dragScroll(pi, py int) {
	p := &w.panes[pi]
	h, total := p.ch(), w.tops[p.to]-w.tops[p.from]
	bh, _ := w.thumb(pi)
	rel := py - whListTop - p.cy() - w.dragOff
	p.scroll = 0
	w.scrollPane(pi, (total-h)*min(max(rel, 0), h-bh)/(h-bh))
	w.put(w.paintList(), whListX, whListTop)
}

func (w *whisker) scrollPane(pi, delta int) {
	if pi < 0 {
		return
	}
	p := &w.panes[pi]
	maxScroll := max(w.tops[p.to]-w.tops[p.from]-p.ch(), 0)
	p.scroll = min(max(p.scroll+delta, 0), maxScroll)
}

func (w *whisker) scrollCats(delta int) {
	total := w.catCount()*whCatRowH + 12
	w.catScroll = min(max(w.catScroll+delta, 0), max(total-w.listHeight(), 0))
}

func (w *whisker) ensureVisible(row int) {
	for pi := range w.panes {
		p := &w.panes[pi]
		if row < p.from || row >= p.to {
			continue
		}
		top, bot := w.tops[row]-w.tops[p.from], w.tops[row+1]-w.tops[p.from]
		if top < p.scroll {
			p.scroll = top
		} else if bot > p.scroll+p.ch() {
			p.scroll = bot - p.ch()
		}
		return
	}
}

func (w *whisker) runButton(i int) {
	cmd := ""
	switch i {
	case 0:
		cmd = w.cmdFromCfg("command-lockscreen", "xflock4")
	case 1:
		cmd = w.cmdFromCfg("command-logout", "xfce4-session-logout")
	}
	w.close()
	if cmd != "" {
		run(shell(cmd))
	}
}

// keysymFor translates a key press using the server's keyboard mapping.
func (w *whisker) keysymFor(code xproto.Keycode, state uint16) xproto.Keysym {
	if w.kpc == 0 {
		return 0
	}
	base := int(code-w.minKC) * w.kpc
	col := 0
	if state&0x80 != 0 && w.kpc > 4 { // Mod5: ISO_Level3_Shift (AltGr)
		col = 4
	}
	if state&1 != 0 {
		col++
	}
	if base+col >= len(w.keymap) || w.keymap[base+col] == 0 {
		col &^= 1
	}
	ks := w.keymap[base+col]
	if state&2 != 0 && state&1 == 0 && col == 0 && ks >= 'a' && ks <= 'z' { // CapsLock
		ks -= 32
	}
	return ks
}

func (w *whisker) key(code xproto.Keycode, state uint16) {
	ks := w.keysymFor(code, state)
	if w.valueHit != nil {
		w.valueKey(ks)
		return
	}
	if w.ctx != nil {
		w.closeCtx()
		if ks == 0xff1b {
			return
		}
	}
	switch ks {
	case 0xff1b: // Escape
		if len(w.query) > 0 {
			w.query = nil
			w.rebuildList()
			w.paintAll()
		} else {
			w.close()
		}
		return
	case 0xff08: // BackSpace
		if len(w.query) > 0 {
			w.query = w.query[:len(w.query)-1]
			w.rebuildList()
			w.paintAll()
		}
		return
	case 0xff0d, 0xff8d: // Return
		if w.selRow >= 0 && w.selRow < len(w.rows) {
			w.activate(w.selRow)
		} else if len(w.query) > 0 {
			w.activate(w.firstSelectable())
		}
		return
	case 0xff54, 0xff52: // Down, Up
		if ks == 0xff52 {
			w.moveSel(-1)
		} else {
			w.moveSel(1)
		}
		return
	case 0xff55, 0xff56: // Page Up/Down
		d := w.listHeight() / whAppRowH
		if ks == 0xff55 {
			d = -d
		}
		w.moveSel(d)
		return
	}
	var r rune
	switch {
	case ks >= 0x20 && ks <= 0x7e, ks >= 0xa0 && ks <= 0xff:
		r = rune(ks)
	case ks&0xff000000 == 0x01000000:
		r = rune(ks & 0xffffff)
	}
	if r != 0 {
		w.query = append(w.query, r)
		w.rebuildList()
		w.paintAll()
	}
}

// handle consumes events while the menu is open.
func (w *whisker) handle(ev xgb.Event) bool {
	if !w.isOpen {
		return false
	}
	switch e := ev.(type) {
	case xproto.ExposeEvent:
		if e.Window == w.win {
			if e.Count == 0 {
				w.flush(0, 0, whW, whH) // the back pixmap is always current; no repaint
			}
			return true
		}
	case xproto.KeyReleaseEvent:
		if w.isSuper(e.Detail) {
			w.superArmed, w.superRel = true, e.Time
		}
		return true
	case xproto.MappingNotifyEvent:
		if w.keymap != nil {
			setup := xproto.Setup(w.c)
			w.loadKeymap(byte(setup.MaxKeycode-setup.MinKeycode) + 1)
		}
		return true
	case xproto.KeyPressEvent:
		if w.isSuper(e.Detail) {
			if w.superArmed && e.Time != w.superRel {
				w.close() // the Windows key toggles the menu
			}
			return true
		}
		w.key(e.Detail, e.State)
		return true
	case xproto.MotionNotifyEvent:
		w.motion(int(e.RootX)-w.x, int(e.RootY)-w.y)
		return true
	case xproto.ButtonPressEvent:
		w.press(int(e.RootX)-w.x, int(e.RootY)-w.y, int(e.Detail))
		return true
	case xproto.ButtonReleaseEvent:
		w.dragging = false
		return true
	}
	return false
}

func (w *whisker) motion(px, py int) {
	if px < 0 || py < 0 || px >= whW || py >= whH {
		return
	}
	if c := w.ctx; c != nil {
		h := -1
		if px >= c.x && px < c.x+c.w && py >= c.y+3 && py < c.y+c.h-3 {
			h = (py - c.y - 3) / ctxRowH
		}
		if h != c.hover {
			c.hover = h
			w.paintCtx()
		}
		return
	}
	if w.dragging {
		w.dragY = py
		w.dragTick()
		return
	}
	row, cat, btn := -1, -1, -1
	switch {
	case py < whHeaderH:
		for i := range w.btnIcons {
			if image.Pt(px, py).In(btnRect(i)) {
				btn = i
			}
		}
	case px >= whListX && px < whListX+whListW && py >= whListTop && py < whListBottom:
		row = w.listRowAt(py)
	case px >= whCatX && px < whCatX+whCatW && py >= whListTop && py < whListBottom:
		cat = w.catAtY(py)
	}
	if btn != w.hoverBtn {
		w.hoverBtn = btn
		w.put(w.paintHeader(), 0, 0)
	}
	if row != w.hoverRow {
		w.hoverRow = row
		if row >= 0 {
			w.selRow, w.userSel = row, true
		}
		w.put(w.paintList(), whListX, whListTop)
	}
	if cat != w.hoverCat {
		w.hoverCat = cat
		hs := true
		if v := w.prop("hover-switch-category"); len(v) == 1 && v[0] == "false" {
			hs = false
		}
		w.catToken++
		if cat >= 0 && hs && len(w.query) == 0 && cat != w.catIdx {
			// opens only after the pointer rested here: crossing categories on the way to the list must not switch
			tok := w.catToken
			time.AfterFunc(whCatHover, func() { ctlCmds <- "whisker-cat:" + strconv.Itoa(tok) })
		}
		w.put(w.paintCats(), whCatX, whListTop)
	}
}

func (w *whisker) press(px, py, btn int) {
	if px < 0 || py < 0 || px >= whW || py >= whH {
		w.close() // click outside
		return
	}
	if w.ctx != nil {
		w.ctxPress(px, py, btn)
		return
	}
	inList := px >= whListX && px < whListX+whListW && py >= whListTop && py < whListBottom
	inCats := px >= whCatX && px < whCatX+whCatW && py >= whListTop && py < whListBottom
	switch btn {
	case 4, 5:
		d := -3 * whAppRowH
		if btn == 5 {
			d = -d
		}
		if inCats {
			w.scrollCats(d / 2)
			w.put(w.paintCats(), whCatX, whListTop)
		} else {
			w.scrollPane(w.paneAtY(py), d)
			w.hoverRow = w.listRowAt(py)
			w.put(w.paintList(), whListX, whListTop)
		}
	case 3:
		if inList {
			if r := w.listRowAt(py); r >= 0 {
				if w.rows[r].kind == rowApp {
					w.openCtx(px, py, w.rows[r].e)
				}
			}
		}
	case 1:
		switch {
		case py < whHeaderH:
			for i := range w.btnIcons {
				if image.Pt(px, py).In(btnRect(i)) {
					w.runButton(i)
					return
				}
			}
		case inList && w.scrollbarPane(px, py) >= 0:
			w.dragStart(w.scrollbarPane(px, py), py)
		case inList:
			if r := w.listRowAt(py); r >= 0 {
				w.activate(r)
			}
		case inCats:
			if c := w.catAtY(py); c >= 0 {
				w.query = nil
				w.catIdx = c
				w.rebuildList()
				w.paintAll()
			}
		}
	}
}

// whiskerCtx is the small right-click menu of an application row. It is painted inside
// the Whisker window (the pointer grab is ours, a separate popup would fight over it).
type whiskerCtx struct {
	x, y, w, h int
	e          *appmenu.Entry
	labels     []string
	hover      int
}

const ctxRowH = 26

func (w *whisker) isFavorite(id string) bool {
	for _, f := range w.favIDs {
		if f == id {
			return true
		}
	}
	return false
}

func (w *whisker) openCtx(px, py int, e *appmenu.Entry) {
	fav := tr("Add to Favorites")
	if w.isFavorite(e.ID) {
		fav = tr("Remove from Favorites")
	}
	c := &whiskerCtx{e: e, labels: []string{fav, tr("Add to Desktop")}, hover: -1}
	for _, l := range c.labels {
		c.w = max(c.w, textWidth(l, 13)+28)
	}
	c.h = len(c.labels)*ctxRowH + 6
	c.x = min(px, whW-c.w-2)
	c.y = min(py, whH-c.h-2)
	w.ctx = c
	w.paintCtx()
}

func (w *whisker) closeCtx() {
	if w.ctx != nil {
		w.ctx = nil
		w.paintAll()
	}
}

func (w *whisker) paintCtx() {
	c := w.ctx
	img := image.NewRGBA(image.Rect(0, 0, c.w, c.h))
	rect(img, img.Bounds(), whBg)
	frame(img, img.Bounds(), whBorder)
	for i, l := range c.labels {
		y := 3 + i*ctxRowH
		ink := whInk
		if i == c.hover {
			rect(img, image.Rect(2, y, c.w-2, y+ctxRowH), menuHilite)
			ink = menuWhite
		}
		textAt(img, 14, y+5, l, ink, false, 13, 0)
	}
	w.put(img, c.x, c.y)
}

// ctxPress handles a click while the context menu is open; always consumes it.
func (w *whisker) ctxPress(px, py, btn int) {
	c := w.ctx
	if btn == 1 && px >= c.x && px < c.x+c.w && py >= c.y+3 && py < c.y+c.h-3 {
		i := (py - c.y - 3) / ctxRowH
		if i >= 0 && i < len(c.labels) {
			w.ctx = nil
			w.ctxAction(c.e, i)
			return
		}
	}
	w.closeCtx()
}

func (w *whisker) ctxAction(e *appmenu.Entry, i int) {
	switch i {
	case 0:
		var ids []string
		if w.isFavorite(e.ID) {
			for _, f := range w.favIDs {
				if f != e.ID {
					ids = append(ids, f)
				}
			}
		} else {
			ids = append(append(ids, w.favIDs...), e.ID)
		}
		w.favIDs = ids
		go setXfconfArray("/plugins/plugin-"+whiskerID+"/favorites", ids)
		if len(w.query) == 0 && w.catIdx == catQuick {
			w.rebuildList()
		}
	case 1:
		home, _ := os.UserHomeDir()
		dst := filepath.Join(home, "Desktop", filepath.Base(e.File))
		if data, err := os.ReadFile(e.File); err == nil {
			os.MkdirAll(filepath.Dir(dst), 0o755)
			os.WriteFile(dst, data, 0o755)
		}
	}
	w.paintAll()
}

func textWidth(s string, px float64) int {
	return gfx.Measure([]gfx.Span{{Text: s, Scale: 1, Color: whInk}}, px).W
}

func (w *whisker) isSuper(code xproto.Keycode) bool {
	i := int(code-w.minKC) * w.kpc
	if w.kpc == 0 || i < 0 || i >= len(w.keymap) {
		return false
	}
	ks := w.keymap[i]
	return ks == 0xffeb || ks == 0xffec // Super_L, Super_R
}

// superHeld reports whether a Super key is physically down right now (the menu was
// probably opened by it, and that press must not close it again).
func (w *whisker) superHeld() bool {
	r, err := xproto.QueryKeymap(w.c).Reply()
	if err != nil {
		return false
	}
	for code := int(w.minKC); code < 256; code++ {
		if r.Keys[code/8]&(1<<(code%8)) != 0 && w.isSuper(xproto.Keycode(code)) {
			return true
		}
	}
	return false
}
