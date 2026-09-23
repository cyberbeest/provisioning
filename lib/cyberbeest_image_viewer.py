#!/usr/bin/env python3
"""Cyberbeest Image Viewer.

Opens one image at its native pixel size (no controls yet -- just a
window). If the image is bigger than the screen it gets downscaled to
fit, but that downscale is done in linear light: sRGB is a gamma-encoded
signal, so averaging pixel values directly (as most image scalers do)
darkens fine detail like thin bright lines on a dark background. The
fix is to decode to linear light, resize, then re-encode to sRGB.

Single-file tool meant to be the double-click handler for image
mimetypes in Thunar. A collapsible control bar on top shows the zoom
level and holds the zoom buttons plus a menu (Rename, Copy Image).
"""

import os
import sys

import gi
import numpy as np
from PIL import Image, ImageOps

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

try:
    from OpenGL import GL

    HAVE_GL = True
except ImportError:
    HAVE_GL = False

# Leave room for window decorations / panel so a fit-to-screen image
# doesn't end up exactly edge-to-edge.
SCREEN_MARGIN_PX = 80

# Big-triangle trick: 3 vertices, no VBO needed, covers the whole viewport.
_VERTEX_SRC = """
#version 150
out vec2 vUV;
void main() {
    vec2 pos = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    vUV = pos;
    gl_Position = vec4(pos * 2.0 - 1.0, 0.0, 1.0);
}
"""

# Sampling a GL_SRGB8_ALPHA8 texture makes the GPU decode sRGB->linear
# *before* it does mipmap/bilinear filtering -- so the minification here
# is done in linear light by the texture unit itself. GTK's default
# framebuffer isn't sRGB-capable, so the encode back to sRGB has to be
# done by hand instead of relying on GL_FRAMEBUFFER_SRGB.
_FRAGMENT_SRC = """
#version 150
in vec2 vUV;
out vec4 outColor;
uniform sampler2D tex;

vec3 linear_to_srgb(vec3 c) {
    vec3 lo = c * 12.92;
    vec3 hi = 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055;
    return mix(hi, lo, step(c, vec3(0.0031308)));
}

void main() {
    vec4 c = texture(tex, vec2(vUV.x, 1.0 - vUV.y));
    outColor = vec4(linear_to_srgb(c.rgb), c.a);
}
"""


def srgb_to_linear(u8):
    a = u8.astype(np.float64) / 255.0
    return np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(lin):
    lin = np.clip(lin, 0.0, 1.0)
    a = np.where(
        lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1.0 / 2.4) - 0.055
    )
    return np.clip(a * 255.0 + 0.5, 0, 255).astype(np.uint8)


def resize_gamma_correct(img, target_w, target_h):
    """Resize an RGB/RGBA PIL image, blending in linear light.

    Alpha (if present) is not gamma-encoded, so it's resized directly
    alongside the linearized color channels rather than through the
    sRGB round-trip.
    """
    has_alpha = img.mode == "RGBA"
    arr = np.asarray(img)
    rgb = arr[:, :, :3]
    linear = srgb_to_linear(rgb)

    channels = []
    for c in range(3):
        chan = Image.fromarray(linear[:, :, c].astype(np.float32), mode="F")
        chan = chan.resize((target_w, target_h), Image.LANCZOS)
        channels.append(np.asarray(chan))
    linear_resized = np.stack(channels, axis=-1)
    rgb_resized = linear_to_srgb(linear_resized)

    if has_alpha:
        alpha_img = Image.fromarray(arr[:, :, 3])
        alpha_resized = np.asarray(alpha_img.resize((target_w, target_h), Image.LANCZOS))
        out = np.dstack([rgb_resized, alpha_resized])
        return Image.fromarray(out, mode="RGBA")
    return Image.fromarray(rgb_resized, mode="RGB")


def pil_to_pixbuf(img):
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.mode else "RGB")
    data = img.tobytes()
    has_alpha = img.mode == "RGBA"
    w, h = img.size
    rowstride = w * (4 if has_alpha else 3)
    return GdkPixbuf.Pixbuf.new_from_bytes(
        GLib.Bytes.new(data),
        GdkPixbuf.Colorspace.RGB,
        has_alpha,
        8,
        w,
        h,
        rowstride,
    )


IMAGE_EXTS = (
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".ico",
)


# Extensions that are correct for each Pillow format; the first one is what
# a mismatched file gets offered as its rename target.
FORMAT_EXTS = {
    "PNG": (".png",),
    "JPEG": (".jpg", ".jpeg"),
    "GIF": (".gif",),
    "BMP": (".bmp",),
    "WEBP": (".webp",),
    "TIFF": (".tif", ".tiff"),
    "ICO": (".ico",),
}


