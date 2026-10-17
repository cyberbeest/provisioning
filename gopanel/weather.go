package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
	"unicode"
)

// Optional weather readout in the menu header. The Weather tab of Cyberbeest Settings writes
// ~/.config/cyberbeest/weather/settings.json ({enabled, name, lat, lon}); nothing is fetched
// unless it says enabled. The current observation comes from Bright Sky (DWD open data) and
// is fetched when the menu opens, at most every weatherMaxAge, never in the background.

const weatherMaxAge = 15 * time.Minute

type weatherSettings struct {
	Enabled bool    `json:"enabled"`
	Name    string  `json:"name"`
	City    string  `json:"city"`
	Lat     float64 `json:"lat"`
	Lon     float64 `json:"lon"`
}

type weatherState struct {
	mu       sync.Mutex
	set      weatherSettings
	temp     float64
	icon     string
	have     bool
	fetched  time.Time
	fetching bool
}

var wx weatherState

func weatherConfigPath() string {
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".config", "cyberbeest", "weather", "settings.json")
}

// weatherOpened runs when the menu opens: re-reads the settings and refreshes a stale reading.
// out gets a weather result when a new reading is in.
func weatherOpened(out chan<- butlerResult) {
	var s weatherSettings
	if data, err := os.ReadFile(weatherConfigPath()); err == nil {
		json.Unmarshal(data, &s)
	}
	wx.mu.Lock()
	defer wx.mu.Unlock()
	if s != wx.set {
		wx.have = false // another place: the old reading is wrong
	}
	wx.set = s
	if !s.Enabled || s.Name == "" || wx.fetching || (wx.have && time.Since(wx.fetched) < weatherMaxAge) {
		return
	}
	wx.fetching = true
	go weatherFetch(s, out)
}

func weatherFetch(s weatherSettings, out chan<- butlerResult) {
	var r struct {
		Weather struct {
			Temperature *float64 `json:"temperature"`
			Icon        string   `json:"icon"`
		} `json:"weather"`
	}
	url := fmt.Sprintf("https://api.brightsky.dev/current_weather?lat=%.2f&lon=%.2f", s.Lat, s.Lon)
	ok := false
	if resp, err := (&http.Client{Timeout: 10 * time.Second}).Get(url); err == nil {
		if resp.StatusCode == 200 && json.NewDecoder(resp.Body).Decode(&r) == nil && r.Weather.Temperature != nil {
			ok = true
		}
		resp.Body.Close()
	}
	wx.mu.Lock()
	wx.fetching = false
	if ok && wx.set == s {
		wx.temp, wx.icon, wx.have, wx.fetched = *r.Weather.Temperature, r.Weather.Icon, true, time.Now()
	}
	wx.mu.Unlock()
	if ok {
		select {
		case out <- butlerResult{weather: true}:
		default:
		}
	}
}

// weatherText is the header text ("☁ 13° Hamburg"), empty while disabled or not yet fetched.
func weatherText() string {
	wx.mu.Lock()
	defer wx.mu.Unlock()
	if !wx.set.Enabled || !wx.have {
		return ""
	}
	glyph := map[string]string{
		"clear-day": "☀", "clear-night": "☾", "partly-cloudy-day": "⛅", "partly-cloudy-night": "☁",
		"cloudy": "☁", "fog": "≋", "wind": "≈", "rain": "☂", "sleet": "☂", "snow": "❄",
		"hail": "❄", "thunderstorm": "ϟ",
	}[wx.icon]
	name := wx.set.City
	if name == "" {
		for _, part := range strings.Split(wx.set.Name, ",") { // first part that is not a bare postcode
			if part = strings.TrimSpace(part); strings.ContainsFunc(part, unicode.IsLetter) {
				name = part
				break
			}
		}
	}
	return strings.TrimSpace(fmt.Sprintf("%s %.0f° %s", glyph, wx.temp, name))
}
