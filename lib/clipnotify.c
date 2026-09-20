/*
 * clipnotify: blocks until the X11 CLIPBOARD selection changes owner, then
 * exits. Uses XFixesSelectSelectionInput to get an event-driven notification
 * instead of polling xclip in a loop -- polling would mean either a laggy
 * multi-second detection delay or burning CPU checking every fraction of a
 * second, and would also make the auto-clear timer start late relative to
 * when something sensitive actually landed in the clipboard.
 *
 * Not packaged in Debian's repos as of writing, and it's ~30 lines, so it's
 * built from source here the same way io-scanner.c is.
 */
#include <X11/Xlib.h>
#include <X11/extensions/Xfixes.h>
#include <stdio.h>
#include <stdlib.h>

int main(void) {
    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) {
        fprintf(stderr, "clipnotify: cannot open display\n");
        return 1;
    }

    int event_base, error_base;
    if (!XFixesQueryExtension(dpy, &event_base, &error_base)) {
        fprintf(stderr, "clipnotify: XFixes extension not available\n");
        return 1;
    }

    Window root = DefaultRootWindow(dpy);
    Atom clipboard = XInternAtom(dpy, "CLIPBOARD", False);

    XFixesSelectSelectionInput(dpy, root, clipboard,
                                XFixesSetSelectionOwnerNotifyMask);

    XEvent ev;
    XNextEvent(dpy, &ev);

    XCloseDisplay(dpy);
    return 0;
}
