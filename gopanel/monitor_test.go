package main

import (
	"testing"

	"github.com/jezek/xgb/randr"
)

func TestPickMonitor(t *testing.T) {
	left := randr.MonitorInfo{X: 0, Y: 0, Width: 1920, Height: 1080}
	right := randr.MonitorInfo{X: 1920, Y: 0, Width: 2560, Height: 1440}
	panelOutput = ""
	if m := pickMonitor(nil, []randr.MonitorInfo{right, left}); m.X != 0 {
		t.Errorf("no primary: want the leftmost monitor, got x=%d", m.X)
	}
	right.Primary = true
	if m := pickMonitor(nil, []randr.MonitorInfo{left, right}); m.X != 1920 {
		t.Errorf("primary set: want the primary, got x=%d", m.X)
	}
	panelOutput = "Automatic"
	if m := pickMonitor(nil, []randr.MonitorInfo{left, right}); m.X != 1920 {
		t.Errorf("Automatic: want the primary, got x=%d", m.X)
	}
}
