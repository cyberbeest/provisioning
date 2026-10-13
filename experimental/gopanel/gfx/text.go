// Package gfx renders text (with a tiny subset of Pango markup) into RGBA images.
// Pure Go: glyph outlines from system TrueType fonts, with per-rune fallback so
// symbols and emoji come from Symbola when DejaVu lacks them.
package gfx

import (
	"image"
	"image/color"
	"os"
	"strconv"
	"strings"
	"sync"

	"golang.org/x/image/font"
	"golang.org/x/image/font/opentype"
	"golang.org/x/image/font/sfnt"
	"golang.org/x/image/math/fixed"
)

// Font chain, first font that has the rune wins. Regular/bold pairs share an index.
var chain = [][2]string{
	{"/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"},
	{"/usr/share/fonts/truetype/ancient-scripts/Symbola_hint.ttf", ""},
	{"/usr/share/fonts/truetype/freefont/FreeSans.ttf", "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"},
	{"/usr/share/fonts/truetype/freefont/FreeSerif.ttf", ""},
}

type loaded struct {
	f    *opentype.Font
	sf   *sfnt.Font
	file *os.File
}

var (
	mu     sync.Mutex
	fonts  = map[string]*loaded{}
	faces  = map[faceKey]font.Face{}
	sfbuf  sfnt.Buffer
	missed = map[string]bool{}
)

type faceKey struct {
	path string
	px   float64
}

func load(path string) *loaded {
	if l, ok := fonts[path]; ok {
		return l
	}
	if path == "" || missed[path] {
		return nil
	}
	f, err := os.Open(path)
	if err != nil {
		missed[path] = true
		return nil
	}
	// ParseReaderAt keeps the file on disk and reads tables on demand: low RSS.
	of, err := opentype.ParseReaderAt(f)
	if err != nil {
		f.Close()
		missed[path] = true
		return nil
	}
	l := &loaded{f: of, file: f}
	fonts[path] = l
	return l
}

func face(path string, px float64) font.Face {
	k := faceKey{path, px}
	if fc, ok := faces[k]; ok {
		return fc
	}
	l := load(path)
	if l == nil {
		return nil
	}
	fc, err := opentype.NewFace(l.f, &opentype.FaceOptions{Size: px, DPI: 72, Hinting: font.HintingVertical})
	if err != nil {
		return nil
	}
	faces[k] = fc
	return fc
}

// pick returns the font path (regular or bold variant) that has a glyph for r.
func pick(r rune, bold bool) string {
	for _, pair := range chain {
		p := pair[0]
		if bold && pair[1] != "" {
			p = pair[1]
		}
		l := load(p)
		if l == nil {
			continue
		}
		if idx, err := l.f.GlyphIndex(&sfbuf, r); err == nil && idx != 0 {
			return p
		}
	}
	return chain[0][0] // .notdef box
}

// Span is a run of uniformly styled text.
type Span struct {
	Text   string
	Scale  float64 // relative to the base size (1.0 = base)
	Bold   bool
	Italic bool // accepted, not rendered (no italic faces in the chain)
	Color  color.RGBA
}

var sizeNames = map[string]float64{
	"xx-small": 0.58, "x-small": 0.69, "small": 0.83, "medium": 1,
	"large": 1.2, "x-large": 1.44, "xx-large": 1.73,
	"smaller": 0.83, "larger": 1.2,
}

func unescape(s string) string {
	if !strings.Contains(s, "&") {
		return s
	}
	var b strings.Builder
	for i := 0; i < len(s); i++ {
		if s[i] != '&' {
			b.WriteByte(s[i])
			continue
		}
		end := strings.IndexByte(s[i:], ';')
		if end < 0 {
			b.WriteByte(s[i])
			continue
		}
		ent := s[i+1 : i+end]
		switch {
		case ent == "amp":
			b.WriteByte('&')
		case ent == "lt":
			b.WriteByte('<')
		case ent == "gt":
			b.WriteByte('>')
		case ent == "quot":
			b.WriteByte('"')
		case ent == "apos":
			b.WriteByte('\'')
		case strings.HasPrefix(ent, "#x"):
			n, err := strconv.ParseInt(ent[2:], 16, 32)
			if err != nil {
				b.WriteString(s[i : i+end+1])
			} else {
				b.WriteRune(rune(n))
			}
		case strings.HasPrefix(ent, "#"):
			n, err := strconv.Atoi(ent[1:])
			if err != nil {
				b.WriteString(s[i : i+end+1])
			} else {
				b.WriteRune(rune(n))
			}
		default:
			b.WriteString(s[i : i+end+1])
		}
		i += end
	}
	return b.String()
}

func parseColor(s string) (color.RGBA, bool) {
	s = strings.TrimPrefix(strings.TrimSpace(s), "#")
	if len(s) == 6 {
		if n, err := strconv.ParseUint(s, 16, 32); err == nil {
			return color.RGBA{uint8(n >> 16), uint8(n >> 8), uint8(n), 255}, true
		}
	}
	switch strings.ToLower(s) {
	case "red":
		return color.RGBA{204, 0, 0, 255}, true
	case "green":
		return color.RGBA{0, 140, 0, 255}, true
	case "orange":
		return color.RGBA{230, 120, 0, 255}, true
	case "gray", "grey":
		return color.RGBA{110, 110, 110, 255}, true
	case "blue":
		return color.RGBA{30, 80, 200, 255}, true
	}
	return color.RGBA{}, false
}

