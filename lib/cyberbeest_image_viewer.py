#!/usr/bin/env python3
"""Cyberbeest Image Viewer.

Opens one image at its native pixel size (no controls yet -- just a
window). If the image is bigger than the screen it gets downscaled to
fit, but that downscale is done in linear light: sRGB is a gamma-encoded
signal, so averaging pixel values directly (as most image scalers do)
darkens fine detail like thin bright lines on a dark background. The
fix is to decode to linear light, resize, then re-encode to sRGB.

Single-file, single-image tool meant to be the double-click handler for
image mimetypes in Thunar. No zoom/pan/next-image controls yet -- see
[[cyberbeest_settings_architecture]] pattern of starting minimal.
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
        self.set_required_version(3, 2)
        self.connect("realize", self.on_realize)
        self.connect("render", self.on_render)

    def on_realize(self, area):
        area.make_current()
        w, h = self.frames[0][0].size
        self.program = _build_program()
        self.vao = GL.glGenVertexArrays(1)
        self.texture = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture)
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
        GL.glTexImage2D(
            GL.GL_TEXTURE_2D, 0, GL.GL_SRGB8_ALPHA8, w, h, 0,
            GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, self.frames[0][0].tobytes(),
        )
        self._set_filter_params()
        if len(self.frames) > 1:
            GLib.timeout_add(self.frames[0][1], self._advance_frame)

    def _set_filter_params(self):
        GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR_MIPMAP_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)

    def _advance_frame(self):
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
        GLib.timeout_add(duration, self._advance_frame)
        return False

    def on_render(self, area, ctx):
        scale = area.get_scale_factor()
        area_w = area.get_allocated_width() * scale
        area_h = area.get_allocated_height() * scale
        GL.glViewport(0, 0, area_w, area_h)
        GL.glClearColor(0.0, 0.0, 0.0, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)

        # Letterbox: fit the image into the window's current size while
        # keeping its aspect ratio, rather than stretching it -- the
        # texture itself never changes, only the viewport rectangle we
        # draw it into, so resizing the window is just a per-frame
        # viewport recompute with no re-upload.
        native_w, native_h = self.frames[0][0].size
        if native_w and native_h and area_w and area_h:
            fit_scale = min(area_w / native_w, area_h / native_h)
            draw_w = max(1, round(native_w * fit_scale))
            draw_h = max(1, round(native_h * fit_scale))
            GL.glViewport((area_w - draw_w) // 2, (area_h - draw_h) // 2, draw_w, draw_h)

        GL.glUseProgram(self.program)
        GL.glBindVertexArray(self.vao)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, 3)
        return True


RESIZE_DEBOUNCE_MS = 150


def animate_cpu_image(image_widget, frames, target_w, target_h):
    """Drives a Gtk.Image through an animated GIF's frames, resizing each
    (gamma-correctly, if downscale is needed) up front, and re-resizing
    all frames (debounced) whenever the widget's allocation changes so
    window resizes scale the content -- there's no live GPU viewport
    trick available here, so a resize means redoing the CPU resample."""
    state = {"idx": 0, "size": (target_w, target_h), "pixbufs": [], "resize_src": None}

    def render_at(w, h):
        pixbufs = []
        for frame, duration in frames:
            if (w, h) != frame.size:
                frame = resize_gamma_correct(frame, w, h)
            pixbufs.append((pil_to_pixbuf(frame), duration))
        state["pixbufs"] = pixbufs
        state["size"] = (w, h)
        image_widget.set_from_pixbuf(pixbufs[state["idx"] % len(pixbufs)][0])

    def advance():
        pixbufs = state["pixbufs"]
        state["idx"] = (state["idx"] + 1) % len(pixbufs)
        pixbuf, duration = pixbufs[state["idx"]]
        image_widget.set_from_pixbuf(pixbuf)
        GLib.timeout_add(duration, advance)
        return False

    def do_resize():
        state["resize_src"] = None
        alloc = image_widget.get_allocation()
        aw, ah = max(alloc.width, 1), max(alloc.height, 1)
        native_w, native_h = frames[0][0].size
        fit_scale = min(aw / native_w, ah / native_h)
        w, h = max(1, round(native_w * fit_scale)), max(1, round(native_h * fit_scale))
        if (w, h) != state["size"]:
            render_at(w, h)
        return False

    def on_allocate(_widget, _allocation):
        if state["resize_src"] is not None:
            GLib.source_remove(state["resize_src"])
        state["resize_src"] = GLib.timeout_add(RESIZE_DEBOUNCE_MS, do_resize)

    render_at(target_w, target_h)
    image_widget.set_halign(Gtk.Align.CENTER)
    image_widget.set_valign(Gtk.Align.CENTER)
    image_widget.connect("size-allocate", on_allocate)

    if len(frames) > 1:
        GLib.timeout_add(frames[0][1], advance)


_BLACK_BG_CSS = Gtk.CssProvider()
_BLACK_BG_CSS.load_from_data(b"window { background-color: black; }")


ZOOM_STEP = 1.25
MIN_ZOOM_PX = 64


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
        self.connect("destroy", Gtk.main_quit)

        self.image_widget = None
        self.native_size = None
        self.is_fullscreen = False
        self.load_image(path, set_initial_size=True)

    def load_image(self, path, set_initial_size=False):
        filename = path.rsplit("/", 1)[-1]
        title_stem = filename.rsplit(".", 1)[0] if "." in filename else filename
        self.set_title(f"{title_stem} - Cyberbeest Images")
        frames, native_size = load_frames(path)
        target_w, target_h = target_display_size(native_size)
        native_w, native_h = native_size
        self.native_size = native_size
        tooltip = f"{path}\n{native_w} × {native_h}\n{human_file_size(os.path.getsize(path))}"

        if self.image_widget is not None:
            self.remove(self.image_widget)

        if HAVE_GL:
            image_widget = GLImageArea(frames)
        else:
            image_widget = Gtk.Image()
            animate_cpu_image(image_widget, frames, target_w, target_h)

        image_widget.set_tooltip_text(tooltip)
        image_widget.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        image_widget.connect("button-press-event", self.on_image_button_press)
        self.image_widget = image_widget
        self.add(image_widget)
        image_widget.show()
        # Only the initial open sizes the window to fit the image/screen;
        # after that the window keeps whatever size the user picked, and
        # switching images (arrow keys) or resizing just rescales the
        # content into it.
        if set_initial_size:
            self.set_default_size(target_w, target_h)

    def show_offset(self, offset):
        if not self.folder_images:
            return
        self.index = (self.index + offset) % len(self.folder_images)
        self.load_image(self.folder_images[self.index])

    def toggle_fullscreen(self):
        if self.is_fullscreen:
            self.unfullscreen()
        else:
            self.fullscreen()
        self.is_fullscreen = not self.is_fullscreen

    def zoom_by(self, factor):
        cur_w, cur_h = self.get_size()
        self.resize(max(MIN_ZOOM_PX, round(cur_w * factor)), max(MIN_ZOOM_PX, round(cur_h * factor)))

    def zoom_to_native(self):
        if self.native_size is None:
            return
        w, h = self.native_size
        self.resize(max(1, w), max(1, h))

    def zoom_to_fit(self):
        if self.native_size is None:
            return
        w, h = target_display_size(self.native_size)
        self.resize(w, h)

    def show_context_menu(self, event):
        menu = Gtk.Menu()
        for label, handler in (
            ("Zoom In", lambda _i: self.zoom_by(ZOOM_STEP)),
            ("Zoom Out", lambda _i: self.zoom_by(1 / ZOOM_STEP)),
            ("Zoom 1:1", lambda _i: self.zoom_to_native()),
            ("Zoom Fit", lambda _i: self.zoom_to_fit()),
        ):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", handler)
            menu.append(item)
        menu.show_all()
        menu.popup_at_pointer(event)

    def on_image_button_press(self, widget, event):
        if event.button == 1 and event.type == Gdk.EventType._2BUTTON_PRESS:
            self.toggle_fullscreen()
            return True
        if event.button == 3:
            self.show_context_menu(event)
            return True
        return False

    def on_key_press(self, widget, event):
        if event.keyval in (Gdk.KEY_Escape, Gdk.KEY_q):
            self.destroy()
            return True
        if event.keyval == Gdk.KEY_Left:
            self.show_offset(-1)
            return True
        if event.keyval == Gdk.KEY_Right:
            self.show_offset(1)
            return True
        return False


def main():
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <image path>", file=sys.stderr)
        sys.exit(1)

    win = ImageViewerWindow(sys.argv[1])
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