def mismatched_extension_fix(path):
    """If path's extension doesn't match its actual content (e.g. a JPEG
    saved as .png, which is common for images downloaded from the web),
    return (format_name, suggested_new_path); otherwise None."""
    try:
        with Image.open(path) as img:
            fmt = img.format
    except OSError:
        return None
    exts = FORMAT_EXTS.get(fmt)
    if not exts:
        return None
    folder, filename = os.path.split(path)
    stem, ext = os.path.splitext(filename)
    if ext.lower() in exts:
        return None
    candidate = os.path.join(folder, stem + exts[0])
    n = 2
    while os.path.exists(candidate):
        candidate = os.path.join(folder, f"{stem} ({n}){exts[0]}")
        n += 1
    return fmt, candidate


def folder_images_by_date(path):
    """Sibling image files in path's folder, sorted by mtime (oldest first)."""
    folder = os.path.dirname(os.path.abspath(path)) or "."
    entries = []
    for name in os.listdir(folder):
        if name.lower().endswith(IMAGE_EXTS):
            full = os.path.join(folder, name)
            try:
                entries.append((os.path.getmtime(full), full))
            except OSError:
                continue
    entries.sort(key=lambda e: e[0])
    return [full for _, full in entries]


def human_file_size(num_bytes):
    size = float(num_bytes)
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "bytes" else f"{size:.1f} {unit}"
        size /= 1024


def load_frames(path):
    """Load every frame of the image at full resolution, no resampling yet.

    Returns (frames, native_size) where frames is a list of
    (RGBA PIL.Image, duration_ms) -- a single entry for a still image, one
    per frame for an animated GIF.
    """
    img = Image.open(path)
    if img.format == "GIF" and getattr(img, "n_frames", 1) > 1:
        frames = []
        for i in range(img.n_frames):
            img.seek(i)
            # Many old GIF tools write a delay of 0 or 1 centisecond to
            # mean "just use the default speed" rather than literally
            # zero -- browsers bump anything <= 10ms up to 100ms, so we
            # match that instead of taking the file's value at face value.
            duration = img.info.get("duration", 100)
            if not duration or duration <= 10:
                duration = 100
            frames.append((img.convert("RGBA"), duration))
        return frames, img.size

    img = ImageOps.exif_transpose(img)
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    return [(img, 0)], img.size


def target_display_size(native_size):
    display = Gdk.Display.get_default()
    monitor = display.get_monitor_at_point(0, 0)
    geom = monitor.get_geometry()
    max_w = max(geom.width - SCREEN_MARGIN_PX, 100)
    max_h = max(geom.height - SCREEN_MARGIN_PX, 100)

    w, h = native_size
    if w > max_w or h > max_h:
        scale = min(max_w / w, max_h / h)
        return max(1, round(w * scale)), max(1, round(h * scale))
    return w, h


def _compile_shader(src, kind):
    shader = GL.glCreateShader(kind)
    GL.glShaderSource(shader, src)
    GL.glCompileShader(shader)
    if not GL.glGetShaderiv(shader, GL.GL_COMPILE_STATUS):
        raise RuntimeError(GL.glGetShaderInfoLog(shader).decode())
    return shader


def _build_program():
    vs = _compile_shader(_VERTEX_SRC, GL.GL_VERTEX_SHADER)
    fs = _compile_shader(_FRAGMENT_SRC, GL.GL_FRAGMENT_SHADER)
    program = GL.glCreateProgram()
    GL.glAttachShader(program, vs)
    GL.glAttachShader(program, fs)
    GL.glLinkProgram(program)
    if not GL.glGetProgramiv(program, GL.GL_LINK_STATUS):
        raise RuntimeError(GL.glGetProgramInfoLog(program).decode())
    GL.glDeleteShader(vs)
    GL.glDeleteShader(fs)
    return program


