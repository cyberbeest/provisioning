package main

import (
	"fmt"
	"time"

	"github.com/jezek/xgb/xproto"
)

// A small notice above the panel while an application started from a launcher or the
// menu has not opened its window yet. It goes away as soon as a new window shows up in
// the taskbar's client list, or after noticeTimeout for apps that never open one.

const noticeTimeout = 20 * time.Second

var (
	noticeTip     *tooltip
	noticeSeen    map[xproto.Window]bool // windows that existed when the app was started
	noticeToken   int
	noticeNames   []string
	noticeDeadTmr *time.Timer
)

func noticeText() string {
	s := ""
	for i, n := range noticeNames {
		if i > 0 {
			s += ", "
		}
		s += n
	}
	return fmt.Sprintf(tr("Starting %s…"), s)
}

// noticeStart shows (or extends) the notice for an app that was just launched.
func noticeStart(name string) {
	if noticeTip == nil || name == "" {
		return
	}
	if !noticeTip.shown {
		noticeSeen = map[xproto.Window]bool{}
		noticeNames = nil
		for _, tb := range taskbars {
			for _, tw := range tb.wins {
				noticeSeen[tw.id] = true
			}
		}
	}
	noticeNames = append(noticeNames, name)
	noticeTip.show(nil, "<b>"+noticeText()+"</b>", monW/2)
	noticeToken++
	tok := noticeToken
	if noticeDeadTmr != nil {
		noticeDeadTmr.Stop()
	}
	noticeDeadTmr = time.AfterFunc(noticeTimeout, func() { ctlCmds <- fmt.Sprintf("notice-timeout:%d", tok) })
}

// noticeWindows is called after every taskbar rescan: a window that was not there
// when the app started ends the notice.
func noticeWindows(wins []*twin) {
	if noticeTip == nil || !noticeTip.shown {
		return
	}
	for _, tw := range wins {
		if !noticeSeen[tw.id] {
			noticeHide()
			return
		}
	}
}

func noticeHide() {
	if noticeTip != nil {
		noticeTip.hide()
	}
	noticeNames = nil
	if noticeDeadTmr != nil {
		noticeDeadTmr.Stop()
	}
}
