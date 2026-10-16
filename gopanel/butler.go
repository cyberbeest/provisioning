package main

import (
	"bufio"
	"encoding/json"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"
)

// Butler command matcher for the menu: a small sentence-embedding model (Python, onnxruntime)
// that maps what the user types to a catalog command ("make the display brighter").
//
// It runs as a child process, `butler-server` from PATH, started on the first menu search and
// stopped again after butlerIdle without use. We talk to it over its stdin/stdout only (JSON
// lines, see butler_server.py), so no other process can reach it, and the panel never sends it
// anything to execute: a command is chosen by id and the server derives the arguments from the
// catalog. If butler-server is not installed the menu simply has no commands.

const (
	butlerDebounce = 90 * time.Millisecond
	butlerIdle     = 30 * time.Second // unload after this long idle when memory is short
	butlerKeepRAM  = 1500             // MB available (MemAvailable): at least this much and the matcher stays loaded
)

type butlerHit struct {
	ID         string  `json:"id"`
	Sentence   string  `json:"sentence"`
	Category   string  `json:"category"`
	Score      float64 `json:"score"`
	NeedsValue bool    `json:"needs_value"`
	Confirm    bool    `json:"confirm"`
	Action     string  `json:"action"` // a fact that suggests a command: its label; Enter runs the fact
	Kind       string  `json:"kind"`   // "fact": a factbook answer, shown as is, not run
}

type butlerResult struct {
	seq  int
	hits []butlerHit

	cmdList []butlerHit // the whole catalog, sent once at startup
	status  bool        // the server started indexing or became ready: repaint the status line
	weather bool        // a new weather reading is in: repaint the header

	// answer to a run request (ran), or a note to clear it again (clear)
	ran, clear bool
	id, reply  string
	app        string // desktop id of the app the command opened, if any
	ok         bool
	osd        string // message for the on-screen display, and its level (0-100, -1 none)
	level      int
	levelMax   int // what a full bar means (100 for brightness, 150 for volume)
	osdHide    bool
	gen        int
}

type butlerClient struct {
	out chan<- butlerResult

	mu        sync.Mutex
	cmd       *exec.Cmd
	stdin     io.WriteCloser
	ready     bool
	seq       int
	pending   string // latest text waiting for the server (not ready yet, or debounce)
	hasPend   bool
	timer     *time.Timer
	lastUse   time.Time
	startedAt time.Time // when the running server was started: older settings changes are already in it
	missing   bool      // the server reported a broken catalog or install (until the panel restarts)
	indexing  bool      // the server is embedding new sentences (first start after a catalog change)
}

func newButlerClient(out chan<- butlerResult) *butlerClient {
	b := &butlerClient{out: out}
	go b.reaper()
	return b
}

// Ask queues a match for text (the latest text wins) and returns its sequence number; results
// with an older number are stale. Returns 0 when no matcher is available.
func (b *butlerClient) Ask(text string) int {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.missing || !readButlerSettings().Enabled {
		return 0
	}
	if b.cmd == nil && !b.startLocked() {
		return 0
	}
	b.seq++
	b.pending, b.hasPend = text, true
	b.lastUse = time.Now()
	if b.timer != nil {
		b.timer.Stop()
	}
	b.timer = time.AfterFunc(butlerDebounce, b.flush)
	return b.seq
}

// notify tells the menu to repaint its status line (indexing started, or the matcher is ready).
func (b *butlerClient) notify() {
	select {
	case b.out <- butlerResult{status: true}:
	default:
	}
}

// State says what the matcher is busy with, for the menu's status line: "indexing", "starting" or "".
func (b *butlerClient) State() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	switch {
	case b.cmd == nil || b.ready:
		return ""
	case b.indexing:
		return "indexing"
	}
	return "starting"
}