class GLImageArea(Gtk.GLArea):
    """Renders the image at native resolution; the GPU's sRGB texture
    unit does the gamma-correct downscale (decode -> mipmap/bilinear
    filter in linear light), the fragment shader re-encodes to sRGB.

    frames is a list of (RGBA PIL.Image, duration_ms); more than one
    entry means an animated GIF, stepped via a self-rescheduling
    GLib.timeout (frame durations vary frame to frame)."""

    def __init__(self, frames):
        super().__init__()
        self.frames = frames
        self.frame_idx = 0
        self.generation = 0
        self.texture = None
        self.set_required_version(3, 2)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self.connect("realize", self.on_realize)
        self.connect("render", self.on_render)

    def set_zoom_size(self, w, h):
        # The widget's own size *is* the zoom level -- inside a
        # GtkScrolledWindow this can exceed the visible viewport, which is
        # exactly what makes scrollbars appear for zoomed-in content.
        self.set_size_request(w, h)

    def set_frames(self, frames):
        # Reuse this widget/GL context for a new image instead of tearing
        # down and recreating one on every navigation -- destroying and
        # realizing a fresh GLArea (new context, new window) on every
        # image switch left a multi-frame window where the compositor
        # could still be showing the old widget's last frame while the
        # new one was realizing, which looked like the old and new image
        # flickering back and forth.
        self.frames = frames
        self.frame_idx = 0
        self.generation += 1
        if self.get_realized():
            self._upload_full(frames[0][0])
        if len(frames) > 1:
            GLib.timeout_add(frames[0][1], self._advance_frame, self.generation)

    def on_realize(self, area):
        area.make_current()
        self.program = _build_program()
        self.vao = GL.glGenVertexArrays(1)
        self.texture = GL.glGenTextures(1)
        self._upload_full(self.frames[0][0])
        if len(self.frames) > 1:
            GLib.timeout_add(self.frames[0][1], self._advance_frame, self.generation)

    def _upload_full(self, img):
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture)
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
        w, h = img.size
        GL.glTexImage2D(
            GL.GL_TEXTURE_2D, 0, GL.GL_SRGB8_ALPHA8, w, h, 0,
            GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, img.tobytes(),
        )
        self._set_filter_params()
        self.queue_render()

    def _set_filter_params(self):
        GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR_MIPMAP_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)

    def _advance_frame(self, generation):
        # A stale timer chain from an image that's since been swapped out
        # via set_frames() stops rescheduling itself here instead of
        # animating over whatever image is now showing.
        if generation != self.generation:
            return False
        self.frame_idx = (self.frame_idx + 1) % len(self.frames)
        frame, duration = self.frames[self.frame_idx]
        self.make_current()
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture)
        GL.glTexSubImage2D(
            GL.GL_TEXTURE_2D, 0, 0, 0, frame.width, frame.height,
            GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, frame.tobytes(),
        )
        self._set_filter_params()
        self.queue_render()
        GLib.timeout_add(duration, self._advance_frame, generation)
        return False

    def on_render(self, area, ctx):
        scale = area.get_scale_factor()
        area_w = area.get_allocated_width() * scale
        area_h = area.get_allocated_height() * scale
        GL.glViewport(0, 0, area_w, area_h)
        GL.glClearColor(0.0, 0.0, 0.0, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)

        # No aspect-ratio math needed here: set_zoom_size() always sets
        # this widget's own size to the exact w/h the caller wants drawn
        # (already aspect-correct), so the viewport just fills it.
        GL.glUseProgram(self.program)
        GL.glBindVertexArray(self.vao)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, 3)
        return True


def make_cpu_image_widget(frames):
    """CPU (Pillow/numpy) fallback when PyOpenGL isn't available: a
    Gtk.Image driven through an animated GIF's frames, resized
    gamma-correctly on demand. Returns (widget, set_zoom_size, set_frames)
    -- the caller drives the displayed size the same way it drives
    GLImageArea.set_zoom_size(), there's just a CPU resample behind it
    instead of a live GPU viewport. set_frames() swaps in a new image
    without recreating the widget, mirroring GLImageArea.set_frames()."""
    image_widget = Gtk.Image()
    image_widget.set_halign(Gtk.Align.CENTER)
    image_widget.set_valign(Gtk.Align.CENTER)
    state = {"idx": 0, "size": None, "pixbufs": [], "frames": frames, "generation": 0}

    def render_at(w, h):
        pixbufs = []
        for frame, duration in state["frames"]:
            if (w, h) != frame.size:
                frame = resize_gamma_correct(frame, w, h)
            pixbufs.append((pil_to_pixbuf(frame), duration))
        state["pixbufs"] = pixbufs
        state["size"] = (w, h)
        image_widget.set_size_request(w, h)
        image_widget.set_from_pixbuf(pixbufs[state["idx"] % len(pixbufs)][0])

    def advance(generation):
        if generation != state["generation"]:
            return False
        pixbufs = state["pixbufs"]
        if not pixbufs:
            return False
        state["idx"] = (state["idx"] + 1) % len(pixbufs)
        pixbuf, duration = pixbufs[state["idx"]]
        image_widget.set_from_pixbuf(pixbuf)
        GLib.timeout_add(duration, advance, generation)
        return False

    def set_zoom_size(w, h):
        if (w, h) != state["size"]:
            render_at(w, h)

    def set_frames(new_frames):
        state["frames"] = new_frames
        state["idx"] = 0
        state["size"] = None
        state["generation"] += 1
        if len(new_frames) > 1:
            GLib.timeout_add(new_frames[0][1], advance, state["generation"])

    native_w, native_h = frames[0][0].size
    render_at(native_w, native_h)
    if len(frames) > 1:
        GLib.timeout_add(frames[0][1], advance, state["generation"])

    return image_widget, set_zoom_size, set_frames


