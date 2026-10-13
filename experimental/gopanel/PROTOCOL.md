# gopanel helper protocol (v0, experimental)

Helpers are separate processes that draw into a slot in the panel. They never talk to X.
Socket: `$XDG_RUNTIME_DIR/gopanel-helper.sock` (unix stream, mode 0600). Text lines, `\n`-terminated.
Helpers should reconnect on EOF, so a panel restart is seamless.

Panel -> helper
    panel <height>        sent immediately on connect (panel height in px)
    pause | resume        display standby; stop animating while paused (also sent after hello)
    hover on | hover off
    click <x> <y> <btn>   coordinates relative to the slot

Helper -> panel
    hello <name> <width>  once, after `panel`; reserves a slot <width> x <height>
    image <w> <h>\n       then w*h*4 bytes: premultiplied RGBA, rows top to bottom, tight stride.
                          w,h must equal the slot. The frame is composited over the panel colour.

Unknown lines are ignored on both sides. Any connected same-uid process can draw into the panel,
so nothing in this protocol may ever launch or execute anything.

Not yet: tooltips, variable width, ordering/placement, autostart of helpers.
