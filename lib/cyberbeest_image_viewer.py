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

import contextlib
import math
import random
import hashlib
import os
import sqlite3
import subprocess
import sys
import time

import gi
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk

try:
    from OpenGL import GL

    HAVE_GL = True
except ImportError:
    HAVE_GL = False

# The GL path produced black flicker (whole image going black) under the
# compositor, so the CPU path is the default for now. CYBERBEEST_IMAGE_VIEWER_GL=1
# opts back into GL.
if not os.environ.get("CYBERBEEST_IMAGE_VIEWER_GL"):
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


def _build_srgb_luts():
    # 8-bit sRGB -> 16-bit linear, and back. Done as lookup tables so the
    # per-pixel pow() runs 256/65536 times instead of once per pixel.
    a = np.arange(256) / 255.0
    lin = np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)
    decode = np.round(lin * 65535).astype(np.uint16)
    lin = np.arange(65536) / 65535.0
    enc = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1.0 / 2.4) - 0.055)
    encode = np.clip(np.round(enc * 255), 0, 255).astype(np.uint8)
    return decode, encode


_SRGB_DECODE_LUT, _SRGB_ENCODE_LUT = _build_srgb_luts()


def resize_gamma_correct(img, target_w, target_h):
    """Resize an RGB/RGBA PIL image, blending in linear light.

    Alpha (if present) is not gamma-encoded, so it's resized directly
    alongside the linearized color channels rather than through the
    sRGB round-trip. The color channels are resized as 16-bit linear
    ("I;16"), which Pillow does in C, far faster than float32.

    Only downscaling averages pixels in a way that darkens, so upscaling
    (zoom beyond native size) skips the linear-light round-trip.
    """
    if target_w >= img.width and target_h >= img.height:
        return img.resize((target_w, target_h), Image.LANCZOS)
    has_alpha = img.mode == "RGBA"
    arr = np.asarray(img)

    channels = []
    for c in range(3):
        chan = Image.fromarray(_SRGB_DECODE_LUT[arr[:, :, c]])
        chan = chan.resize((target_w, target_h), Image.LANCZOS)
        channels.append(_SRGB_ENCODE_LUT[np.asarray(chan)])
    rgb_resized = np.stack(channels, axis=-1)

    if has_alpha:
        alpha_img = Image.fromarray(arr[:, :, 3])
        alpha_resized = np.asarray(alpha_img.resize((target_w, target_h), Image.LANCZOS))
        out = np.dstack([rgb_resized, alpha_resized])
        return Image.fromarray(out, mode="RGBA")
    return Image.fromarray(rgb_resized, mode="RGB")


def pixbuf_to_pil(path):
    """Decode formats Pillow lacks (JPEG XL) through the gdk-pixbuf loader
    plugins (libjxl-gdk-pixbuf). 8-bit RGBA, EXIF orientation applied."""
    try:
        pb = GdkPixbuf.Pixbuf.new_from_file(path)
    except GLib.Error as e:
        raise OSError(f"cannot decode {path}: {e.message}") from e
    pb = pb.apply_embedded_orientation() or pb
    if not pb.get_has_alpha():
        pb = pb.add_alpha(False, 0, 0, 0)
    w, h, stride = pb.get_width(), pb.get_height(), pb.get_rowstride()
    return Image.frombuffer(
        "RGBA", (w, h), pb.get_pixels(), "raw", "RGBA", stride, 1
    ).copy()


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
    ".jxl",
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
    try:
        img = Image.open(path)
    except UnidentifiedImageError:
        img = pixbuf_to_pil(path)
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