_BLACK_BG_CSS = Gtk.CssProvider()
_BLACK_BG_CSS.load_from_data(b"window { background-color: black; }")

# The window itself is black (image backdrop), so the control bar needs
# the theme's normal background back to be readable.
_BAR_CSS = Gtk.CssProvider()
_BAR_CSS.load_from_data(b"box { background-color: @theme_bg_color; padding: 2px 4px; }")

CONFIG_DIR = os.path.expanduser("~/.config/cyberbeest")
BAR_COLLAPSED_FILE = os.path.join(CONFIG_DIR, "image-viewer-bar-collapsed")


def _icon_button(icon_name, tooltip, handler):
    button = Gtk.Button.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
    button.set_relief(Gtk.ReliefStyle.NONE)
    button.set_tooltip_text(tooltip)
    # Keep keyboard focus off the bar, so arrow keys / Enter keep going
    # to the viewer instead of moving between or clicking bar buttons.
    button.set_can_focus(False)
    button.connect("clicked", lambda _b: handler())
    return button


def _menu_item_with_hotkey(label, hotkey, handler):
    item = Gtk.MenuItem()
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
    row.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0)
    row.pack_start(Gtk.Label(label=hotkey, xalign=1), False, False, 0)
    item.add(row)
    item.connect("activate", lambda _i: handler())
    return item


class RenameDialog(Gtk.Dialog):
    """Edits only the part before the extension by default, since changing
    the extension is almost never what's wanted; a checkbox unlocks the
    whole filename for the rare case where it is."""

    def __init__(self, parent, path):
        super().__init__(title="Rename", transient_for=parent, modal=True)
        self.folder = os.path.dirname(path)
        self.old_name = os.path.basename(path)
        stem, self.ext = os.path.splitext(self.old_name)
        self.new_path = None

        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Rename", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self.entry = Gtk.Entry(text=stem, activates_default=True, width_chars=40)
        row.pack_start(self.entry, True, True, 0)
        self.ext_label = Gtk.Label(label=self.ext)
        row.pack_start(self.ext_label, False, False, 0)
        box.pack_start(row, False, False, 0)

        self.whole_check = Gtk.CheckButton(label="Rename the whole file name, including the extension")
        self.whole_check.connect("toggled", self.on_whole_toggled)
        # Nothing to unlock for a file without an extension.
        self.whole_check.set_sensitive(bool(self.ext))
        box.pack_start(self.whole_check, False, False, 0)

        self.error_label = Gtk.Label(xalign=0)
        self.error_label.set_line_wrap(True)
        self.error_label.set_no_show_all(True)
        box.pack_start(self.error_label, False, False, 0)

        self.connect("response", self.on_response)
        box.show_all()
        self.entry.grab_focus()

    def on_whole_toggled(self, check):
        # Carry over whatever was already typed rather than resetting.
        if check.get_active():
            self.entry.set_text(self.entry.get_text() + self.ext)
            self.ext_label.hide()
            self.entry.grab_focus()
            self.entry.select_region(0, -1)
        else:
            text = self.entry.get_text()
            stem, ext = os.path.splitext(text)
            if ext:
                self.ext = ext
            self.entry.set_text(stem if ext else text)
            self.ext_label.set_text(self.ext)
            self.ext_label.show()
            self.entry.grab_focus()

    def _new_name(self):
        text = self.entry.get_text().strip()
        if self.whole_check.get_active():
            return text
        return text + self.ext if text else ""

    def _show_error(self, text):
        self.error_label.set_text(text)
        self.error_label.show()

    def on_response(self, _dialog, response):
        if response != Gtk.ResponseType.OK:
            return
        new_name = self._new_name()
        if not new_name or new_name in (".", ".."):
            self._show_error("The name can't be empty.")
        elif "/" in new_name:
            self._show_error("The name can't contain a \"/\".")
        elif new_name == self.old_name:
            return  # unchanged: just close
        elif os.path.lexists(os.path.join(self.folder, new_name)):
            self._show_error(f"A file named \"{new_name}\" already exists here.")
        else:
            try:
                os.rename(os.path.join(self.folder, self.old_name), os.path.join(self.folder, new_name))
            except OSError as e:
                self._show_error(f"Couldn't rename: {e.strerror}")
            else:
                self.new_path = os.path.join(self.folder, new_name)
                return
        # Keep the dialog open so the user can fix the name.
        self.stop_emission_by_name("response")


ZOOM_STEP = 1.25
MIN_ZOOM_SCALE = 0.02
SELF_CHECK_INTERVAL_S = 2
NAV_DEBOUNCE_MS = 200


