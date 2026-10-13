// network-scanner: blue vertical LED sweep tracking network MB/s on the default route's
// interface, with since-boot totals in the tooltip. Port of ~/claude/network-scanner.c.
package main

import (
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"

	"gopanel/scanner"
)

type netSource struct {
	iface            string
	prevRx, prevTx   int64
	havePrev         bool
	prevAt           time.Time
	down, up, smooth float64
	rxTotal, txTotal uint64
}

func defaultIface() string {
	if b, err := os.ReadFile("/proc/net/route"); err == nil {
		for _, ln := range strings.Split(string(b), "\n")[1:] {
			if f := strings.Fields(ln); len(f) >= 2 && f[1] == "00000000" {
				return f[0]
			}
		}
	}
	ents, _ := os.ReadDir("/sys/class/net")
	for _, e := range ents {
		if e.Name() != "lo" {
			return e.Name()
		}
	}
	return ""
}

func counter(iface, which string) (uint64, bool) {
	b, err := os.ReadFile("/sys/class/net/" + iface + "/statistics/" + which)
	if err != nil {
		return 0, false
	}
	v, err := strconv.ParseUint(strings.TrimSpace(string(b)), 10, 64)
	return v, err == nil
}

func (s *netSource) Sample() {
	iface := defaultIface()
	rx, ok1 := counter(iface, "rx_bytes")
	tx, ok2 := counter(iface, "tx_bytes")
	if iface == "" || !ok1 || !ok2 {
		return
	}
	now := time.Now()
	changed := iface != s.iface
	s.iface = iface
	if s.havePrev && !changed {
		if dt := now.Sub(s.prevAt).Seconds(); dt > 0 {
			// A negative delta means the counters reset (interface cycled), not traffic.
			dRx, dTx := max(int64(rx)-s.prevRx, 0), max(int64(tx)-s.prevTx, 0)
			s.down, s.up = float64(dRx)/1e6/dt, float64(dTx)/1e6/dt
			s.smooth += (s.down + s.up - s.smooth) * 0.35
		}
	}
	s.prevRx, s.prevTx, s.prevAt, s.havePrev = int64(rx), int64(tx), now, true
	s.rxTotal, s.txTotal = rx, tx
}

func (s *netSource) Value() float64 { return s.smooth }

func human(b uint64) string {
	units := []string{"B", "KB", "MB", "GB", "TB"}
	v, i := float64(b), 0
	for v >= 1024 && i < 4 {
		v /= 1024
		i++
	}
	return fmt.Sprintf("%.1f %s", v, units[i])
}

func (s *netSource) Tooltip() string {
	status := "= Very Heavy traffic ="
	switch m := s.smooth; {
	case m < 0.05:
		status = "= Idle ="
	case m < 2:
		status = "= Light traffic ="
	case m < 10:
		status = "= Busy ="
	case m < 40:
		status = "= Heavy traffic ="
	}
	name := s.iface
	if name == "" {
		name = "n/a"
	}
	return fmt.Sprintf("Network: %.3f MB/s (down %.3f, up %.3f)\n%s\n\nSince boot (%s):\n  Down: %s\n  Up: %s\n  Total: %s",
		s.down+s.up, s.down, s.up, status, name, human(s.rxTotal), human(s.txTotal), human(s.rxTotal+s.txTotal))
}

func main() {
	scanner.Main(scanner.Config{
		Name:  "network-scanner",
		LedOn: [3]float64{0.10, 0.45, 0.95}, LedOff: [3]float64{0.03, 0.08, 0.22},
		Factor: 1.0, Exponent: 0.6, MinRate: 0, MaxRate: 2.86,
		FPS: 40, OffIsBg: true, SineSweep: true, Enabled: true,
	}, &netSource{})
}
