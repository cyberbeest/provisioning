package main

import (
	"bufio"
	"gopanel/appmenu"
	"image"
	"image/draw"
	_ "image/png"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"

	"github.com/srwiley/oksvg"
	"github.com/srwiley/rasterx"
	xdraw "golang.org/x/image/draw"
)

type launcher struct {
	name    string
	comment string
	exec    string
	dir     string
	term    bool
	img     *image.RGBA
}

var fieldCode = regexp.MustCompile(`%[fFuUdDnNickvm]`)

func (l *launcher) command() *exec.Cmd {
	line := strings.ReplaceAll(fieldCode.ReplaceAllString(l.exec, ""), "%%", "%")
	if l.term {
		line = "exec xfce4-terminal -x sh -c " + shQuote(line)
	}
	cmd := exec.Command("sh", "-c", "exec "+line)
	cmd.Dir = l.dir
	return cmd
}

func shQuote(s string) string { return "'" + strings.ReplaceAll(s, "'", `'\''`) + "'" }

// xfconfAll dumps the whole xfce4-panel channel with a single xfconf-query call.
// Arrays are printed as "[a,b,c]"; they come back as slices, scalars as one element.
func xfconfAll() map[string][]string {
	out, err := exec.Command("xfconf-query", "-c", "xfce4-panel", "-lv").Output()
	if err != nil {
		return nil
	}
	m := map[string][]string{}
	for _, ln := range strings.Split(string(out), "\n") {
		f := strings.Fields(ln)
		if len(f) < 2 {
			continue
		}
		v := strings.Join(f[1:], " ")
		if strings.HasPrefix(v, "[") && strings.HasSuffix(v, "]") {
			m[f[0]] = strings.Split(v[1:len(v)-1], ",")
		} else {
			m[f[0]] = []string{v}
		}
	}
	return m
}

func parseDesktop(path string) (*launcher, string) {
	f, err := os.Open(path)
	if err != nil {
		return nil, ""
	}
	defer f.Close()
	l := &launcher{}
	icon := ""
	inEntry := false
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		ln := strings.TrimSpace(sc.Text())
		if strings.HasPrefix(ln, "[") {
			inEntry = ln == "[Desktop Entry]"
			continue
		}
		k, v, ok := strings.Cut(ln, "=")
		if !inEntry || !ok {
			continue
		}
		switch k { // unlocalised keys only
		case "Name":
			l.name = v
		case "Comment":
			l.comment = v
		case "Exec":
			l.exec = v
		case "Icon":
			icon = v
		case "Path":
			l.dir = v
		case "Terminal":
			l.term = v == "true"
		}
	}
	if l.exec == "" {
		return nil, ""
	}
	return l, icon
}

type iconDir struct {
	path     string
	rank     int // position of its theme in the lookup chain (0 = active theme)
	size     int
	scalable bool
}

var (
	iconDirsOnce   sync.Once
	iconDirList    []iconDir
	iconCacheOnce  sync.Once
	iconCacheDirty bool
	iconCacheMu    sync.Mutex
	iconCache      = map[string][]string{}
)

func themeBases() []string {
	home, _ := os.UserHomeDir()
	return []string{filepath.Join(home, ".local/share/icons"), "/usr/share/icons"}
}

// themeChain is the active icon theme, then what it inherits, then hicolor, then a few
// well-stocked themes as a last resort for names the chain lacks.
func themeChain() []string {
	active := "Tango"
	if out, err := exec.Command("xfconf-query", "-c", "xsettings", "-p", "/Net/IconThemeName").Output(); err == nil {
		if s := strings.TrimSpace(string(out)); s != "" {
			active = s
		}
	}
	var chain []string
	seen := map[string]bool{}
	var add func(string, int)
	add = func(name string, depth int) {
		if name == "" || seen[name] || depth > 6 {
			return
		}
		seen[name] = true
		chain = append(chain, name)
		for _, base := range themeBases() {
			if g := appmenu.ReadGroup(filepath.Join(base, name, "index.theme"), "Icon Theme"); g != nil {
				for _, p := range strings.Split(g["Inherits"], ",") {
					add(strings.TrimSpace(p), depth+1)
				}
				return
			}
		}
	}
	add(active, 0)
	for _, t := range []string{"hicolor", "Adwaita", "gnome", "oxygen", "breeze"} {
		add(t, 0)
	}
	return chain
}