class ClipboardOwner:
    """Serves a copied image on the CLIPBOARD selection in several formats
    at once. Gtk.Clipboard.set_with_data() isn't usable from Python, so
    this goes through the lower-level selection API on an invisible
    widget instead."""

    INFO_IMAGE, INFO_URIS, INFO_GNOME_FILES = range(3)

    def __init__(self):
        self.widget = Gtk.Invisible()
        self.widget.connect("selection-get", self.on_selection_get)
        self.widget.connect("selection-clear-event", self.on_selection_clear)
        self.pixbuf = None
        self.uri = None

    def offer(self, pixbuf, path):
        self.pixbuf = pixbuf
        self.uri = GLib.filename_to_uri(os.path.abspath(path))
        # Built by hand: Gtk.target_table_new_from_list() segfaults under
        # PyGObject. PNG first, as the lossless default.
        targets = [
            Gtk.TargetEntry.new(mime, 0, self.INFO_IMAGE)
            for mime in ("image/png", "image/bmp", "image/tiff", "image/jpeg")
        ] + [
            Gtk.TargetEntry.new("text/uri-list", 0, self.INFO_URIS),
            Gtk.TargetEntry.new("x-special/gnome-copied-files", 0, self.INFO_GNOME_FILES),
        ]
        Gtk.selection_clear_targets(self.widget, Gdk.SELECTION_CLIPBOARD)
        Gtk.selection_add_targets(self.widget, Gdk.SELECTION_CLIPBOARD, targets)
        Gtk.selection_owner_set(self.widget, Gdk.SELECTION_CLIPBOARD, Gdk.CURRENT_TIME)

    def owns_clipboard(self):
        return self.pixbuf is not None

    def on_selection_get(self, _widget, data, info, _time):
        if self.pixbuf is None:
            return
        if info == self.INFO_IMAGE:
            data.set_pixbuf(self.pixbuf)
        elif info == self.INFO_URIS:
            data.set_uris([self.uri])
        elif info == self.INFO_GNOME_FILES:
            data.set(data.get_target(), 8, f"copy\n{self.uri}".encode())

    def on_selection_clear(self, _widget, _event):
        self.pixbuf = None
        self.uri = None
        # All viewer windows closed and only the clipboard kept us alive.
        if not any(isinstance(w, ImageViewerWindow) and w.get_visible() for w in Gtk.Window.list_toplevels()):
            Gtk.main_quit()
        return False


_clipboard_owner = None


