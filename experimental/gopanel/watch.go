package main

import (
	"log"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/fsnotify/fsnotify"
)

// watchConfig sends "reload" when the panel's launcher config changes: the
// per-launcher .desktop dirs, new launcher dirs, or xfconf's xfce4-panel.xml.
// Directories are watched (not files) because editors and xfconfd save via
// rename. Bursts of events are coalesced into one reload.
func watchConfig(cmds chan<- string) {
	home, _ := os.UserHomeDir()
	panelDir := filepath.Join(home, ".config/xfce4/panel")
	xfconfDir := filepath.Join(home, ".config/xfce4/xfconf/xfce-perchannel-xml")

	w, err := fsnotify.NewWatcher()
	if err != nil {
		log.Println("file watcher disabled:", err)
		return
	}
	add := func(dir string) {
		if err := w.Add(dir); err != nil {
			log.Println("watch:", err)
		}
	}
	add(panelDir)
	add(xfconfDir)
	subs, _ := filepath.Glob(filepath.Join(panelDir, "launcher-*"))
	for _, d := range subs {
		add(d)
	}

	go func() {
		var timer *time.Timer
		fire := make(chan struct{}, 1)
		for {
			select {
			case ev, ok := <-w.Events:
				if !ok {
					return
				}
				base := filepath.Base(ev.Name)
				if filepath.Dir(ev.Name) == panelDir {
					if ev.Has(fsnotify.Create) && strings.HasPrefix(base, "launcher-") {
						add(ev.Name) // new launcher dir
					} else if !strings.HasPrefix(base, "launcher-") {
						continue // genmon rc files etc. are not our business
					}
				} else if filepath.Dir(ev.Name) == xfconfDir && base != "xfce4-panel.xml" {
					continue
				}
				if timer == nil {
					timer = time.AfterFunc(300*time.Millisecond, func() {
						select {
						case fire <- struct{}{}:
						default:
						}
					})
				} else {
					timer.Reset(300 * time.Millisecond)
				}
			case <-fire:
				select {
				case cmds <- "reload":
				default:
				}
			case err, ok := <-w.Errors:
				if !ok {
					return
				}
				log.Println("watch:", err)
			}
		}
	}()
}