// dirSize guesses the pixel size of an icon directory from its path ("48x48", "24", "scalable").
func dirSize(rel string) (size int, scalable bool) {
	for _, part := range strings.Split(rel, "/") {
		if part == "scalable" || part == "symbolic" {
			scalable = true
		}
		if a, _, ok := strings.Cut(part, "x"); ok {
			if n, err := strconv.Atoi(a); err == nil {
				size = n
			}
		} else if n, err := strconv.Atoi(part); err == nil {
			size = n
		}
	}
	return
}

// buildIconDirs lists the directories of every theme in the chain once (directories only,
// at most three levels below a theme root), so a lookup is a handful of stats, not globs.
func buildIconDirs() {
	for rank, th := range themeChain() {
		for _, base := range themeBases() {
			root := filepath.Join(base, th)
			filepath.WalkDir(root, func(p string, de os.DirEntry, err error) error {
				if err != nil || !de.IsDir() {
					return nil
				}
				rel, _ := filepath.Rel(root, p)
				if rel == "." {
					return nil
				}
				depth := strings.Count(rel, "/") + 1
				if depth > 3 {
					return filepath.SkipDir
				}
				if depth >= 2 {
					sz, sc := dirSize(rel)
					iconDirList = append(iconDirList, iconDir{p, rank, sz, sc})
				}
				return nil
			})
		}
	}
}

// findIcons returns candidate files for an Icon= value, best first: themes earlier in the
// chain win; within a theme an exact size beats a larger one beats scalable (our SVG
// renderer is weak) beats a smaller one.
func findIcons(name string, size int) []string {
	if filepath.IsAbs(name) {
		return []string{name}
	}
	iconCacheOnce.Do(loadIconCache)
	key := name + "@" + strconv.Itoa(size)
	iconCacheMu.Lock()
	if p, ok := iconCache[key]; ok {
		iconCacheMu.Unlock()
		return p
	}
	iconCacheMu.Unlock()
	iconDirsOnce.Do(buildIconDirs)
	type cand struct {
		path        string
		rank, score int
	}
	var cs []cand
	for _, d := range iconDirList {
		for _, ext := range [2]string{".png", ".svg"} {
			p := filepath.Join(d.path, name+ext)
			if _, err := os.Stat(p); err != nil {
				continue
			}
			sc := 0
			switch {
			case ext == ".svg" || d.scalable:
				sc = 20000
			case d.size == size:
				sc = 100000
			case d.size > size:
				sc = 50000 - d.size
			default:
				sc = d.size
			}
			cs = append(cs, cand{p, d.rank, sc})
		}
	}
	sort.SliceStable(cs, func(i, j int) bool {
		if cs[i].rank != cs[j].rank {
			return cs[i].rank < cs[j].rank
		}
		return cs[i].score > cs[j].score
	})
	var out []string
	for _, c := range cs {
		if len(out) < 4 {
			out = append(out, c.path)
		}
	}
	if len(out) == 0 {
		for _, ext := range []string{"png", "svg"} {
			if p := "/usr/share/pixmaps/" + name + "." + ext; fileExists(p) {
				out = append(out, p)
				break
			}
		}
	}
	iconCacheMu.Lock()
	iconCache[key] = out
	iconCacheDirty = true
	iconCacheMu.Unlock()
	return out
}

func findIcon(name string) string {
	if c := findIcons(name, iconSize); len(c) > 0 {
		return c[0]
	}
	return ""
}

// The resolved-path cache lives on disk and is valid while the package database and the
// user icon dir are unchanged: a first menu open is slow (every icon walks ~1000 theme
// directories), later ones are instant.
func iconCacheStamp() string {
	home, _ := os.UserHomeDir()
	var stamp []string
	for _, p := range []string{"/var/lib/dpkg/status", filepath.Join(home, ".local/share/icons")} {
		if st, err := os.Stat(p); err == nil {
			stamp = append(stamp, strconv.FormatInt(st.ModTime().Unix(), 10))
		}
	}
	return "# v2 " + strings.Join(stamp, " ")
}