// Warm starts the server ahead of the first search (menu opened), so the model is loading
// while the user is still reaching for the keyboard.
func (b *butlerClient) Warm() {
	b.mu.Lock()
	defer b.mu.Unlock()
	st := readButlerSettings()
	if b.cmd != nil && (!st.Enabled || butlerConfigNewer(b.startedAt)) { // switched off, or the settings/disabled commands changed
		b.stopLocked()
	}
	if b.cmd == nil && !b.missing && st.Enabled {
		b.startLocked()
	}
	b.lastUse = time.Now()
}

// stopLocked asks the server to quit, which frees its memory; the next search starts it again.
func (b *butlerClient) stopLocked() {
	b.sendLocked(map[string]any{"op": "quit"})
	b.stdin.Close()
	b.cmd, b.stdin, b.ready, b.indexing = nil, nil, false, false
}

// The Butler tab of Cyberbeest Settings writes settings.json.
type butlerSettings struct {
	Enabled bool `json:"enabled"` // Butler in the menu at all
}

func butlerConfigPath(name string) string {
	dir, err := os.UserConfigDir()
	if err != nil {
		return ""
	}
	return filepath.Join(dir, "cyberbeest", "butler", name)
}

func readButlerSettings() butlerSettings {
	st := butlerSettings{Enabled: true}
	if data, err := os.ReadFile(butlerConfigPath("settings.json")); err == nil {
		json.Unmarshal(data, &st) // a broken file keeps the defaults it did not override
	}
	return st
}

// butlerConfigNewer reports whether the settings or the list of disabled commands (edited by hand) changed after t.
func butlerConfigNewer(t time.Time) bool {
	for _, n := range []string{"settings.json", "disabled.json"} {
		if fi, err := os.Stat(butlerConfigPath(n)); err == nil && fi.ModTime().After(t) {
			return true
		}
	}
	return false
}

func (b *butlerClient) flush() {
	b.mu.Lock()
	defer b.mu.Unlock()
	if !b.hasPend || !b.ready || b.stdin == nil {
		return // sent when the server announces ready
	}
	b.sendLocked(map[string]any{"op": "match", "seq": b.seq, "text": b.pending, "k": 14})
	b.hasPend = false
}

// Run asks the server to run catalog command id for the sentence the user typed.
func (b *butlerClient) Run(id, text string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.stdin != nil && b.ready {
		b.sendLocked(map[string]any{"op": "run", "id": id, "text": text})
		b.lastUse = time.Now()
	}
}

func (b *butlerClient) sendLocked(v map[string]any) {
	line, _ := json.Marshal(v)
	b.stdin.Write(append(line, '\n'))
}

func (b *butlerClient) startLocked() bool {
	path, err := exec.LookPath("butler-server")
	if err != nil { // autostarted panels often lack ~/.local/bin in PATH
		home, _ := os.UserHomeDir()
		path = filepath.Join(home, ".local/bin/butler-server")
		if _, serr := os.Stat(path); serr != nil { // not sticky: it may be installed while the panel runs
			return false
		}
	}
	cmd := exec.Command(path)
	in, err1 := cmd.StdinPipe()
	outp, err2 := cmd.StdoutPipe()
	if err1 != nil || err2 != nil || cmd.Start() != nil {
		return false
	}
	b.cmd, b.stdin, b.ready, b.startedAt = cmd, in, false, time.Now()
	go b.read(cmd, outp)
	return true
}

// Programs holding memory they give back under pressure announce it for the memory tank's tooltip:
// a file "<pid>\t<label>\t<baseline KiB>" in $XDG_RUNTIME_DIR/cyberbeest/unloadable/.
func butlerUnloadableFile() string {
	rt := os.Getenv("XDG_RUNTIME_DIR")
	if rt == "" {
		return ""
	}
	return filepath.Join(rt, "cyberbeest", "unloadable", "butler")
}

func announceButler(pid int) {
	path := butlerUnloadableFile()
	if path == "" {
		return
	}
	os.MkdirAll(filepath.Dir(path), 0o700)
	tmp := path + ".tmp"
	if os.WriteFile(tmp, []byte(strconv.Itoa(pid)+"\tButler command matcher\t0\n"), 0o600) == nil {
		os.Rename(tmp, path)
	}
}