// attr extracts name='value' (or "value") from a tag body.
func attr(tag, name string) string {
	i := strings.Index(tag, name+"=")
	if i < 0 {
		return ""
	}
	rest := tag[i+len(name)+1:]
	if len(rest) < 2 || (rest[0] != '\'' && rest[0] != '"') {
		return ""
	}
	end := strings.IndexByte(rest[1:], rest[0])
	if end < 0 {
		return ""
	}
	return rest[1 : 1+end]
}

// ParseMarkup understands <b>, <i>, <big>, <small>, <span size= foreground= weight=>,
// and the usual entities. Unknown tags are dropped, their content kept.
func ParseMarkup(s string, base color.RGBA) []Span {
	type style struct {
		scale  float64
		bold   bool
		italic bool
		col    color.RGBA
	}
	stack := []style{{1, false, false, base}}
	var spans []Span
	emit := func(text string) {
		if text == "" {
			return
		}
		st := stack[len(stack)-1]
		spans = append(spans, Span{Text: unescape(text), Scale: st.scale, Bold: st.bold, Italic: st.italic, Color: st.col})
	}
	for len(s) > 0 {
		i := strings.IndexByte(s, '<')
		if i < 0 {
			emit(s)
			break
		}
		emit(s[:i])
		j := strings.IndexByte(s[i:], '>')
		if j < 0 {
			emit(s[i:])
			break
		}
		tag := s[i+1 : i+j]
		s = s[i+j+1:]
		if strings.HasPrefix(tag, "/") {
			if len(stack) > 1 {
				stack = stack[:len(stack)-1]
			}
			continue
		}
		st := stack[len(stack)-1]
		name := strings.Fields(tag + " ")[0]
		switch name {
		case "b":
			st.bold = true
		case "i":
			st.italic = true
		case "big":
			st.scale *= 1.2
		case "small":
			st.scale *= 0.83
		case "span":
			if v, ok := sizeNames[attr(tag, "size")]; ok {
				st.scale = v * stack[0].scale
			}
			if c, ok := parseColor(attr(tag, "foreground")); ok {
				st.col = c
			} else if c, ok := parseColor(attr(tag, "color")); ok {
				st.col = c
			}
			if w := attr(tag, "weight"); w == "bold" || w == "heavy" {
				st.bold = true
			}
		}
		if !strings.HasSuffix(tag, "/") {
			stack = append(stack, st)
		}
	}
	return spans
}

type run struct {
	text string
	path string
	px   float64
	col  color.RGBA
}

// runs splits spans into font runs at the base pixel size.
func runs(spans []Span, basePx float64) []run {
	var out []run
	for _, sp := range spans {
		px := basePx * sp.Scale
		for _, r := range sp.Text {
			p := pick(r, sp.Bold)
			if n := len(out); n > 0 && out[n-1].path == p && out[n-1].px == px && out[n-1].col == sp.Color {
				out[n-1].text += string(r)
			} else {
				out = append(out, run{string(r), p, px, sp.Color})
			}
		}
	}
	return out
}

// Metrics describes one line of laid-out text.
type Metrics struct{ W, H, Ascent int }

func measureRuns(rs []run) (w fixed.Int26_6, asc, desc int) {
	for _, r := range rs {
		fc := face(r.path, r.px)
		if fc == nil {
			continue
		}
		w += font.MeasureString(fc, r.text)
		m := fc.Metrics()
		if a := m.Ascent.Ceil(); a > asc {
			asc = a
		}
		if d := m.Descent.Ceil(); d > desc {
			desc = d
		}
	}
	return
}

// Measure returns the size of a single line of text.
func Measure(spans []Span, basePx float64) Metrics {
	mu.Lock()
	defer mu.Unlock()
	w, asc, desc := measureRuns(runs(spans, basePx))
	return Metrics{W: w.Ceil(), H: asc + desc, Ascent: asc}
}

// Draw renders one line with its top-left at (x,y); returns the advance in pixels.
func Draw(dst *image.RGBA, x, y int, spans []Span, basePx float64) int {
	mu.Lock()
	defer mu.Unlock()
	rs := runs(spans, basePx)
	_, asc, _ := measureRuns(rs)
	dot := fixed.P(x, y+asc)
	for _, r := range rs {
		fc := face(r.path, r.px)
		if fc == nil {
			continue
		}
		d := font.Drawer{Dst: dst, Src: image.NewUniform(r.col), Face: fc, Dot: dot}
		d.DrawString(r.text)
		dot = d.Dot
	}
	return (dot.X - fixed.I(x)).Ceil()
}

// SplitLines splits markup text on newlines (tags never span lines in our uses).
func SplitLines(s string) []string { return strings.Split(s, "\n") }

// SplitSpans splits spans into lines at "\n" characters inside their text.
func SplitSpans(spans []Span) [][]Span {
	lines := [][]Span{nil}
	for _, sp := range spans {
		parts := strings.Split(sp.Text, "\n")
		for i, p := range parts {
			if i > 0 {
				lines = append(lines, nil)
			}
			if p != "" {
				s := sp
				s.Text = p
				lines[len(lines)-1] = append(lines[len(lines)-1], s)
			}
		}
	}
	return lines
}
