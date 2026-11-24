package main

import "testing"

func TestHasMicrophone(t *testing.T) {
	for name, want := range map[string]bool{
		"alsa_input.usb-TTGK_Technology_USB_Audio-00.mono-fallback\n":                      true,
		"alsa_input.pci-0000_00_0e.0-platform-sof-essx8336.HiFi__Mic__source\n":            true,
		"alsa_output.pci-0000_00_0e.0-platform-sof-essx8336.HiFi__Speaker__sink.monitor\n": false,
		"":   false,
		"\n": false,
	} {
		if got := hasMicrophone(name); got != want {
			t.Errorf("hasMicrophone(%q) = %v, want %v", name, got, want)
		}
	}
}