// withdrawButler removes the announcement, but only our own: a newer server may already have replaced it.
func withdrawButler(pid int) {
	path := butlerUnloadableFile()
	if data, err := os.ReadFile(path); err == nil && strings.HasPrefix(string(data), strconv.Itoa(pid)+"\t") {
		os.Remove(path)
	}
}

func (b *butlerClient) read(cmd *exec.Cmd, r io.Reader) {
	sc := bufio.NewScanner(r)
	sc.Buffer(make([]byte, 64*1024), 1024*1024)
	for sc.Scan() {
		var m struct {
			Ready bool        `json:"ready"`
			Error string      `json:"error"`
			Seq   int         `json:"seq"`
			Ran   string      `json:"ran"`
			OK    bool        `json:"ok"`
			Reply string      `json:"reply"`
			App   string      `json:"app"`
			OSD   string      `json:"osd"`
			Level *int        `json:"level"`
			LMax  int         `json:"level_max"`
			Hits  []butlerHit `json:"hits"`
			Cmds  []butlerHit `json:"commands"`
			Idx   *int        `json:"indexing"`
		}
		var raw map[string]json.RawMessage
		if json.Unmarshal(sc.Bytes(), &raw) != nil || json.Unmarshal(sc.Bytes(), &m) != nil {
			continue
		}
		switch {
		case m.Ready:
			b.mu.Lock()
			if b.cmd == cmd {
				b.ready, b.indexing = true, false
				announceButler(cmd.Process.Pid)
				if b.hasPend {
					b.sendLocked(map[string]any{"op": "match", "seq": b.seq, "text": b.pending, "k": 14})
					b.hasPend = false
				}
			}
			b.mu.Unlock()
			b.notify()
		case m.Idx != nil:
			b.mu.Lock()
			b.indexing = true
			b.mu.Unlock()
			b.notify()
		case m.Cmds != nil:
			b.out <- butlerResult{cmdList: m.Cmds}
		case m.Error != "":
			b.mu.Lock()
			b.missing = true // broken catalog or install: stay quiet rather than restart in a loop
			b.mu.Unlock()
		case m.Ran != "":
			lvl := -1
			if m.Level != nil {
				lvl = *m.Level
			}
			select {
			case b.out <- butlerResult{ran: true, id: m.Ran, ok: m.OK, reply: m.Reply, app: m.App, osd: m.OSD, level: lvl, levelMax: m.LMax}:
			default:
			}
		default:
			if _, ok := raw["hits"]; ok {
				select {
				case b.out <- butlerResult{seq: m.Seq, hits: m.Hits}:
				default:
				}
			}
		}
	}
	cmd.Wait()
	withdrawButler(cmd.Process.Pid)
	b.mu.Lock()
	if b.cmd == cmd {
		b.cmd, b.stdin, b.ready, b.indexing = nil, nil, false, false
	}
	b.mu.Unlock()
}

// ramComfortable reports whether plenty of memory is free (the same rule Dictate uses for its model:
// MemAvailable already leaves out what the loaded model holds). When it cannot be read: not comfortable.
func ramComfortable() bool {
	data, err := os.ReadFile("/proc/meminfo")
	if err != nil {
		return false
	}
	for _, line := range strings.Split(string(data), "\n") {
		if f := strings.Fields(line); len(f) >= 2 && f[0] == "MemAvailable:" {
			kb, _ := strconv.Atoi(f[1])
			return kb/1024 >= butlerKeepRAM
		}
	}
	return false
}

// reaper stops the server (and frees its ~480 MB) after butlerIdle without use, unless memory is plentiful:
// then it stays loaded and the next search starts instantly. Checked every few seconds, so memory that
// becomes scarce later still gets it unloaded.
func (b *butlerClient) reaper() {
	for {
		time.Sleep(5 * time.Second)
		b.mu.Lock()
		if b.cmd != nil && time.Since(b.lastUse) > butlerIdle && !ramComfortable() {
			b.stopLocked()
		}
		b.mu.Unlock()
	}
}
