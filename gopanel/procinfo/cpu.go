package procinfo

import (
	"os"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"time"
)

// Proc is one row of a top-N list.
type Proc struct {
	Name    string
	Percent float64
}

type sample struct {
	ticks uint64
	comm  string
}

// readStat parses /proc/<pid>/stat. comm is wrapped in parens and may itself contain
// spaces or parens, so split on the last ')'.
func readStat(pid string) (sample, bool) {
	b, err := os.ReadFile("/proc/" + pid + "/stat")
	if err != nil {
		return sample{}, false
	}
	s := string(b)
	o, c := strings.IndexByte(s, '('), strings.LastIndexByte(s, ')')
	if o < 0 || c < o {
		return sample{}, false
	}
	f := strings.Fields(s[c+1:])
	if len(f) < 13 {
		return sample{}, false
	}
	ut, e1 := strconv.ParseUint(f[11], 10, 64)
	st, e2 := strconv.ParseUint(f[12], 10, 64)
	if e1 != nil || e2 != nil {
		return sample{}, false
	}
	return sample{ut + st, s[o+1 : c]}, true
}

func scan() map[string]sample {
	out := map[string]sample{}
	ents, _ := os.ReadDir("/proc")
	for _, e := range ents {
		if n := e.Name(); n[0] >= '0' && n[0] <= '9' {
			if s, ok := readStat(n); ok {
				out[n] = s
			}
		}
	}
	return out
}

const (
	clkTck     = 100 // sysconf(_SC_CLK_TCK) is 100 on every Linux we ship
	sampleGap  = 150 * time.Millisecond
	minPercent = 0.5
)

// TopCPU samples /proc twice, a short gap apart, and returns the n busiest process
// groups as a share of the whole machine. Grouped by (aliased) name so a
// multi-process app counts once. Only run it while someone is looking.
func TopCPU(n int, friendly bool) []Proc {
	t0 := time.Now()
	before := scan()
	time.Sleep(sampleGap)
	after := scan()
	interval := time.Since(t0).Seconds() // measured, not assumed: the scans themselves take time
	ncpu := float64(runtime.NumCPU())
	totals := map[string]float64{}
	for pid, now := range after {
		prev, ok := before[pid]
		if !ok || now.ticks <= prev.ticks {
			continue
		}
		name := now.comm
		if friendly {
			name = Alias(name)
		}
		totals[name] += float64(now.ticks-prev.ticks) / clkTck / interval * 100 / ncpu
	}
	var rows []Proc
	for k, v := range totals {
		if v >= minPercent {
			rows = append(rows, Proc{k, v})
		}
	}
	sort.Slice(rows, func(i, j int) bool { return rows[i].Percent > rows[j].Percent })
	if len(rows) > n {
		rows = rows[:n]
	}
	return rows
}