def _paint_x_background_black(gdk_window):
    # While the window is dragged bigger, the X server fills the newly
    # exposed strip itself, long before GTK/GL has drawn the next frame.
    # Giving the windows a black background makes that interim fill black
    # instead of leftover image lines.
    if gdk_window is not None:
        gdk_window.set_background_rgba(Gdk.RGBA(0, 0, 0, 1))


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
        self.paused = False
        self.texture = None
        self.fit_native = None
        self.set_required_version(3, 2)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self.connect("realize", self.on_realize)
        self.connect("render", self.on_render)
        self.connect("resize", self.on_resize)

    def on_resize(self, area, w, h):
        # Emitted with the new, empty buffer before the (slow, esp. for GIFs)
        # render: paint it black right away so the newly exposed area never
        # shows leftovers of the previous frame.
        area.make_current()
        GL.glClearColor(0.0, 0.0, 0.0, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)

    def set_zoom_size(self, w, h):
        # The widget's own size *is* the zoom level -- inside a
        # GtkScrolledWindow this can exceed the visible viewport, which is
        # exactly what makes scrollbars appear for zoomed-in content.
        if self.fit_native is not None:
            self.fit_native = None
            self.set_halign(Gtk.Align.CENTER)
            self.set_valign(Gtk.Align.CENTER)
        self.set_size_request(w, h)

    def set_fit(self, native_size):
        # Fit mode: the widget fills the whole viewport and on_render
        # letterboxes the image inside it. Resizing the window then only
        # re-renders in the same allocation pass, instead of resizing the
        # widget from an idle callback and showing stale, edge-stretched
        # pixels until that catches up.
        if self.fit_native is None:
            self.set_halign(Gtk.Align.FILL)
            self.set_valign(Gtk.Align.FILL)
            self.set_size_request(1, 1)
        self.fit_native = native_size
        self.queue_render()

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
        self.paused = False
        if self.get_realized():
            self._upload_full(frames[0][0])
        if len(frames) > 1:
            GLib.timeout_add(frames[0][1], self._advance_frame, self.generation)

    def on_realize(self, area):
        _paint_x_background_black(area.get_window())
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
        if self.paused:
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

    def current_frame_index(self):
        return self.frame_idx

    def toggle_pause(self):
        if len(self.frames) < 2:
            return
        self.paused = not self.paused
        if not self.paused:
            # The paused timer chain ended itself; start a fresh one.
            self.generation += 1
            GLib.timeout_add(self.frames[self.frame_idx][1], self._advance_frame, self.generation)

    def on_render(self, area, ctx):
        scale = area.get_scale_factor()
        area_w = area.get_allocated_width() * scale
        area_h = area.get_allocated_height() * scale
        GL.glViewport(0, 0, area_w, area_h)
        GL.glClearColor(0.0, 0.0, 0.0, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)

        # Zoomed: set_zoom_size() sized this widget to the exact aspect-correct
        # w/h, so the viewport fills it. Fit: letterbox inside the full area.
        if self.fit_native is not None:
            nw, nh = self.fit_native
            k = min(area_w / nw, area_h / nh)
            w, h = max(1, round(nw * k)), max(1, round(nh * k))
            GL.glViewport((area_w - w) // 2, (area_h - h) // 2, w, h)
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
    state = {"idx": 0, "size": None, "pixbufs": [], "frames": frames, "generation": 0, "paused": False}

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
        if generation != state["generation"] or state["paused"]:
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
        state["paused"] = False
        if len(new_frames) > 1:
            GLib.timeout_add(new_frames[0][1], advance, state["generation"])

    def toggle_pause():
        if len(state["frames"]) < 2:
            return
        state["paused"] = not state["paused"]
        if not state["paused"] and state["pixbufs"]:
            state["generation"] += 1
            GLib.timeout_add(state["pixbufs"][state["idx"]][1], advance, state["generation"])

    image_widget.toggle_pause = toggle_pause
    image_widget.current_frame_index = lambda: state["idx"] % len(state["frames"])

    native_w, native_h = frames[0][0].size
    render_at(native_w, native_h)
    if len(frames) > 1:
        GLib.timeout_add(frames[0][1], advance, state["generation"])

    return image_widget, set_zoom_size, set_frames


_BLACK_BG_CSS = Gtk.CssProvider()
# Only the image area is black, not the whole window: with a black window,
# any partial redraw of the control bar (hover over a button, the zoom
# label) could flash black through its transparent children.
_BLACK_BG_CSS.load_from_data(b".image-backdrop, .image-backdrop viewport { background-color: black; }")

_BAR_CSS = Gtk.CssProvider()
_BAR_CSS.load_from_data(b"box { background-color: @theme_bg_color; padding: 2px 4px; border-bottom: 1px solid #555555; }")

# GTK animates a button's transparent normal state to its hover color
# through transparent black, which flashes dark over the black window.
# Providers only style the widget they're added to, so this goes on
# each button individually.
_NO_TRANSITION_CSS = Gtk.CssProvider()
_NO_TRANSITION_CSS.load_from_data(b"button { transition: none; }")


CONFIG_DIR = os.path.expanduser("~/.config/cyberbeest")
BAR_COLLAPSED_FILE = os.path.join(CONFIG_DIR, "image-viewer-bar-collapsed")
_STAR_CSS = Gtk.CssProvider()
_STAR_CSS.load_from_data(b"button.favorite { color: #ffd60a; }")

_CAPTION_CSS = Gtk.CssProvider()
_CAPTION_CSS.load_from_data(b"box { background-color: @theme_bg_color; padding: 4px 8px; border-top: 1px solid #555555; }")

FAVORITES_DB = os.path.join(CONFIG_DIR, "image-favorites.sqlite")


@contextlib.contextmanager
def _favorites_db():
    """Open connection in one transaction (committed on success), always closed.

    images: every image the user has a record for (a caption, a favorite
    star, or both), with the content hash and the file's mtime/size as last
    seen. favorite_added is NULL for images that are not favorites.
    graveyard: records whose file is gone, changed or deleted, keyed by
    content hash, so the same image turning up again (any path) is
    recognized and its caption and star restored (added = 0: no star)."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    db = sqlite3.connect(FAVORITES_DB)
    try:
        db.execute(
            "CREATE TABLE IF NOT EXISTS images (path TEXT PRIMARY KEY, hash TEXT, mtime INTEGER, size INTEGER, "
            "caption TEXT NOT NULL DEFAULT '', favorite_added INTEGER)")
        old = db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'favorites'").fetchone()
        if old:
            # Earlier versions kept favorites only.
            have = {row[1] for row in db.execute("PRAGMA table_info(favorites)")}
            cols = ", ".join(c if c in have else "NULL" for c in ("path", "hash", "mtime", "size"))
            db.execute(f"INSERT OR IGNORE INTO images (path, hash, mtime, size, favorite_added) SELECT {cols}, added FROM favorites")
            db.execute("DROP TABLE favorites")
        db.execute(
            "CREATE TABLE IF NOT EXISTS graveyard (hash TEXT PRIMARY KEY, path TEXT NOT NULL, "
            "added INTEGER NOT NULL, buried INTEGER NOT NULL, reason TEXT NOT NULL)")
        if "caption" not in {row[1] for row in db.execute("PRAGMA table_info(graveyard)")}:
            db.execute("ALTER TABLE graveyard ADD COLUMN caption TEXT NOT NULL DEFAULT ''")
        db.execute("CREATE INDEX IF NOT EXISTS images_hash ON images (hash)")
        with db:
            yield db
    finally:
        db.close()


def _file_signature(path):
    st = os.stat(path)
    return st.st_mtime_ns, st.st_size


def _file_hash(path):
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _bury(db, path, reason):
    row = db.execute("SELECT favorite_added, caption, hash FROM images WHERE path = ?", (path,)).fetchone()
    db.execute("DELETE FROM images WHERE path = ?", (path,))
    if row and row[2]:
        db.execute(
            "INSERT OR REPLACE INTO graveyard (hash, path, added, buried, reason, caption) VALUES (?, ?, ?, ?, ?, ?)",
            (row[2], path, row[0] or 0, int(time.time()), reason, row[1]))


def _verify(db, path):
    """Check a record against its file; True if it is still valid. A missing
    file or different content buries the record."""
    row = db.execute("SELECT hash, mtime, size FROM images WHERE path = ?", (path,)).fetchone()
    if row is None:
        return False
    try:
        sig = _file_signature(path)
    except OSError:
        _bury(db, path, "gone")
        return False
    if row[1:] == sig:
        return True
    new_hash = _file_hash(path)
    if new_hash is not None and row[0] is None:
        # Record from before hashes were stored: adopt what is on disk now.
        db.execute("UPDATE images SET hash = ?, mtime = ?, size = ? WHERE path = ?", (new_hash, *sig, path))
        return True
    if new_hash is not None and new_hash == row[0]:
        db.execute("UPDATE images SET mtime = ?, size = ? WHERE path = ?", (*sig, path))
        return True
    _bury(db, path, "changed")
    return False


def _recognize(db, path):
    """No record by path: is it a known image by content? Restores a
    graveyard record, or follows a record whose old file is gone."""
    new_hash = _file_hash(path)
    if new_hash is None:
        return False
    sig = _file_signature(path)
    for old_path, in db.execute("SELECT path FROM images WHERE hash = ?", (new_hash,)).fetchall():
        if not os.path.exists(old_path):
            db.execute("UPDATE images SET path = ?, mtime = ?, size = ? WHERE path = ?", (path, *sig, old_path))
            return True
    grave = db.execute("SELECT added, caption FROM graveyard WHERE hash = ?", (new_hash,)).fetchone()
    if grave:
        db.execute("DELETE FROM graveyard WHERE hash = ?", (new_hash,))
        db.execute("INSERT OR REPLACE INTO images (path, hash, mtime, size, caption, favorite_added) VALUES (?, ?, ?, ?, ?, ?)",
                   (path, new_hash, *sig, grave[1], grave[0] or None))
        return True
    return False


def _ensure_record(db, path):
    if db.execute("SELECT 1 FROM images WHERE path = ?", (path,)).fetchone():
        return
    file_hash = _file_hash(path)
    try:
        mtime, size = _file_signature(path)
    except OSError:
        mtime = size = None
    db.execute("INSERT INTO images (path, hash, mtime, size) VALUES (?, ?, ?, ?)", (path, file_hash, mtime, size))
    if file_hash:
        db.execute("DELETE FROM graveyard WHERE hash = ?", (file_hash,))


def image_record(path):
    """(is_favorite, caption) for an image; recognizes it by content if the
    path is new."""
    try:
        with _favorites_db() as db:
            if not (db.execute("SELECT 1 FROM images WHERE path = ?", (path,)).fetchone() and _verify(db, path)):
                _recognize(db, path)
            row = db.execute("SELECT favorite_added, caption FROM images WHERE path = ?", (path,)).fetchone()
            return (row[0] is not None, row[1]) if row else (False, "")
    except (sqlite3.Error, OSError):
        return (False, "")


def _drop_if_empty(db, path):
    db.execute("DELETE FROM images WHERE path = ? AND caption = '' AND favorite_added IS NULL", (path,))


def favorite_toggle(path):
    """Flip the favorite flag; returns the new state."""
    with _favorites_db() as db:
        _ensure_record(db, path)
        row = db.execute("SELECT favorite_added FROM images WHERE path = ?", (path,)).fetchone()
        if row[0] is not None:
            db.execute("UPDATE images SET favorite_added = NULL WHERE path = ?", (path,))
            _drop_if_empty(db, path)
            return False
        db.execute("UPDATE images SET favorite_added = ? WHERE path = ?", (int(time.time()), path))
        return True


def set_caption(path, text):
    text = text.strip()
    with _favorites_db() as db:
        if text:
            _ensure_record(db, path)
        db.execute("UPDATE images SET caption = ? WHERE path = ?", (text, path))
        _drop_if_empty(db, path)


def favorite_move(old_path, new_path):
    try:
        with _favorites_db() as db:
            db.execute("UPDATE OR REPLACE images SET path = ? WHERE path = ?", (new_path, old_path))
    except sqlite3.Error:
        pass


def favorite_bury(path, reason):
    """File deleted from the viewer: keep the record in the graveyard, so it
    comes back if the image is restored."""
    try:
        with _favorites_db() as db:
            _bury(db, path, reason)
    except sqlite3.Error:
        pass


def favorites_list():
    """(path, added, caption) of still-valid favorites, newest first. Records
    whose file is gone or changed move to the graveyard on the way."""
    try:
        with _favorites_db() as db:
            for path, in db.execute("SELECT path FROM images").fetchall():
                _verify(db, path)
            return db.execute(
                "SELECT path, favorite_added, caption FROM images WHERE favorite_added IS NOT NULL "
                "ORDER BY favorite_added DESC").fetchall()
    except sqlite3.Error:
        return []


TOOLTIP_TIMEOUT_MS = 1500
TOOLTIP_REST_MS = 400


def _icon_button(icon_name, tooltip, handler):
    button = Gtk.Button.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
    button.set_relief(Gtk.ReliefStyle.NONE)
    button.get_style_context().add_provider(_NO_TRANSITION_CSS, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    button.set_tooltip_text(tooltip)
    # Keep keyboard focus off the bar, so arrow keys / Enter keep going
    # to the viewer instead of moving between or clicking bar buttons.
    button.set_can_focus(False)
    button.connect("clicked", lambda _b: handler())
    return button


def _label_button(markup, tooltip, handler):
    button = Gtk.Button()
    button.add(Gtk.Label(use_markup=True, label=markup))
    button.set_relief(Gtk.ReliefStyle.NONE)
    button.get_style_context().add_provider(_NO_TRANSITION_CSS, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    button.set_tooltip_text(tooltip)
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

    def offer(self, pixbuf, path=None):
        """path=None offers the pixels only (a single GIF frame), with no
        file reference that would paste as the whole file."""
        self.pixbuf = pixbuf
        self.uri = GLib.filename_to_uri(os.path.abspath(path)) if path else None
        # Built by hand: Gtk.target_table_new_from_list() segfaults under
        # PyGObject. PNG first, as the lossless default.
        targets = [
            Gtk.TargetEntry.new(mime, 0, self.INFO_IMAGE)
            for mime in ("image/png", "image/bmp", "image/tiff", "image/jpeg")
        ]
        if self.uri:
            targets += [
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


class SparkleLayer(Gtk.DrawingArea):
    """Transparent, click-through layer for a short sparkle burst around a point."""

    DURATION = 0.9

    def __init__(self):
        super().__init__()
        # Windowless: a GdkWindow of its own would swallow clicks meant for
        # the buttons underneath, pass-through or not.
        self.set_has_window(False)
        self.set_can_focus(False)
        self.particles = []
        self.center = (0, 0)
        self.arc = (0.0, math.tau)
        self.start = 0.0
        self.tick_id = 0
        self.connect("draw", self.on_draw)

    def burst(self, cx, cy):
        self.center = (cx, cy)
        self.start = time.monotonic()
        # Near the top edge (the star sits in the control bar) everything
        # would be cropped by the title bar, so spray sideways and down only.
        if cy < 60:
            self.arc = (-0.15 * math.pi, 1.15 * math.pi)
        else:
            self.arc = (0.0, math.tau)
        lo, hi = self.arc
        # (angle, distance, size, delay, gold/white flag)
        self.particles = [
            (lo + (i + random.uniform(0.1, 0.9)) * (hi - lo) / 14, random.uniform(22, 44),
             random.uniform(3.5, 7), random.uniform(0, 0.25), i % 3 == 0)
            for i in range(14)
        ]
        if not self.tick_id:
            self.tick_id = self.add_tick_callback(self._tick)

    def _tick(self, _w, _clock):
        if time.monotonic() - self.start > self.DURATION:
            self.particles = []
            self.tick_id = 0
            self.queue_draw()
            return False
        self.queue_draw()
        return True

    @staticmethod
    def _sparkle_path(cr, x, y, r):
        # Four-point star with concave sides.
        cr.move_to(x, y - r)
        k = r * 0.28
        cr.curve_to(x + k, y - k, x + k, y - k, x + r, y)
        cr.curve_to(x + k, y + k, x + k, y + k, x, y + r)
        cr.curve_to(x - k, y + k, x - k, y + k, x - r, y)
        cr.curve_to(x - k, y - k, x - k, y - k, x, y - r)
        cr.close_path()

    def on_draw(self, _w, cr):
        if not self.particles:
            return False
        t = (time.monotonic() - self.start) / self.DURATION
        cx, cy = self.center
        ease = 1 - (1 - min(t, 1.0)) ** 3
        fade = max(0.0, 1 - t ** 2)
        # Expanding ring.
        cr.set_source_rgba(1.0, 0.84, 0.04, 0.55 * fade)
        cr.set_line_width(2.5 * (1 - t) + 0.5)
        cr.arc(cx, cy, 8 + 26 * ease, *self.arc)
        cr.stroke()
        for angle, dist, size, delay, white in self.particles:
            pt = max(0.0, (t - delay) / (1 - delay))
            if pt <= 0:
                continue
            e = 1 - (1 - pt) ** 3
            x = cx + math.cos(angle) * dist * e
            y = cy + math.sin(angle) * dist * e
            # Twinkle: size swells then shrinks.
            r = size * math.sin(min(pt, 1.0) * math.pi) + 0.5
            alpha = max(0.0, 1 - pt ** 2)
            if white:
                cr.set_source_rgba(1, 1, 1, alpha)
            else:
                cr.set_source_rgba(1.0, 0.84, 0.04, alpha)
            self._sparkle_path(cr, x, y, r * 1.6)
            cr.fill()
        return False


class ImageViewerWindow(Gtk.Window):
    def __init__(self, path):
        super().__init__()
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), _BLACK_BG_CSS, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.folder_images = folder_images_by_date(path)
        path = os.path.abspath(path)
        try:
            self.index = self.folder_images.index(path)
        except ValueError:
            self.folder_images = [path]
            self.index = 0

        self.connect("key-press-event", self.on_key_press)
        self.connect("window-state-event", self.on_window_state)
        # Another viewer window may have starred or unstarred this image.
        self.connect("focus-in-event", lambda _w, _e: self._update_record() and False)
        self.connect("map", self._on_map_black_bg)
        self.connect("destroy", self.on_destroy)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        # Whole-window overlay so the favorite sparkles can spill over the
        # control bar and the image.
        top = Gtk.Overlay()
        top.add(vbox)
        self.sparkles = SparkleLayer()
        top.add_overlay(self.sparkles)
        top.set_overlay_pass_through(self.sparkles, True)
        self.add(top)
        top.show_all()

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
        overlay.get_style_context().add_class("image-backdrop")
        vbox.pack_start(overlay, True, True, 0)
        overlay.show()

        # Caption under the image: a label, swapped for an entry while editing.
        self.caption = ""
        self.caption_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.caption_bar.get_style_context().add_provider(_CAPTION_CSS, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        # Selectable by mouse (drag, right-click menu: Copy, Select All), but never
        # focusable: a focused selectable label shows a blinking text cursor.
        self.caption_label = Gtk.Label(justify=Gtk.Justification.CENTER, wrap=True, selectable=True)
        self.caption_label.set_can_focus(False)
        self.caption_event = Gtk.EventBox()
        self.caption_event.set_visible_window(False)
        self.caption_event.add(self.caption_label)
        self.caption_event.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        # On the label itself, ahead of its own handler (which would select a word).
        self.caption_label.connect("button-press-event", self.on_caption_click)
        self.caption_event.connect("button-press-event", self.on_caption_click)
        self.caption_entry = Gtk.Entry(placeholder_text="Caption (Enter to save, Esc to cancel)", xalign=0.5)
        self.caption_entry.connect("activate", lambda _e: self.finish_caption_edit(save=True))
        self.caption_entry.connect("key-press-event", self.on_caption_key)
        self.caption_entry.connect("focus-out-event", self.on_caption_focus_out)
        self.caption_entry.connect("populate-popup", self.on_caption_popup)
        self._caption_menu_open = False
        self._caption_confirming = False
        self._caption_closing = False
        self.caption_bar.pack_start(self.caption_event, True, True, 0)
        self.caption_bar.pack_start(self.caption_entry, True, True, 0)
        self.caption_bar.set_no_show_all(True)
        self.caption_event.set_no_show_all(True)
        self.caption_label.show()
        self.caption_entry.set_no_show_all(True)
        vbox.pack_start(self.caption_bar, False, False, 0)

        self.scroller = Gtk.ScrolledWindow()
        self.scroller.get_style_context().add_class("image-backdrop")
        self.scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.scroller.connect("size-allocate", self.on_viewport_allocate)
        self.scroller.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.scroller.connect("scroll-event", self.on_scroll)
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

        # With the bar collapsed there is no fullscreen button, so a fullscreen
        # window gets its own way out, next to the expand button.
        self.exit_fullscreen_button = _icon_button("view-restore-symbolic", "Exit Fullscreen (F11, Esc)", self.toggle_fullscreen)
        self.exit_fullscreen_button.get_style_context().add_class("osd")
        self.exit_fullscreen_button.set_halign(Gtk.Align.END)
        self.exit_fullscreen_button.set_valign(Gtk.Align.START)
        self.exit_fullscreen_button.set_margin_top(6)
        self.exit_fullscreen_button.set_margin_end(60)
        self.exit_fullscreen_button.set_no_show_all(True)
        overlay.add_overlay(self.exit_fullscreen_button)

        self.image_widget = None
        self.set_zoom_size = None
        self.set_frames = None
        self.native_size = None
        self.is_fullscreen = False
        self.zoom_mode = "fit"  # "fit" tracks the viewport; "manual" holds zoom_scale
        self.zoom_scale = 1.0
        self._last_fit_size = None
        self._fit_pending = False
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
        zoom_box.pack_start(_label_button("<b>1:1</b>", "Zoom 1:1 (0)", self.zoom_to_native), False, False, 0)
        zoom_box.pack_start(_label_button("<span size='x-small'>●</span>", "Zoom Fit (z)", self.zoom_to_fit), False, False, 0)
        zoom_box.pack_start(_icon_button("zoom-out-symbolic", "Zoom Out (-)", lambda: self.zoom_by(1 / ZOOM_STEP)), False, False, 0)
        # Fixed width so the buttons don't shift as the percentage changes.
        self.zoom_label = Gtk.Label(width_chars=12)
        zoom_box.pack_start(self.zoom_label, False, False, 0)
        zoom_box.pack_start(_icon_button("zoom-in-symbolic", "Zoom In (+)", lambda: self.zoom_by(ZOOM_STEP)), False, False, 0)
        bar.set_center_widget(zoom_box)

        bar.pack_start(_icon_button("go-previous-symbolic", "Previous Image (Left)", lambda: self.show_offset(-1)), False, False, 0)
        bar.pack_start(_icon_button("go-next-symbolic", "Next Image (Right)", lambda: self.show_offset(1)), False, False, 0)

        self.star_button = _icon_button("non-starred-symbolic", "Add to Favorites (F)", self.toggle_favorite)
        self.star_button.get_style_context().add_provider(_STAR_CSS, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        bar.pack_start(self.star_button, False, False, 0)
        bar.pack_start(_icon_button("document-edit-symbolic", "Edit Caption (C)", self.edit_caption), False, False, 0)

        bar.pack_end(_icon_button("pan-up-symbolic", "Hide control bar", lambda: self.set_bar_collapsed(True)), False, False, 0)

        menu = Gtk.Menu()
        menu.append(_menu_item_with_hotkey("Rename…", "F2", self.show_rename_dialog))
        menu.append(_menu_item_with_hotkey("Copy Image", "Ctrl+C", self.copy_image))
        self.copy_frame_item = _menu_item_with_hotkey("Copy Frame", "Ctrl+Shift+C", self.copy_frame)
        menu.append(self.copy_frame_item)
        menu.append(_menu_item_with_hotkey("Delete…", "Del", self.show_delete_dialog))
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(_menu_item_with_hotkey("Edit Caption", "C", self.edit_caption))
        menu.append(_menu_item_with_hotkey("Show Folder", "O", self.show_folder))
        menu.append(_menu_item_with_hotkey("Favorites", "Shift+F", self.show_favorites))
        menu.show_all()
        menu_button = Gtk.MenuButton(popup=menu, relief=Gtk.ReliefStyle.NONE, can_focus=False)
        menu_button.get_style_context().add_provider(_NO_TRANSITION_CSS, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        menu_button.set_image(Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON))
        menu_button.set_tooltip_text("Menu")
        bar.pack_end(menu_button, False, False, 0)

        self.fullscreen_button = _icon_button("view-fullscreen-symbolic", "Enter Fullscreen (F11)", self.toggle_fullscreen)
        bar.pack_end(self.fullscreen_button, False, False, 0)

        for child in bar.get_children():
            child.show_all()
        return bar

    def set_bar_collapsed(self, collapsed, remember=True):
        self.control_bar.set_visible(not collapsed)
        self.expand_button.set_visible(collapsed)
        self._update_fullscreen_ui()
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
        text = f"Fit {percent}%" if self.zoom_mode == "fit" else f"{percent}%"
        # ▲ above 100%, ▼ below: the image is shown enlarged or reduced.
        arrow = "▲" if percent > 100 else "▼" if percent < 100 else ""
        self.zoom_label.set_markup(f"{text} <span size='xx-small' rise='2600'>{arrow}</span>" if arrow else text)

    def _on_map_black_bg(self, _window):
        # The toplevel's exposed strip is always image backdrop (the control
        # bar sits at the top), so black is right for it too.
        _paint_x_background_black(self.get_window())
        _paint_x_background_black(self.scroller.get_window())
        viewport = self.scroller.get_child()
        if viewport is not None:
            _paint_x_background_black(viewport.get_window())
            if hasattr(viewport, "get_bin_window"):
                _paint_x_background_black(viewport.get_bin_window())

    def current_path(self):
        return self.folder_images[self.index]

    def _update_record(self):
        if self.caption_entry.get_visible():
            is_fav, _caption = image_record(self.current_path())
        else:
            is_fav, self.caption = image_record(self.current_path())
            self.caption_label.set_text(self.caption)
            self.caption_event.set_visible(bool(self.caption))
            self.caption_bar.set_visible(bool(self.caption))
        self.star_button.set_image(Gtk.Image.new_from_icon_name(
            "starred-symbolic" if is_fav else "non-starred-symbolic", Gtk.IconSize.BUTTON))
        ctx = self.star_button.get_style_context()
        (ctx.add_class if is_fav else ctx.remove_class)("favorite")
        self.star_button.set_tooltip_text("Remove from Favorites (F)" if is_fav else "Add to Favorites (F)")

    def edit_caption(self):
        self.caption_event.hide()
        self.caption_entry.set_text(self.caption)
        self.caption_bar.show()
        self.caption_entry.show()
        self.caption_entry.grab_focus()
        self.caption_entry.set_position(-1)

    def finish_caption_edit(self, save):
        if not self.caption_entry.get_visible():
            return
        text = self.caption_entry.get_text()
        # Hiding the focused entry fires its focus-out synchronously, while it
        # still counts as visible; without this that would save a discard.
        self._caption_closing = True
        self.caption_entry.hide()
        self.set_focus(None)
        self._caption_closing = False
        if save:
            try:
                set_caption(self.current_path(), text)
            except sqlite3.Error:
                pass
        self._update_record()

    def on_caption_focus_out(self, _entry, _event):
        # The right-click menu takes focus while it is open; that is not leaving.
        if not (self._caption_menu_open or self._caption_confirming or self._caption_closing):
            self.finish_caption_edit(save=True)
        return False

    def on_caption_popup(self, _entry, menu):
        self._caption_menu_open = True

        def closed(_menu):
            def restore():
                self._caption_menu_open = False
                if self.caption_entry.get_visible():
                    self.caption_entry.grab_focus_without_selecting()
                return False
            GLib.idle_add(restore)
        menu.connect("hide", closed)

    def on_caption_click(self, _widget, event):
        if event.type == Gdk.EventType.DOUBLE_BUTTON_PRESS and event.button == 1:
            self.edit_caption()
            return True
        return False

    def on_caption_key(self, _entry, event):
        if event.keyval == Gdk.KEY_Escape:
            self.discard_caption_edit()
            return True
        return False

    def discard_caption_edit(self):
        # Nothing typed: just leave. Otherwise ask before throwing it away.
        if self.caption_entry.get_text().strip() == self.caption:
            self.finish_caption_edit(save=False)
        elif self._confirm_discard_caption():
            self.finish_caption_edit(save=False)
        else:
            self.caption_entry.grab_focus_without_selecting()

    def _confirm_discard_caption(self):
        # The dialog takes focus; _caption_confirming keeps that from
        # counting as leaving the field (which would save).
        self._caption_confirming = True
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
            text="Discard your changes to the caption?")
        dialog.add_button("Keep Editing", Gtk.ResponseType.CANCEL)
        dialog.add_button("Discard Changes", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.CANCEL)
        response = dialog.run()
        dialog.destroy()
        self._caption_confirming = False
        return response == Gtk.ResponseType.OK

    def show_folder(self):
        # Opens the image's folder in Files. Own session, so it outlives this
        # window; inside the viewer's sandbox it inherits that sandbox.
        subprocess.Popen(["thunar", os.path.dirname(os.path.abspath(self.current_path()))],
                         start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def show_favorites(self):
        # Its own process, so it outlives this window; inherits this
        # process's sandbox.
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cyberbeest_image_favorites.py")
        subprocess.Popen([sys.executable, script], start_new_session=True)

    def toggle_favorite(self):
        try:
            now_favorite = favorite_toggle(self.current_path())
        except sqlite3.Error:
            return
        self._update_record()
        if now_favorite and self.star_button.get_mapped():
            x, y = self.star_button.translate_coordinates(
                self.sparkles, self.star_button.get_allocated_width() / 2,
                self.star_button.get_allocated_height() / 2)
            self.sparkles.burst(x, y)

    def _path_renamed(self, old_path, new_path):
        favorite_move(old_path, new_path)
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

    def show_delete_dialog(self):
        path = self.current_path()
        name = os.path.basename(path)
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
            text=f"Move \"{name}\" to the Wastebasket?",
        )
        # A file on another device (a stick, a card) goes into that device's
        # own Wastebasket, so it keeps its space and stays readable there.
        try:
            home_trash = os.path.expanduser("~/.local/share/Trash")
            if os.stat(path).st_dev != os.stat(home_trash).st_dev:
                dialog.format_secondary_text(
                    "It stays on this device, in its own Wastebasket, "
                    "until you empty it.")
        except OSError:
            pass
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Move to Wastebasket", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return
        try:
            Gio.File.new_for_path(path).trash(None)
        except GLib.Error as e:
            error = Gtk.MessageDialog(
                transient_for=self, modal=True, message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.CLOSE, text=f"Couldn't delete \"{name}\"",
                secondary_text=e.message,
            )
            error.run()
            error.destroy()
            return
        favorite_bury(path, "deleted")
        del self.folder_images[self.index]
        if not self.folder_images:
            self.destroy()
            return
        # The next image slides into the deleted one's slot; wrap at the end.
        self.index = min(self.index, len(self.folder_images) - 1)
        self.load_image(self.folder_images[self.index])

    def copy_frame(self):
        # The frame on screen right now (pause with P to pick one), as pixels only.
        if not self.frames:
            return
        global _clipboard_owner
        if _clipboard_owner is None:
            _clipboard_owner = ClipboardOwner()
        index = self.image_widget.current_frame_index() % len(self.frames)
        _clipboard_owner.offer(pil_to_pixbuf(self.frames[index][0]))

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
        self._tooltip_text = (
            f"{path}\n{native_w} × {native_h}\n{human_file_size(os.path.getsize(path))}"
        )

    def _show_tooltip(self):
        if not getattr(self.image_widget, "_tooltip_hooked", False):
            self.image_widget.connect("query-tooltip", self.on_query_tooltip)
            self.image_widget._tooltip_hooked = True
        self.image_widget.set_has_tooltip(True)

    def _pixel_rgb_at(self, widget, x, y):
        # Pointer position in widget coords -> pixel of the native-size image.
        if not self.frames or self.native_size is None:
            return None
        aw, ah = widget.get_allocated_width(), widget.get_allocated_height()
        if not (0 <= x < aw and 0 <= y < ah):
            return None
        nw, nh = self.native_size
        px = min(nw - 1, int(x * nw / aw))
        py = min(nh - 1, int(y * nh / ah))
        try:
            return self.frames[0][0].getpixel((px, py))[:3]
        except Exception:
            return None

    def on_query_tooltip(self, widget, x, y, keyboard_mode, tooltip):
        text = self._tooltip_text
        rgb = self._pixel_rgb_at(widget, x, y)
        if rgb is not None:
            text += "\nRGB " + ", ".join(str(c) for c in rgb)
        label = Gtk.Label(label=text)
        label.set_xalign(0)
        label.show()
        # Make the tooltip window click-through, so the pointer moving over
        # it still counts as being over the image and doesn't dismiss it.
        label.connect("map", self._make_tooltip_input_transparent)
        tooltip.set_custom(label)
        return True

    @staticmethod
    def _make_tooltip_input_transparent(label):
        try:
            import cairo
        except ImportError:
            return
        gdk_window = label.get_toplevel().get_window()
        if gdk_window is not None:
            gdk_window.input_shape_combine_region(cairo.Region(), 0, 0)

    def _hide_tooltip(self):
        self._tooltip_hide_timer = None
        self.image_widget.set_has_tooltip(False)
        self.image_widget.trigger_tooltip_query()
        return False

    def _show_tooltip_now(self):
        # Pointer has rested: show the tooltip, then hide it again
        # TOOLTIP_TIMEOUT_MS after it appeared.
        self._tooltip_rest_timer = None
        self._show_tooltip()
        self.image_widget.trigger_tooltip_query()
        self._tooltip_hide_timer = GLib.timeout_add(TOOLTIP_TIMEOUT_MS, self._hide_tooltip)
        return False

    def _restart_tooltip_timer(self):
        # Moving the pointer dismisses the tooltip; it comes back once the
        # pointer has rested for TOOLTIP_REST_MS, and goes again
        # TOOLTIP_TIMEOUT_MS later, so it never flickers while you move.
        for name in ("_tooltip_rest_timer", "_tooltip_hide_timer"):
            if getattr(self, name, None) is not None:
                GLib.source_remove(getattr(self, name))
                setattr(self, name, None)
        if self.image_widget.get_has_tooltip():
            self.image_widget.set_has_tooltip(False)
            self.image_widget.trigger_tooltip_query()
        self._tooltip_rest_timer = GLib.timeout_add(TOOLTIP_REST_MS, self._show_tooltip_now)

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
            # Gtk.Image (CPU path) has no GdkWindow of its own and never
            # sees pointer events; they land on the Viewport around it.
            viewport = self.scroller.get_child()
            if viewport is not image_widget:
                viewport.add_events(
                    Gdk.EventMask.BUTTON_PRESS_MASK
                    | Gdk.EventMask.BUTTON_RELEASE_MASK
                    | Gdk.EventMask.POINTER_MOTION_MASK
                )
                viewport.connect("button-press-event", self.on_image_button_press)
                viewport.connect("button-release-event", self.on_image_button_release)
                viewport.connect("motion-notify-event", self.on_image_motion)

        self._set_title_and_tooltip(path)
        self._update_rename_bar(path)
        self._update_record()
        self.copy_frame_item.set_sensitive(len(frames) > 1)
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
        # Follows the window manager's real state (see on_window_state), not
        # a flag of our own, which went out of sync and left the window stuck.
        if self.is_fullscreen:
            self.unfullscreen()
        else:
            self.fullscreen()

    def on_window_state(self, _widget, event):
        self.is_fullscreen = bool(event.new_window_state & Gdk.WindowState.FULLSCREEN)
        self._update_fullscreen_ui()
        return False

    def _update_fullscreen_ui(self):
        self.fullscreen_button.set_image(Gtk.Image.new_from_icon_name(
            "view-restore-symbolic" if self.is_fullscreen else "view-fullscreen-symbolic", Gtk.IconSize.BUTTON))
        self.fullscreen_button.set_tooltip_text(
            "Exit Fullscreen (F11, Esc)" if self.is_fullscreen else "Enter Fullscreen (F11)")
        self.exit_fullscreen_button.set_visible(self.is_fullscreen and not self.control_bar.get_visible())

    def on_viewport_allocate(self, _widget, allocation):
        if self.zoom_mode != "fit":
            return
        # Not resized in here: changing the image's size request in the middle of the
        # scroller's own size-allocate left a stale, half-repainted picture after a
        # maximize. Done from an idle callback (coalesced), then fully redrawn.
        if not self._fit_pending:
            self._fit_pending = True
            GLib.idle_add(self._fit_idle)

    def _fit_idle(self):
        self._fit_pending = False
        if self.zoom_mode == "fit":
            self._apply_fit(self.scroller.get_allocation())
            if self.image_widget is not None and not isinstance(self.image_widget, GLImageArea):
                self.image_widget.queue_resize()
                self.image_widget.queue_draw()
            self.scroller.queue_draw()
        return False

    def _apply_fit(self, allocation):
        if self.native_size is None or self.set_zoom_size is None:
            return
        if isinstance(self.image_widget, GLImageArea):
            self.image_widget.set_fit(self.native_size)
            self._update_zoom_label()
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
            ("Zoom Fit", "z", self.zoom_to_fit),
        ):
            menu.append(_menu_item_with_hotkey(label, hotkey, handler))
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(_menu_item_with_hotkey("Copy Image", "Ctrl+C", self.copy_image))
        if len(self.frames) > 1:
            menu.append(_menu_item_with_hotkey("Copy Frame", "Ctrl+Shift+C", self.copy_frame))
        menu.append(_menu_item_with_hotkey("Delete…", "Del", self.show_delete_dialog))
        menu.append(_menu_item_with_hotkey("Edit Caption", "C", self.edit_caption))
        menu.append(_menu_item_with_hotkey("Show Folder", "O", self.show_folder))
        menu.append(_menu_item_with_hotkey("Favorites", "Shift+F", self.show_favorites))
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

    def on_scroll(self, widget, event):
        if event.direction == Gdk.ScrollDirection.UP:
            self.zoom_by(ZOOM_STEP)
        elif event.direction == Gdk.ScrollDirection.DOWN:
            self.zoom_by(1 / ZOOM_STEP)
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            if event.delta_y < 0:
                self.zoom_by(ZOOM_STEP)
            elif event.delta_y > 0:
                self.zoom_by(1 / ZOOM_STEP)
        return True

    def on_image_motion(self, widget, event):
        self._restart_tooltip_timer()
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
        if self.caption_entry.get_visible():
            return False
        if event.keyval == Gdk.KEY_F11:
            self.toggle_fullscreen()
            return True
        if event.keyval == Gdk.KEY_Escape and self.is_fullscreen:
            self.unfullscreen()
            return True
        if event.keyval in (Gdk.KEY_Escape, Gdk.KEY_q):
            self.destroy()
            return True
        if event.keyval in (Gdk.KEY_c, Gdk.KEY_C) and event.state & Gdk.ModifierType.CONTROL_MASK \
                and event.state & Gdk.ModifierType.SHIFT_MASK:
            self.copy_frame()
            return True
        if event.keyval in (Gdk.KEY_c, Gdk.KEY_C) and event.state & Gdk.ModifierType.CONTROL_MASK:
            # Text selected in the caption wins over copying the image.
            selected, start, end = self.caption_label.get_selection_bounds()
            if selected:
                Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(self.caption_label.get_text()[start:end], -1)
                return True
            self.copy_image()
            return True
        if event.keyval in (Gdk.KEY_Delete, Gdk.KEY_KP_Delete):
            self.show_delete_dialog()
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
        if event.keyval in (Gdk.KEY_z, Gdk.KEY_Z):
            self.zoom_to_fit()
            return True
        if event.keyval in (Gdk.KEY_c, Gdk.KEY_C) and not event.state & Gdk.ModifierType.CONTROL_MASK:
            self.edit_caption()
            return True
        if event.keyval in (Gdk.KEY_o, Gdk.KEY_O):
            self.show_folder()
            return True
        if event.keyval == Gdk.KEY_F:
            self.show_favorites()
            return True
        if event.keyval == Gdk.KEY_f:
            self.toggle_favorite()
            return True
        if event.keyval in (Gdk.KEY_p, Gdk.KEY_P):
            if self.image_widget is not None:
                self.image_widget.toggle_pause()
            return True
        return False


def _check_self_modified(self_path, initial_mtime):
    """Re-exec the running process if its own script file changed on disk
    (e.g. a git pull + reinstall while it's open), so the user doesn't
    have to notice and manually restart to pick up a fix."""
    # Re-exec'ing would reopen a window the user already closed while
    # this process only lingers to serve the clipboard.
    windows = [w for w in Gtk.Window.list_toplevels() if isinstance(w, ImageViewerWindow)]
    if not windows:
        return True
    try:
        if os.path.getmtime(self_path) != initial_mtime:
            # Reopen on the image currently shown, not the one from the command line.
            os.execv(sys.executable, [sys.executable, self_path, windows[0].current_path()])
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
