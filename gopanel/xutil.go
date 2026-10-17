package main

import (
	"github.com/jezek/xgb"
	"github.com/jezek/xgb/xproto"
)

// putBGRX uploads a w x h image (4 bytes/pixel, BGRX) to a drawable at (x,y), in row
// chunks. X rejects requests above ~256 KB, and xgb silently drops them while still
// counting the sequence number, which desynchronises replies for the rest of the
// connection's life. Every PutImage in the panel must go through here.
func putBGRX(c *xgb.Conn, d xproto.Drawable, gc xproto.Gcontext, depth byte, x, y, w, h int, buf []byte) {
	if w <= 0 || h <= 0 {
		return
	}
	rows := max((int(xproto.Setup(c).MaximumRequestLength)*4-64)/(w*4), 1)
	rows = min(rows, 200000/(w*4)+1) // stay well under the classic 262140-byte limit
	for r := 0; r < h; r += rows {
		n := min(rows, h-r)
		xproto.PutImage(c, xproto.ImageFormatZPixmap, d, gc, uint16(w), uint16(n), int16(x), int16(y+r), 0, depth,
			buf[r*w*4:(r+n)*w*4])
	}
}