class ImageViewerWindow(Gtk.Window):
    def __init__(self, path):
        super().__init__()
        self.get_style_context().add_provider(_BLACK_BG_CSS, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.folder_images = folder_images_by_date(path)
        path = os.path.abspath(path)
        try:
            self.index = self.folder_images.index(path)
        except ValueError:
            self.folder_images = [path]
            self.index = 0

        self.connect("key-press-event", self.on_key_press)
        self.connect("destroy", self.on_destroy)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(vbox)
        vbox.show()

        # Only shown when the file's extension doesn't match its content;
        # nothing is renamed until the user clicks the button.
        self.rename_bar = Gtk.InfoBar()
        self.rename_bar.set_message_type(Gtk.MessageType.WARNING)
        self.rename_bar.set_show_close_button(True)
        self.rename_bar.set_no_show_all(True)
        self.rename_label = Gtk.Label(xalign=0)
        self.rename_label.set_line_wrap(True)
        self.rename_bar.get_content_area().add(self.rename_label)
        self.rename_label.show()
        self.rename_button = self.rename_bar.add_button("Rename", Gtk.ResponseType.ACCEPT)
        self.rename_bar.connect("response", self.on_rename_response)
        vbox.pack_start(self.rename_bar, False, False, 0)
        self.rename_target = None

        self.control_bar = self._build_control_bar()
        vbox.pack_start(self.control_bar, False, False, 0)
        vbox.reorder_child(self.control_bar, 0)

        overlay = Gtk.Overlay()
        vbox.pack_start(overlay, True, True, 0)
        overlay.show()

        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.scroller.connect("size-allocate", self.on_viewport_allocate)
        overlay.add(self.scroller)
        self.scroller.show()

        # Shown over the image's top-right corner only while the bar is
        # collapsed. Right margin leaves the vertical scrollbar clickable.
        self.expand_button = _icon_button("pan-down-symbolic", "Show control bar", lambda: self.set_bar_collapsed(False))
        self.expand_button.get_style_context().add_class("osd")
        self.expand_button.set_halign(Gtk.Align.END)
        self.expand_button.set_valign(Gtk.Align.START)
        self.expand_button.set_margin_top(6)
        self.expand_button.set_margin_end(18)
        self.expand_button.set_no_show_all(True)
        overlay.add_overlay(self.expand_button)

        self.image_widget = None
        self.set_zoom_size = None
        self.set_frames = None
        self.native_size = None
        self.is_fullscreen = False
        self.zoom_mode = "fit"  # "fit" tracks the viewport; "manual" holds zoom_scale
        self.zoom_scale = 1.0
        self._last_fit_size = None
        self.drag_state = None
        self._last_nav_time = 0
        self.frames = None
        self.set_bar_collapsed(os.path.exists(BAR_COLLAPSED_FILE), remember=False)
        self.load_image(path, set_initial_size=True)

    def _build_control_bar(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        bar.get_style_context().add_provider(_BAR_CSS, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        bar.set_no_show_all(True)

        # Zoom controls sit centered in the window; the menu and collapse
        # buttons stay at the right edge.
        zoom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        zoom_box.pack_start(_icon_button("zoom-out-symbolic", "Zoom Out (-)", lambda: self.zoom_by(1 / ZOOM_STEP)), False, False, 0)
        # Fixed width so the buttons don't shift as the percentage changes.
        self.zoom_label = Gtk.Label(width_chars=10)
        zoom_box.pack_start(self.zoom_label, False, False, 0)
        zoom_box.pack_start(_icon_button("zoom-in-symbolic", "Zoom In (+)", lambda: self.zoom_by(ZOOM_STEP)), False, False, 0)
        zoom_box.pack_start(_icon_button("zoom-original-symbolic", "Zoom 1:1 (0)", self.zoom_to_native), False, False, 0)
        zoom_box.pack_start(_icon_button("zoom-fit-best-symbolic", "Zoom Fit (f)", self.zoom_to_fit), False, False, 0)
        bar.set_center_widget(zoom_box)

        bar.pack_end(_icon_button("pan-up-symbolic", "Hide control bar", lambda: self.set_bar_collapsed(True)), False, False, 0)

        menu = Gtk.Menu()
        menu.append(_menu_item_with_hotkey("Rename…", "F2", self.show_rename_dialog))
        menu.append(_menu_item_with_hotkey("Copy Image", "Ctrl+C", self.copy_image))
        menu.show_all()
        menu_button = Gtk.MenuButton(popup=menu, relief=Gtk.ReliefStyle.NONE, can_focus=False)
        menu_button.set_image(Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON))
        menu_button.set_tooltip_text("Menu")
        bar.pack_end(menu_button, False, False, 0)

        for child in bar.get_children():
            child.show_all()
        return bar

    def set_bar_collapsed(self, collapsed, remember=True):
        self.control_bar.set_visible(not collapsed)
        self.expand_button.set_visible(collapsed)
        if not remember:
            return
        try:
            if collapsed:
                os.makedirs(CONFIG_DIR, exist_ok=True)
                open(BAR_COLLAPSED_FILE, "w").close()
            elif os.path.exists(BAR_COLLAPSED_FILE):
                os.remove(BAR_COLLAPSED_FILE)
        except OSError:
            pass

    def _update_zoom_label(self):
        percent = round(self._current_scale() * 100)
        self.zoom_label.set_text(f"Fit {percent}%" if self.zoom_mode == "fit" else f"{percent}%")

    def current_path(self):
        return self.folder_images[self.index]

    def _path_renamed(self, old_path, new_path):
        if self.folder_images[self.index] == old_path:
            self.folder_images[self.index] = new_path
        self._set_title_and_tooltip(new_path)
        self._update_rename_bar(new_path)

    def show_rename_dialog(self):
        dialog = RenameDialog(self, self.current_path())
        dialog.run()
        new_path = dialog.new_path
        dialog.destroy()
        if new_path is not None:
            self._path_renamed(os.path.join(dialog.folder, dialog.old_name), new_path)

    def copy_image(self):
        if not self.frames:
            return
        # Offered as both pixels and a file reference; each app pastes
        # whichever it understands (Files makes an exact copy of the file,
        # image editors take the pixels). The pixels are the frame on
        # screen (first frame for an animated GIF), EXIF-rotated as shown.
        global _clipboard_owner
        if _clipboard_owner is None:
            _clipboard_owner = ClipboardOwner()
        _clipboard_owner.offer(pil_to_pixbuf(self.frames[0][0]), self.current_path())

    def on_destroy(self, _window):
        if isinstance(self.image_widget, GLImageArea):
            # Stop a GIF's frame timer from touching the dead GL context.
            self.image_widget.generation += 1
        self.frames = None
        # No clipboard manager runs on Cyberbeest, so a copy only lives as
        # long as this process does: keep running windowless until
        # something else takes over the clipboard.
        if _clipboard_owner is None or not _clipboard_owner.owns_clipboard():
            Gtk.main_quit()

    def _set_title_and_tooltip(self, path):
        filename = path.rsplit("/", 1)[-1]
        title_stem = filename.rsplit(".", 1)[0] if "." in filename else filename
        self.set_title(f"{title_stem} - Cyberbeest Images")
        native_w, native_h = self.native_size
        self.image_widget.set_tooltip_text(
            f"{path}\n{native_w} × {native_h}\n{human_file_size(os.path.getsize(path))}"
        )

    def _update_rename_bar(self, path):
        fix = mismatched_extension_fix(path)
        if fix is None:
            self.rename_target = None
            self.rename_bar.hide()
            return
        fmt, new_path = fix
        self.rename_target = (path, new_path)
        self.rename_label.set_text(
            f"This file is actually a {fmt} image, but its name says otherwise."
        )
        self.rename_button.set_label(f"Rename to {os.path.basename(new_path)}")
        self.rename_bar.show()

    def on_rename_response(self, _bar, response):
        if response != Gtk.ResponseType.ACCEPT or self.rename_target is None:
            self.rename_bar.hide()
            return
        old_path, new_path = self.rename_target
        if os.path.exists(new_path):
            # Something appeared under that name since the bar was shown.
            self._update_rename_bar(old_path)
            return
        try:
            os.rename(old_path, new_path)
        except OSError as e:
            self.rename_label.set_text(f"Couldn't rename: {e.strerror}")
            return
        self.rename_target = None
        self.rename_bar.hide()
        self._path_renamed(old_path, new_path)

    def load_image(self, path, set_initial_size=False):
        frames, native_size = load_frames(path)
        target_w, target_h = target_display_size(native_size)
        self.frames = frames
        self.native_size = native_size
        self._last_fit_size = None

        if self.image_widget is not None:
            # Reuse the existing widget (and its GL context, for the GL
            # path) rather than destroying and recreating one -- doing a
            # full teardown/rebuild on every navigation left a window
            # where the compositor could still be showing the old
            # widget's last frame while the new one was realizing, which
            # looked like the old and new image flickering back and
            # forth a few times before settling.
            self.set_frames(frames)
        else:
            if HAVE_GL:
                image_widget = GLImageArea(frames)
                set_zoom_size = image_widget.set_zoom_size
                set_frames = image_widget.set_frames
            else:
                image_widget, set_zoom_size, set_frames = make_cpu_image_widget(frames)

            image_widget.add_events(
                Gdk.EventMask.BUTTON_PRESS_MASK
                | Gdk.EventMask.BUTTON_RELEASE_MASK
                | Gdk.EventMask.POINTER_MOTION_MASK
            )
            image_widget.connect("button-press-event", self.on_image_button_press)
            image_widget.connect("button-release-event", self.on_image_button_release)
            image_widget.connect("motion-notify-event", self.on_image_motion)
            self.image_widget = image_widget
            self.set_zoom_size = set_zoom_size
            self.set_frames = set_frames
            self.scroller.add(image_widget)
            image_widget.show()

        self._set_title_and_tooltip(path)
        self._update_rename_bar(path)
        # Only the initial open sizes the window to fit the image/screen;
        # after that the window keeps whatever size the user picked.
        if set_initial_size:
            bar_h = self.control_bar.get_preferred_height()[1] if self.control_bar.get_visible() else 0
            self.set_default_size(target_w, target_h + bar_h)
        # Every newly shown image starts back at fit, regardless of
        # whatever zoom level was left over from the previous one.
        self.zoom_mode = "fit"
        self._apply_fit(self.scroller.get_allocation())

    def show_offset(self, offset):
        if not self.folder_images:
            return
        self.index = (self.index + offset) % len(self.folder_images)
        self.load_image(self.folder_images[self.index])

    def _debounce_nav(self, event_time):
        # X11 key-autorepeat fires Left/Right press events roughly every
        # 50ms while held -- without this, a small folder cycles fast
        # enough while a key is held (or even briefly stutters) to look
        # like the viewer is flickering between two images.
        if event_time - self._last_nav_time < NAV_DEBOUNCE_MS:
            return False
        self._last_nav_time = event_time
        return True

    def toggle_fullscreen(self):
        if self.is_fullscreen:
            self.unfullscreen()
        else:
            self.fullscreen()
        self.is_fullscreen = not self.is_fullscreen

    def on_viewport_allocate(self, _widget, allocation):
        if self.zoom_mode == "fit":
            self._apply_fit(allocation)

    def _apply_fit(self, allocation):
        if self.native_size is None or self.set_zoom_size is None:
            return
        aw, ah = max(allocation.width, 1), max(allocation.height, 1)
        nw, nh = self.native_size
        scale = min(aw / nw, ah / nh)
        w, h = max(1, round(nw * scale)), max(1, round(nh * scale))
        if (w, h) != self._last_fit_size:
            self._last_fit_size = (w, h)
            self.set_zoom_size(w, h)
        self._update_zoom_label()

    def _apply_manual_zoom(self):
        if self.native_size is None or self.set_zoom_size is None:
            return
        nw, nh = self.native_size
        self.set_zoom_size(max(1, round(nw * self.zoom_scale)), max(1, round(nh * self.zoom_scale)))
        self._update_zoom_label()

    def _current_scale(self):
        if self.zoom_mode == "manual" or self.native_size is None:
            return self.zoom_scale
        alloc = self.scroller.get_allocation()
        nw, nh = self.native_size
        if alloc.width <= 0 or alloc.height <= 0:
            return 1.0
        return min(alloc.width / nw, alloc.height / nh)

    def zoom_by(self, factor):
        base_scale = self._current_scale()
        self.zoom_mode = "manual"
        self.zoom_scale = max(MIN_ZOOM_SCALE, base_scale * factor)
        self._apply_manual_zoom()

    def zoom_to_native(self):
        self.zoom_mode = "manual"
        self.zoom_scale = 1.0
        self._apply_manual_zoom()

    def zoom_to_fit(self):
        self.zoom_mode = "fit"
        self._last_fit_size = None
        self._apply_fit(self.scroller.get_allocation())

    def show_context_menu(self, event):
        menu = Gtk.Menu()
        for label, hotkey, handler in (
            ("Zoom In", "+", lambda: self.zoom_by(ZOOM_STEP)),
            ("Zoom Out", "-", lambda: self.zoom_by(1 / ZOOM_STEP)),
            ("Zoom 1:1", "0", self.zoom_to_native),
            ("Zoom Fit", "f", self.zoom_to_fit),
        ):
            menu.append(_menu_item_with_hotkey(label, hotkey, handler))
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(_menu_item_with_hotkey("Copy Image", "Ctrl+C", self.copy_image))
        menu.show_all()
        menu.popup_at_pointer(event)

    def on_image_button_press(self, widget, event):
        if event.button == 1:
            if event.type == Gdk.EventType._2BUTTON_PRESS:
                self.toggle_fullscreen()
                return True
            self.drag_state = (
                event.x_root,
                event.y_root,
                self.scroller.get_hadjustment().get_value(),
                self.scroller.get_vadjustment().get_value(),
            )
            return True
        if event.button == 3:
            self.show_context_menu(event)
            return True
        return False

    def on_image_motion(self, widget, event):
        if self.drag_state is None:
            return False
        start_x, start_y, h0, v0 = self.drag_state
        self.scroller.get_hadjustment().set_value(h0 - (event.x_root - start_x))
        self.scroller.get_vadjustment().set_value(v0 - (event.y_root - start_y))
        return True

    def on_image_button_release(self, widget, event):
        if event.button == 1:
            self.drag_state = None
            return True
        return False

    def on_key_press(self, widget, event):
        if event.keyval in (Gdk.KEY_Escape, Gdk.KEY_q):
            self.destroy()
            return True
        if event.keyval in (Gdk.KEY_c, Gdk.KEY_C) and event.state & Gdk.ModifierType.CONTROL_MASK:
            self.copy_image()
            return True
        if event.keyval == Gdk.KEY_F2:
            self.show_rename_dialog()
            return True
        if event.keyval == Gdk.KEY_Left:
            if self._debounce_nav(event.time):
                self.show_offset(-1)
            return True
        if event.keyval == Gdk.KEY_Right:
            if self._debounce_nav(event.time):
                self.show_offset(1)
            return True
        if event.keyval in (Gdk.KEY_plus, Gdk.KEY_KP_Add):
            self.zoom_by(ZOOM_STEP)
            return True
        if event.keyval in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
            self.zoom_by(1 / ZOOM_STEP)
            return True
        if event.keyval in (Gdk.KEY_0, Gdk.KEY_KP_0):
            self.zoom_to_native()
            return True
        if event.keyval in (Gdk.KEY_f, Gdk.KEY_F):
            self.zoom_to_fit()
            return True
        return False


def _check_self_modified(self_path, initial_mtime):
    """Re-exec the running process if its own script file changed on disk
    (e.g. a git pull + reinstall while it's open), so the user doesn't
    have to notice and manually restart to pick up a fix."""
    # Re-exec'ing would reopen a window the user already closed while
    # this process only lingers to serve the clipboard.
    if not any(isinstance(w, ImageViewerWindow) for w in Gtk.Window.list_toplevels()):
        return True
    try:
        if os.path.getmtime(self_path) != initial_mtime:
            os.execv(sys.executable, [sys.executable, self_path] + sys.argv[1:])
    except OSError:
        pass
    return True


def main():
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <image path>", file=sys.stderr)
        sys.exit(1)

    self_path = os.path.abspath(sys.argv[0])
    try:
        initial_mtime = os.path.getmtime(self_path)
        GLib.timeout_add_seconds(SELF_CHECK_INTERVAL_S, _check_self_modified, self_path, initial_mtime)
    except OSError:
        pass

    win = ImageViewerWindow(sys.argv[1])
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
