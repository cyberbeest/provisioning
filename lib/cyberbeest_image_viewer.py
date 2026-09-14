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
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self.connect("realize", self.on_realize)
        self.connect("render", self.on_render)

    def set_zoom_size(self, w, h):
        # The widget's own size *is* the zoom level -- inside a
        # GtkScrolledWindow this can exceed the visible viewport, which is
        # exactly what makes scrollbars appear for zoomed-in content.
        self.set_size_request(w, h)

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
    gamma-correctly on demand. Returns (widget, set_zoom_size) -- the
    caller drives the displayed size the same way it drives
    GLImageArea.set_zoom_size(), there's just a CPU resample behind it
    instead of a live GPU viewport."""
    image_widget = Gtk.Image()
    image_widget.set_halign(Gtk.Align.CENTER)
    image_widget.set_valign(Gtk.Align.CENTER)
    state = {"idx": 0, "size": None, "pixbufs": []}

    def render_at(w, h):
        pixbufs = []
        for frame, duration in frames:
            if (w, h) != frame.size:
                frame = resize_gamma_correct(frame, w, h)
            pixbufs.append((pil_to_pixbuf(frame), duration))
        state["pixbufs"] = pixbufs
        state["size"] = (w, h)
        image_widget.set_size_request(w, h)
        image_widget.set_from_pixbuf(pixbufs[state["idx"] % len(pixbufs)][0])

    def advance():
        pixbufs = state["pixbufs"]
        if not pixbufs:
            return False
        state["idx"] = (state["idx"] + 1) % len(pixbufs)
        pixbuf, duration = pixbufs[state["idx"]]
        image_widget.set_from_pixbuf(pixbuf)
        GLib.timeout_add(duration, advance)
        return False

    def set_zoom_size(w, h):
        if (w, h) != state["size"]:
            render_at(w, h)

    native_w, native_h = frames[0][0].size
    render_at(native_w, native_h)
    if len(frames) > 1:
        GLib.timeout_add(frames[0][1], advance)

    return image_widget, set_zoom_size


_BLACK_BG_CSS = Gtk.CssProvider()
_BLACK_BG_CSS.load_from_data(b"window { background-color: black; }")


ZOOM_STEP = 1.25
MIN_ZOOM_SCALE = 0.02
SELF_CHECK_INTERVAL_S = 2


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

        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.scroller.connect("size-allocate", self.on_viewport_allocate)
        self.add(self.scroller)
        self.scroller.show()

        self.image_widget = None
        self.set_zoom_size = None
        self.native_size = None
        self.is_fullscreen = False
        self.zoom_mode = "fit"  # "fit" tracks the viewport; "manual" holds zoom_scale
        self.zoom_scale = 1.0
        self._last_fit_size = None
        self.drag_state = None
        self.load_image(path, set_initial_size=True)

    def load_image(self, path, set_initial_size=False):
        filename = path.rsplit("/", 1)[-1]
        title_stem = filename.rsplit(".", 1)[0] if "." in filename else filename
        self.set_title(f"{title_stem} - Cyberbeest Images")
        frames, native_size = load_frames(path)
        target_w, target_h = target_display_size(native_size)
        native_w, native_h = native_size
        self.native_size = native_size
        self._last_fit_size = None
        tooltip = f"{path}\n{native_w} × {native_h}\n{human_file_size(os.path.getsize(path))}"

        if self.image_widget is not None:
            self.scroller.remove(self.image_widget)

        if HAVE_GL:
            image_widget = GLImageArea(frames)
            set_zoom_size = image_widget.set_zoom_size
        else:
            image_widget, set_zoom_size = make_cpu_image_widget(frames)

        image_widget.set_tooltip_text(tooltip)
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
        self.scroller.add(image_widget)
        image_widget.show()
        # Only the initial open sizes the window to fit the image/screen;
        # after that the window keeps whatever size the user picked.
        if set_initial_size:
            self.set_default_size(target_w, target_h)
        if self.zoom_mode == "fit":
            self._apply_fit(self.scroller.get_allocation())
        else:
            self._apply_manual_zoom()

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

    def _apply_manual_zoom(self):
        if self.native_size is None or self.set_zoom_size is None:
            return
        nw, nh = self.native_size
        self.set_zoom_size(max(1, round(nw * self.zoom_scale)), max(1, round(nh * self.zoom_scale)))

    def _current_scale(self):
        if self.zoom_mode == "manual" or self.native_size is None:
            return self.zoom_scale
        alloc = self.scroller.get_allocation()
        nw, nh = self.native_size
        if alloc.width <= 0 or alloc.height <= 0:
            return 1.0
        return min(alloc.width / nw, alloc.height / nh)

    def zoom_by(self, factor):
        self.zoom_mode = "manual"
        self.zoom_scale = max(MIN_ZOOM_SCALE, self._current_scale() * factor)
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
        if event.keyval == Gdk.KEY_Left:
            self.show_offset(-1)
            return True
        if event.keyval == Gdk.KEY_Right:
            self.show_offset(1)
            return True
        return False


def _check_self_modified(self_path, initial_mtime):
    """Re-exec the running process if its own script file changed on disk
    (e.g. a git pull + reinstall while it's open), so the user doesn't
    have to notice and manually restart to pick up a fix."""
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
