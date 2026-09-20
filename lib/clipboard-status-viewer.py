#!/usr/bin/env python3
"""Popup for the clipboard-status panel icon (clipboard-status-genmon.sh).

Shows what's currently in the clipboard and offers a one-click Clear, so
a leaked/breached app's window into the clipboard can be closed manually
before the auto-clear timer would. Text can be edited in place and
applied back to the clipboard. Images never reach this dialog --
clipboard-status-menu.py's "Show image" item calls
clipboard-show-image.py directly instead, since this dialog's old
"Clipboard contains an image" + Show-button step didn't add any
information over just opening the image immediately. The image-target
check below still matters for the empty-vs-text disambiguation.
"""

import subprocess

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from i18n import t

PLAIN_TEXT_TARGETS = ("UTF8_STRING", "text/plain", "STRING")
# ICCCM/GTK bookkeeping pseudo-targets every selection owner advertises
# regardless of actual content -- not real alternate representations, so
# their presence alongside a plain-text target doesn't mean anything would
# be lost by editing/saving as plain text.
BOOKKEEPING_TARGETS = {"TARGETS", "MULTIPLE", "TIMESTAMP", "SAVE_TARGETS", "DELETE", "INCR"}


def get_targets():
    try:
        out = subprocess.run(
            ["xclip", "-selection", "clipboard", "-o", "-t", "TARGETS"],
            capture_output=True, text=True, timeout=2,
        ).stdout
        return out.splitlines()
    except Exception:
        return []


def get_text_preview(limit=2000):
    try:
        out = subprocess.run(
            ["xclip", "-selection", "clipboard", "-o"],
            capture_output=True, text=True, timeout=2,
        ).stdout
        return out[:limit]
    except Exception:
        return ""


def clear_clipboard(button, window):
    subprocess.run(
        ["xclip", "-selection", "clipboard", "-i", "/dev/null"],
        timeout=2,
    )
    window.destroy()


def save_changes(button, textview, window):
    buf = textview.get_buffer()
    text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
    subprocess.run(
        ["xclip", "-selection", "clipboard", "-i"],
        input=text, text=True, timeout=2,
    )
    window.destroy()


def update_save_sensitivity(buf, save_btn, original_text):
    text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
    save_btn.set_sensitive(text != original_text)


def main():
    targets = get_targets()

    win = Gtk.Window(title=t("clipboard.window_title"))
    win.set_default_size(420, 300)
    win.set_border_width(10)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    win.add(box)

    button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    button_box.set_halign(Gtk.Align.END)

    is_text = False
    textview = None

    has_plain_text_target = any(tgt in PLAIN_TEXT_TARGETS for tgt in targets)
    has_other_content = any(tgt.startswith("image/") for tgt in targets) or "text/uri-list" in targets
    # Right after any clear (ours or another app's), the clipboard still
    # advertises an empty UTF8_STRING target rather than releasing
    # ownership (same xclip quirk clipboard-watcher.sh already works
    # around) -- without checking the actual content here too, a "Show
    # image..." click that loses a race with the auto-clear timer would
    # open the editable-text branch below with a blank buffer instead of
    # correctly reporting an empty clipboard.
    plain_text = get_text_preview() if has_plain_text_target else ""

    if not targets or (has_plain_text_target and not plain_text and not has_other_content):
        box.pack_start(Gtk.Label(label=t("clipboard.empty")), False, False, 0)
    elif any(tgt.startswith("image/") for tgt in targets):
        # Not reachable via clipboard-status-menu.py (it calls
        # clipboard-show-image.py directly for images instead) -- kept as
        # a plain fallback message in case this dialog is ever launched
        # some other way while an image is on the clipboard.
        box.pack_start(Gtk.Label(label=t("clipboard.contains_image")), False, False, 0)
    elif "text/uri-list" in targets:
        preview = get_text_preview()
        label = Gtk.Label(label=t("clipboard.contains_files"))
        label.set_xalign(0)
        box.pack_start(label, False, False, 0)
        textview = _add_scrolled_text(box, preview, editable=False)
    elif has_plain_text_target:
        preview = plain_text
        label = Gtk.Label(label=t("clipboard.contains_text"))
        label.set_xalign(0)
        box.pack_start(label, False, False, 0)

        # xclip's untargeted -o/-i only ever reads/writes the plain-text
        # target (confirmed via its own binary: it explicitly announces
        # "Using UTF8_STRING."), so a richer representation sitting
        # alongside it here -- text/html from a browser or word processor
        # being the common case -- is invisible to this dialog and gets
        # silently discarded the moment Save changes writes back, since
        # that only ever re-sets the plain-text target.
        rich_targets = set(targets) - set(PLAIN_TEXT_TARGETS) - BOOKKEEPING_TARGETS
        if rich_targets:
            warn = Gtk.Label(label=t("clipboard.formatting_warning"))
            warn.set_xalign(0)
            warn.set_line_wrap(True)
            warn.get_style_context().add_class("dim-label")
            box.pack_start(warn, False, False, 0)

        textview = _add_scrolled_text(box, preview, editable=True)
        is_text = True
    else:
        box.pack_start(Gtk.Label(label=t("clipboard.contains_unknown")), False, False, 0)

    box.pack_end(button_box, False, False, 0)

    close_btn = Gtk.Button(label=t("clipboard.close"))
    close_btn.connect("clicked", lambda b: win.destroy())
    button_box.pack_start(close_btn, False, False, 0)

    clear_btn = Gtk.Button(label=t("clipboard.clear_clipboard"))
    clear_btn.get_style_context().add_class("destructive-action")
    clear_btn.connect("clicked", clear_clipboard, win)
    button_box.pack_start(clear_btn, False, False, 0)

    if is_text:
        save_btn = Gtk.Button(label=t("clipboard.save_changes"))
        save_btn.set_sensitive(False)
        save_btn.connect("clicked", save_changes, textview, win)
        button_box.pack_start(save_btn, False, False, 0)
        textview.get_buffer().connect(
            "changed", update_save_sensitivity, save_btn, preview
        )

    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()


def _add_scrolled_text(box, content, editable):
    scrolled = Gtk.ScrolledWindow()
    scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    textview = Gtk.TextView()
    textview.set_editable(editable)
    textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    textview.get_buffer().set_text(content)
    scrolled.add(textview)
    box.pack_start(scrolled, True, True, 0)
    return textview


if __name__ == "__main__":
    main()