func iconCachePath() string {
	d := os.Getenv("XDG_CACHE_HOME")
	if d == "" {
		home, _ := os.UserHomeDir()
		d = filepath.Join(home, ".cache")
	}
	return filepath.Join(d, "gopanel", "icon-paths.tsv")
}

func loadIconCache() {
	b, err := os.ReadFile(iconCachePath())
	if err != nil {
		return
	}
	lines := strings.Split(string(b), "\n")
	if len(lines) == 0 || lines[0] != iconCacheStamp() {
		return
	}
	for _, ln := range lines[1:] {
		f := strings.Split(ln, "\t")
		if len(f) >= 1 && f[0] != "" {
			var paths []string
			for _, p := range f[1:] {
				if p != "" {
					paths = append(paths, p)
				}
			}
			iconCache[f[0]] = paths
		}
	}
}

// FlushIconCache writes new lookups to disk (call after a burst of lookups).
func FlushIconCache() {
	iconCacheMu.Lock()
	defer iconCacheMu.Unlock()
	if !iconCacheDirty {
		return
	}
	var sb strings.Builder
	sb.WriteString(iconCacheStamp() + "\n")
	for k, v := range iconCache {
		sb.WriteString(k + "\t" + strings.Join(v, "\t") + "\n")
	}
	p := iconCachePath()
	os.MkdirAll(filepath.Dir(p), 0o755)
	os.WriteFile(p, []byte(sb.String()), 0o644)
	iconCacheDirty = false
}

func fileExists(p string) bool { _, err := os.Stat(p); return err == nil }

func loadIcon(name string) *image.RGBA {
	if !strings.HasSuffix(name, "-symbolic") {
		return loadIconSized(name, iconSize)
	}
	// GTK resolves symbolic icons from Adwaita before hicolor, and the provisioned
	// panel overrides some there (padded volume icon, see 12-xfce-panel-layout.sh).
	var img *image.RGBA
	for _, base := range themeBases() {
		if img = loadIconFile(filepath.Join(base, "Adwaita/symbolic/status", name+".svg"), iconSize); img != nil {
			break
		}
	}
	if img == nil {
		img = loadIconSized(name, iconSize)
	}
	tintSymbolic(img)
	return img
}

// tintSymbolic recolours a symbolic icon (a mask: only alpha matters) to the dark
// foreground GTK would use on the light panel. Some themes ship the mask in light
// grey (#bebebe, for dark themes), which would render as a washed-out icon.
func tintSymbolic(img *image.RGBA) {
	const r, g, b = 0x2e, 0x34, 0x36
	for i := 0; i+3 < len(img.Pix); i += 4 {
		a := uint32(img.Pix[i+3])
		img.Pix[i], img.Pix[i+1], img.Pix[i+2] = byte(r*a/255), byte(g*a/255), byte(b*a/255)
	}
}

func loadIconSized(name string, size int) *image.RGBA {
	for _, p := range findIcons(name, size) {
		if img := loadIconFile(p, size); img != nil {
			return img
		}
	}
	log.Println("icon not found:", name)
	return image.NewRGBA(image.Rect(0, 0, size, size))
}

// loadIconFile decodes one icon file scaled into a size x size box; nil if it fails.
func loadIconFile(p string, size int) *image.RGBA {
	f, err := os.Open(p)
	if err != nil {
		return nil
	}
	defer f.Close()
	dst := image.NewRGBA(image.Rect(0, 0, size, size))
	if strings.HasSuffix(p, ".svg") {
		ic, err := oksvg.ReadIconStream(f)
		if err != nil {
			return nil
		}
		ic.SetTarget(0, 0, float64(size), float64(size))
		ic.Draw(rasterx.NewDasher(size, size, rasterx.NewScannerGV(size, size, dst, dst.Bounds())), 1)
		return dst
	}
	src, _, err := image.Decode(f)
	if err != nil {
		return nil
	}
	sb := src.Bounds()
	w, h := size, size
	if sb.Dx() > sb.Dy() {
		h = max(sb.Dy()*size/sb.Dx(), 1)
	} else if sb.Dy() > sb.Dx() {
		w = max(sb.Dx()*size/sb.Dy(), 1)
	}
	xdraw.CatmullRom.Scale(dst, image.Rect((size-w)/2, (size-h)/2, (size-w)/2+w, (size-h)/2+h), src, sb, draw.Over, nil)
	return dst
}
