package main

import (
	"bufio"
	"image"
	"image/draw"
	_ "image/png"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"

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

var iconThemes = []string{"Tango", "gnome", "Adwaita", "hicolor", "oxygen"}

// findIcon resolves an Icon= value: absolute path, or a themed name searched
// across the theme dirs. Prefers SVG, else the smallest PNG >= iconSize, else the largest.
func findIcon(name string) string {
	if filepath.IsAbs(name) {
		return name
	}
	home, _ := os.UserHomeDir()
	bases := []string{filepath.Join(home, ".local/share/icons"), "/usr/share/icons"}
	best, bestScore := "", -1
	for _, base := range bases {
		for _, th := range iconThemes {
			for _, ext := range []string{"svg", "png"} {
				ms, _ := filepath.Glob(filepath.Join(base, th, "*", "*", name+"."+ext))
				ms2, _ := filepath.Glob(filepath.Join(base, th, "*", name+"."+ext))
				for _, m := range append(ms, ms2...) {
					sc := iconScore(m)
					if sc > bestScore {
						best, bestScore = m, sc
					}
				}
			}
		}
	}
	if best == "" {
		for _, ext := range []string{"png", "svg"} {
			if p := "/usr/share/pixmaps/" + name + "." + ext; fileExists(p) {
				return p
			}
		}
	}
	return best
}

func fileExists(p string) bool { _, err := os.Stat(p); return err == nil }

func iconScore(p string) int {
	if strings.HasSuffix(p, ".svg") {
		return 10000
	}
	sz := 0
	for _, part := range strings.Split(p, "/") {
		if a, _, ok := strings.Cut(part, "x"); ok {
			if n, err := strconv.Atoi(a); err == nil {
				sz = n
			}
		}
	}
	if sz >= iconSize {
		return 5000 - sz
	}
	return sz
}

func loadIcon(name string) *image.RGBA { return loadIconSized(name, iconSize) }

func loadIconSized(name string, size int) *image.RGBA {
	dst := image.NewRGBA(image.Rect(0, 0, size, size))
	p := findIcon(name)
	if p == "" {
		log.Println("icon not found:", name)
		return dst
	}
	f, err := os.Open(p)
	if err != nil {
		return dst
	}
	defer f.Close()
	if strings.HasSuffix(p, ".svg") {
		ic, err := oksvg.ReadIconStream(f)
		if err != nil {
			log.Println(p, err)
			return dst
		}
		ic.SetTarget(0, 0, float64(size), float64(size))
		ic.Draw(rasterx.NewDasher(size, size, rasterx.NewScannerGV(size, size, dst, dst.Bounds())), 1)
		return dst
	}
	src, _, err := image.Decode(f)
	if err != nil {
		log.Println(p, err)
		return dst
	}
	xdraw.CatmullRom.Scale(dst, dst.Bounds(), src, src.Bounds(), draw.Over, nil)
	return dst
}
