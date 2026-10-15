package main

import (
	"testing"
	"time"
)

func TestLockStateNotifiesOnTransitionOnly(t *testing.T) {
	setScreenLocked(false)
	ch := lockChanged()
	setScreenLocked(false) // no transition: channel must stay open
	select {
	case <-ch:
		t.Fatal("notified without a transition")
	case <-time.After(10 * time.Millisecond):
	}
	setScreenLocked(true)
	select {
	case <-ch:
	default:
		t.Fatal("no notification on lock")
	}
	if !screenLocked() {
		t.Fatal("state not locked")
	}
	setScreenLocked(false)
}
