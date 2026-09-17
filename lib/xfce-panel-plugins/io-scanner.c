/*
 * io-scanner: xfce4-panel plugin. A second, vertical KITT-style LED sweep
 * whose speed tracks disk I/O throughput (MB/s) instead of CPU load, drawn
 * in green rather than red so the two scanners are never confused at a
 * glance. Ported from kitt-scanner.c -- see that file for the fuller
 * commentary this trims down.
 *
 * Sums throughput across every physical block device in /proc/diskstats
 * (a device counts if /sys/block/<name>/slaves/ is empty -- true for a
 * real disk, false for a partition and false for a dm-crypt/LVM device
 * layered on top of one, which lists its underlying device(s) there) --
 * this avoids both double-counting a partition against its disk *and*
 * double-counting a LUKS/LVM mapper against the physical disk it forwards
 * to, which every full-disk-encrypted Cyberbeest unit has by default.
 * Not hardcoding a device name also means this works whether a machine
 * has one disk or several of wildly different speeds.
 *
 * Sweep speed is not normalized against any "100% load" ceiling either --
 * there's no sane universal answer to "how many MB/s is fast" across
 * unknown hardware (HDD vs SATA SSD vs NVMe, one disk or several). Instead
 * rate = factor * mbps^exponent, an unbounded curve tuned so that each
 * 10x jump in throughput increases the sweep rate by a fixed multiplier
 * (default: doubles) -- this needs no calibration to the machine at all,
 * a slow disk and a fast one both land somewhere sensible on the same
 * curve. max_rate still clamps the top end, but purely as an
 * animation-smoothness limit, not a calibration target.
 *
 * Built as an "external" plugin (X-XFCE-Internal=FALSE), so a crash here
 * takes down only this plugin's process, not the panel.
 */

#include <gtk/gtk.h>
#include <gdk/gdkx.h>
#include <gio/gio.h>
#include <X11/Xlib.h>
#include <X11/extensions/dpms.h>
#include <libxfce4panel/libxfce4panel.h>
#include <libxfce4util/libxfce4util.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SECTOR_BYTES 512.0
#define SYS_BLOCK_DIR "/sys/block/"

#define VERTICAL_WIDTH_FRAC 0.6 /* widget width = panel size * this; height = panel size */
/* NUM_LEDS=6 with bar_h/bar_w below matching fractions makes this LED
 * pitch -- and so led_h/radius -- come out numerically identical to
 * kitt-scanner's own pitch (size*4*0.92/24 == size*0.92/6): same segment
 * size, just rotated 90 degrees. */
#define NUM_LEDS 6
#define LED_GAP_FRAC 0.22
/* Scaled down from kitt-scanner's 2.2 by NUM_LEDS's ratio (6/24): kitt's
 * glow width was tuned as a fraction of its 24-LED bar, and reusing the
 * same absolute value against only 6 LEDs left most of the bar lit at
 * once instead of a short bright streak fading quickly. */
#define GLOW_WIDTH 0.55
#define GLOW_CUTOFF_SIGMAS 3.5
#define DEFAULT_FPS 40
#define MIN_FPS 1
#define MAX_FPS 60

#define DEFAULT_MIN_RATE 0.0
#define DEFAULT_MAX_RATE 2.86
/* rate = factor * mbps^exponent. exponent = log10(2) means each 10x jump
 * in MB/s doubles the sweep rate (10->0.5, 100->1.0, 1000->2.0 sweeps/sec
 * with the defaults below) -- picked by feel, not measurement. */
#define DEFAULT_FACTOR 0.25
#define DEFAULT_EXPONENT 0.301
#define IO_SAMPLE_MS 500
#define IO_SMOOTHING 0.35
#define MIN_REDRAW_DELTA_PX 1.0
#define CENTER_PHASE 0.5
#define SCREEN_CHECK_INTERVAL_S 2
#define DBUS_CALL_TIMEOUT_MS 300
#define TOOLTIP_REFRESH_INTERVAL_S 3

static const gdouble DEFAULT_BG[3] = { 0.9647, 0.9608, 0.9569 };
static const gdouble DIM_LED_OFF[3] = { 0.0, 0.20, 0.05 };
static const gdouble LED_ON[3] = { 0.0, 0.60, 0.08 };

typedef struct {
    XfcePanelPlugin *plugin;
    GtkWidget *area;

    gdouble io_mbps; /* smoothed combined read+write throughput, MB/s, unbounded */
    gdouble read_mbps, write_mbps;
    gdouble phase;
    gdouble prev_eye_pos;
    gint64 last_tick_us;

    gdouble min_rate, max_rate, factor, exponent;
    gint fps;
    gboolean off_is_bg;
    gboolean sine_sweep;
    gboolean enabled;
    gboolean paused;
    gboolean show_rate;
    gint shown_mbps; /* rounded MB/s as of the last repaint, -1 = none yet */
    gdouble bg[3];

    long prev_sectors_read, prev_sectors_written;
    gint64 prev_sample_us;

    guint sample_id;
    guint tick_id;
    guint screen_check_id;
    guint tooltip_refresh_id;
    GDBusConnection *dbus_conn;
} IoPlugin;

/* A name counts as a physical disk iff /sys/block/<name>/slaves/ exists
 * and is empty. Partitions (sda1, nvme0n1p1, mmcblk0p1, ...) never get
 * their own /sys/block entry at all, so they're excluded automatically.
 * A dm-crypt or LVM device does get its own entry, but its slaves/
 * directory lists the physical device(s) underneath it -- so checking
 * for an *empty* slaves/ (rather than just "the entry exists") is what
 * excludes those layered devices and avoids counting the same I/O twice. */
static gboolean
is_physical_disk(const gchar *name)
{
    gchar path[160];
    g_snprintf(path, sizeof(path), SYS_BLOCK_DIR "%s/slaves", name);

    GDir *dir = g_dir_open(path, 0, NULL);
    if (!dir)
        return FALSE; /* no slaves/ at all -- not a real block device entry */

    gboolean empty = (g_dir_read_name(dir) == NULL);
    g_dir_close(dir);
    return empty;
}

static gboolean
sample_disk_io(IoPlugin *kp)
{
    FILE *f = fopen("/proc/diskstats", "r");
    if (!f)
        return FALSE;

    gchar line[512];
    long rd_sectors_total = 0, wr_sectors_total = 0;
    gboolean any = FALSE;
    while (fgets(line, sizeof(line), f)) {
        int major, minor;
        gchar name[64];
        long rd_ios, rd_merges, rd_ticks, wr_ios, wr_merges, wr_ticks;
        long rs, ws;
        int n = sscanf(line, "%d %d %63s %ld %ld %ld %ld %ld %ld %ld %ld",
                       &major, &minor, name, &rd_ios, &rd_merges, &rs, &rd_ticks,
                       &wr_ios, &wr_merges, &ws, &wr_ticks);
        if (n < 11)
            continue;
        if (!is_physical_disk(name))
            continue;
        rd_sectors_total += rs;
        wr_sectors_total += ws;
        any = TRUE;
    }
    fclose(f);
    if (!any)
        return FALSE;

    gint64 now = g_get_monotonic_time();
    gdouble dt = (kp->prev_sample_us == 0) ? 0.0 : (now - kp->prev_sample_us) / 1e6;
    kp->prev_sample_us = now;

    if (dt > 0.0 && kp->prev_sectors_read >= 0) {
        long d_read = rd_sectors_total - kp->prev_sectors_read;
        long d_write = wr_sectors_total - kp->prev_sectors_written;
        kp->read_mbps = (d_read * SECTOR_BYTES / 1e6) / dt;
        kp->write_mbps = (d_write * SECTOR_BYTES / 1e6) / dt;

        gdouble instant = kp->read_mbps + kp->write_mbps;
        kp->io_mbps += (instant - kp->io_mbps) * IO_SMOOTHING;
    }
    kp->prev_sectors_read = rd_sectors_total;
    kp->prev_sectors_written = wr_sectors_total;
    return TRUE;
}

static gboolean
on_sample(gpointer user_data)
{
    sample_disk_io((IoPlugin *) user_data);
    return G_SOURCE_CONTINUE;
}

/* Rough, machine-agnostic MB/s bands for the tooltip label -- these are
 * just descriptive words, not tied to the sweep-rate formula above. */
static const gchar *
io_status_text(gdouble mbps)
{
    if (mbps < 1.0)
        return "= Idle =";
    if (mbps < 20.0)
        return "= Light I/O =";
    if (mbps < 100.0)
        return "= Busy =";
    if (mbps < 400.0)
        return "= Heavy I/O =";
    return "= Very Heavy I/O =";
}

static gboolean
on_query_tooltip(GtkWidget *widget, gint x, gint y, gboolean keyboard_mode,
                  GtkTooltip *tooltip, gpointer user_data)
{
    IoPlugin *kp = user_data;
    gchar buf[256];
    g_snprintf(buf, sizeof(buf), "Disk I/O: %.1f MB/s (read %.1f, write %.1f)\n%s",
               kp->read_mbps + kp->write_mbps, kp->read_mbps, kp->write_mbps,
               io_status_text(kp->io_mbps));
    gtk_tooltip_set_text(tooltip, buf);
    return TRUE;
}

static gboolean
on_tooltip_refresh_tick(gpointer user_data)
{
    IoPlugin *kp = user_data;
    gtk_widget_trigger_tooltip_query(kp->area);
    return G_SOURCE_CONTINUE;
}

static gboolean
on_area_enter(GtkWidget *widget, GdkEventCrossing *event, gpointer user_data)
{
    IoPlugin *kp = user_data;
    if (kp->tooltip_refresh_id == 0)
        kp->tooltip_refresh_id = g_timeout_add_seconds(TOOLTIP_REFRESH_INTERVAL_S, on_tooltip_refresh_tick, kp);
    return FALSE;
}

static gboolean
on_area_leave(GtkWidget *widget, GdkEventCrossing *event, gpointer user_data)
{
    IoPlugin *kp = user_data;
    if (kp->tooltip_refresh_id != 0) {
        g_source_remove(kp->tooltip_refresh_id);
        kp->tooltip_refresh_id = 0;
    }
    return FALSE;
}

typedef struct {
    gdouble bar_x, bar_y, bar_w, bar_h;
    gdouble pitch, led_h, radius;
} BarLayout;

/* Vertical counterpart of kitt-scanner's compute_layout: the LED strip
 * runs top-to-bottom instead of left-to-right, so height plays the role
 * width used to. */
static void
compute_layout(gdouble w, gdouble h, BarLayout *lay)
{
    lay->bar_h = h * 0.92;
    lay->bar_w = h * 0.5; /* thickness keyed off h (== panel size), same fraction kitt-scanner uses */
    lay->bar_x = (w - lay->bar_w) / 2;
    lay->bar_y = (h - lay->bar_h) / 2;

    lay->pitch = lay->bar_h / NUM_LEDS;
    lay->led_h = lay->pitch * (1 - LED_GAP_FRAC);
    lay->radius = MIN(lay->led_h, lay->bar_w) / 2;
}

static gdouble
eye_pos_for_phase(gdouble phase, gboolean sine_sweep)
{
    gdouble frac = phase <= 1.0 ? phase : 2.0 - phase;
    gdouble shaped = sine_sweep ? (1 - cos(frac * M_PI)) / 2.0 : frac;
    return shaped * (NUM_LEDS - 1);
}

static void
rounded_rect(cairo_t *cr, gdouble x, gdouble y, gdouble w, gdouble h, gdouble r)
{
    r = MIN(r, MIN(w / 2, h / 2));
    cairo_new_sub_path(cr);
    cairo_arc(cr, x + w - r, y + r, r, -M_PI / 2, 0);
    cairo_arc(cr, x + w - r, y + h - r, r, 0, M_PI / 2);
    cairo_arc(cr, x + r, y + h - r, r, M_PI / 2, M_PI);
    cairo_arc(cr, x + r, y + r, r, M_PI, 3 * M_PI / 2);
    cairo_close_path(cr);
}

static gboolean
on_tick(gpointer user_data)
{
    IoPlugin *kp = user_data;

    gint64 now = g_get_monotonic_time();
    gdouble dt = (now - kp->last_tick_us) / 1e6;
    kp->last_tick_us = now;

    gdouble rate = kp->min_rate + kp->factor * pow(MAX(kp->io_mbps, 0.0), kp->exponent);
    rate = CLAMP(rate, kp->min_rate, kp->max_rate);
    if (rate <= 0.0)
        return G_SOURCE_CONTINUE;

    kp->phase = fmod(kp->phase + dt * rate, 2.0);
    gdouble new_eye_pos = eye_pos_for_phase(kp->phase, kp->sine_sweep);

    GtkAllocation alloc;
    gtk_widget_get_allocation(kp->area, &alloc);
    BarLayout lay;
    compute_layout(alloc.width, alloc.height, &lay);

    if (kp->show_rate) {
        gboolean eye_moved = fabs(new_eye_pos - kp->prev_eye_pos) * lay.pitch >= MIN_REDRAW_DELTA_PX;
        gint mbps = (gint) lround(kp->read_mbps + kp->write_mbps);
        kp->prev_eye_pos = new_eye_pos;
        if (!eye_moved && mbps == kp->shown_mbps)
            return G_SOURCE_CONTINUE;
        kp->shown_mbps = mbps;
        gtk_widget_queue_draw(kp->area);
        return G_SOURCE_CONTINUE;
    }

    gdouble px_delta = fabs(new_eye_pos - kp->prev_eye_pos) * lay.pitch;
    if (px_delta < MIN_REDRAW_DELTA_PX)
        return G_SOURCE_CONTINUE;

    gdouble lo = MIN(kp->prev_eye_pos, new_eye_pos);
    gdouble hi = MAX(kp->prev_eye_pos, new_eye_pos);
    kp->prev_eye_pos = new_eye_pos;

    gdouble margin = GLOW_WIDTH * GLOW_CUTOFF_SIGMAS;
    gint y0 = (gint) floor(lay.bar_y + (lo - margin) * lay.pitch);
    gint y1 = (gint) ceil(lay.bar_y + (hi + margin) * lay.pitch + lay.led_h);
    y0 = CLAMP(y0, 0, alloc.height);
    y1 = CLAMP(y1, 0, alloc.height);

    gint x0 = (gint) floor(lay.bar_x) - 1;
    gint x1 = (gint) ceil(lay.bar_x + lay.bar_w) + 1;
    x0 = CLAMP(x0, 0, alloc.width);
    x1 = CLAMP(x1, 0, alloc.width);

    gtk_widget_queue_draw_area(kp->area, x0, y0, x1 - x0, y1 - y0);
    return G_SOURCE_CONTINUE;
}

static gboolean
on_draw(GtkWidget *widget, cairo_t *cr, gpointer user_data)
{
    IoPlugin *kp = user_data;
    GtkAllocation alloc;
    gtk_widget_get_allocation(widget, &alloc);
    gdouble w = alloc.width, h = alloc.height;

    cairo_set_source_rgb(cr, kp->bg[0], kp->bg[1], kp->bg[2]);
    cairo_paint(cr);

    gdouble eye_pos = eye_pos_for_phase(kp->phase, kp->sine_sweep);

    BarLayout lay;
    compute_layout(w, h, &lay);

    gdouble hard_cutoff = GLOW_WIDTH * GLOW_CUTOFF_SIGMAS;
    const gdouble *led_off = kp->off_is_bg ? kp->bg : DIM_LED_OFF;

    for (int i = 0; i < NUM_LEDS; i++) {
        gdouble dist = fabs(i - eye_pos);
        gdouble brightness = dist > hard_cutoff
            ? 0.0
            : exp(-(dist * dist) / (2 * GLOW_WIDTH * GLOW_WIDTH));

        gdouble r = led_off[0] + (LED_ON[0] - led_off[0]) * brightness;
        gdouble g = led_off[1] + (LED_ON[1] - led_off[1]) * brightness;
        gdouble b = led_off[2] + (LED_ON[2] - led_off[2]) * brightness;

        gdouble y = lay.bar_y + i * lay.pitch + (lay.pitch - lay.led_h) / 2;

        cairo_set_source_rgb(cr, r, g, b);
        rounded_rect(cr, lay.bar_x, y, lay.bar_w, lay.led_h, lay.radius);
        cairo_fill(cr);
    }

    if (kp->show_rate) {
        gchar buf[8];
        gint mbps = (gint) lround(kp->read_mbps + kp->write_mbps);
        g_snprintf(buf, sizeof(buf), "%d", mbps);

        cairo_text_extents_t ext;
        cairo_select_font_face(cr, "sans-serif", CAIRO_FONT_SLANT_NORMAL, CAIRO_FONT_WEIGHT_BOLD);
        cairo_set_font_size(cr, h * 0.28);
        cairo_text_extents(cr, buf, &ext);

        gdouble tx = w / 2.0 - (ext.width / 2.0 + ext.x_bearing);
        gdouble ty = h / 2.0 - (ext.height / 2.0 + ext.y_bearing);

        cairo_move_to(cr, tx, ty);
        cairo_text_path(cr, buf);
        cairo_set_line_width(cr, h * 0.05);
        cairo_set_source_rgba(cr, 1.0, 1.0, 1.0, 0.55);
        cairo_stroke_preserve(cr);
        cairo_set_source_rgba(cr, 0.0, 0.0, 0.0, 0.88);
        cairo_fill(cr);
    }

    return TRUE;
}

static void
io_load_settings(IoPlugin *kp)
{
    kp->min_rate = DEFAULT_MIN_RATE;
    kp->max_rate = DEFAULT_MAX_RATE;
    kp->factor = DEFAULT_FACTOR;
    kp->exponent = DEFAULT_EXPONENT;
    kp->fps = DEFAULT_FPS;
    kp->off_is_bg = TRUE; /* unlit LEDs fade into the panel's own gray, not a dark housing color */
    kp->sine_sweep = TRUE;
    kp->enabled = TRUE;
    kp->show_rate = FALSE;
    memcpy(kp->bg, DEFAULT_BG, sizeof(kp->bg));

    gchar *file = xfce_panel_plugin_save_location(kp->plugin, FALSE);
    if (!file)
        return;

    XfceRc *rc = xfce_rc_simple_open(file, TRUE);
    g_free(file);
    if (!rc)
        return;

    xfce_rc_set_group(rc, "General");
    kp->min_rate = g_ascii_strtod(xfce_rc_read_entry(rc, "MinRate", "0"), NULL);
    kp->max_rate = g_ascii_strtod(xfce_rc_read_entry(rc, "MaxRate", "2.86"), NULL);
    kp->factor = g_ascii_strtod(xfce_rc_read_entry(rc, "Factor", "0.25"), NULL);
    kp->exponent = g_ascii_strtod(xfce_rc_read_entry(rc, "Exponent", "0.301"), NULL);
    kp->fps = xfce_rc_read_int_entry(rc, "FPS", DEFAULT_FPS);
    kp->fps = CLAMP(kp->fps, MIN_FPS, MAX_FPS);
    kp->off_is_bg = xfce_rc_read_bool_entry(rc, "OffIsBg", TRUE);
    kp->sine_sweep = xfce_rc_read_bool_entry(rc, "SineSweep", TRUE);
    kp->enabled = xfce_rc_read_bool_entry(rc, "Enabled", TRUE);
    kp->show_rate = xfce_rc_read_bool_entry(rc, "ShowRate", FALSE);

    const gchar *color_str = xfce_rc_read_entry(rc, "MarginColor", NULL);
    if (color_str) {
        GdkRGBA rgba;
        if (gdk_rgba_parse(&rgba, color_str)) {
            kp->bg[0] = rgba.red;
            kp->bg[1] = rgba.green;
            kp->bg[2] = rgba.blue;
        }
    }
    xfce_rc_close(rc);
}

static void
io_save_settings(IoPlugin *kp)
{
    gchar *file = xfce_panel_plugin_save_location(kp->plugin, TRUE);
    if (!file)
        return;

    XfceRc *rc = xfce_rc_simple_open(file, FALSE);
    g_free(file);
    if (!rc)
        return;

    gchar buf[G_ASCII_DTOSTR_BUF_SIZE];
    GdkRGBA rgba = { kp->bg[0], kp->bg[1], kp->bg[2], 1.0 };
    gchar *color_str = gdk_rgba_to_string(&rgba);

    xfce_rc_set_group(rc, "General");
    xfce_rc_write_entry(rc, "MinRate", g_ascii_dtostr(buf, sizeof(buf), kp->min_rate));
    xfce_rc_write_entry(rc, "MaxRate", g_ascii_dtostr(buf, sizeof(buf), kp->max_rate));
    xfce_rc_write_entry(rc, "Factor", g_ascii_dtostr(buf, sizeof(buf), kp->factor));
    xfce_rc_write_entry(rc, "Exponent", g_ascii_dtostr(buf, sizeof(buf), kp->exponent));
    xfce_rc_write_int_entry(rc, "FPS", kp->fps);
    xfce_rc_write_bool_entry(rc, "OffIsBg", kp->off_is_bg);
    xfce_rc_write_bool_entry(rc, "SineSweep", kp->sine_sweep);
    xfce_rc_write_bool_entry(rc, "Enabled", kp->enabled);
    xfce_rc_write_bool_entry(rc, "ShowRate", kp->show_rate);
    xfce_rc_write_entry(rc, "MarginColor", color_str);
    g_free(color_str);
    xfce_rc_close(rc);
}

static gboolean
display_is_off(IoPlugin *kp)
{
    Display *dpy = GDK_DISPLAY_XDISPLAY(gtk_widget_get_display(GTK_WIDGET(kp->plugin)));

    int event_base, error_base;
    if (!DPMSQueryExtension(dpy, &event_base, &error_base))
        return FALSE;

    BOOL onoff = FALSE;
    CARD16 power_level = DPMSModeOn;
    if (!DPMSInfo(dpy, &power_level, &onoff))
        return FALSE;

    return onoff && power_level != DPMSModeOn;
}

static gboolean
query_screensaver_active(GDBusConnection *conn, const gchar *bus_name,
                          const gchar *object_path, const gchar *interface_name)
{
    if (!conn)
        return FALSE;

    GVariant *result = g_dbus_connection_call_sync(
        conn, bus_name, object_path, interface_name, "GetActive",
        NULL, G_VARIANT_TYPE("(b)"), G_DBUS_CALL_FLAGS_NONE,
        DBUS_CALL_TIMEOUT_MS, NULL, NULL);
    if (!result)
        return FALSE;

    gboolean active = FALSE;
    g_variant_get(result, "(b)", &active);
    g_variant_unref(result);
    return active;
}

static gboolean
screensaver_is_active(IoPlugin *kp)
{
    return query_screensaver_active(kp->dbus_conn, "org.freedesktop.ScreenSaver",
                                     "/org/freedesktop/ScreenSaver", "org.freedesktop.ScreenSaver")
        || query_screensaver_active(kp->dbus_conn, "org.xfce.ScreenSaver",
                                     "/org/xfce/ScreenSaver", "org.xfce.ScreenSaver");
}

static void
io_restart_tick_timer(IoPlugin *kp)
{
    if (kp->tick_id != 0)
        g_source_remove(kp->tick_id);
    kp->tick_id = g_timeout_add(1000 / kp->fps, on_tick, kp);
}

static void
io_maybe_start_tick_timer(IoPlugin *kp)
{
    if (!kp->enabled || kp->paused || kp->tick_id != 0)
        return;
    kp->last_tick_us = g_get_monotonic_time();
    io_restart_tick_timer(kp);
}

static void
io_stop_tick_timer(IoPlugin *kp)
{
    if (kp->tick_id != 0) {
        g_source_remove(kp->tick_id);
        kp->tick_id = 0;
    }
}

static gboolean
on_screen_check_tick(gpointer user_data)
{
    IoPlugin *kp = user_data;

    gboolean should_pause = display_is_off(kp) || screensaver_is_active(kp);
    if (should_pause != kp->paused) {
        kp->paused = should_pause;
        if (kp->paused)
            io_stop_tick_timer(kp);
        else
            io_maybe_start_tick_timer(kp);
    }
    return G_SOURCE_CONTINUE;
}

static void
on_min_rate_changed(GtkSpinButton *spin, IoPlugin *kp)
{
    kp->min_rate = gtk_spin_button_get_value(spin);
    io_save_settings(kp);
}

static void
on_max_rate_changed(GtkSpinButton *spin, IoPlugin *kp)
{
    kp->max_rate = gtk_spin_button_get_value(spin);
    io_save_settings(kp);
}

static void
on_factor_changed(GtkSpinButton *spin, IoPlugin *kp)
{
    kp->factor = gtk_spin_button_get_value(spin);
    io_save_settings(kp);
}

static void
on_exponent_changed(GtkSpinButton *spin, IoPlugin *kp)
{
    kp->exponent = gtk_spin_button_get_value(spin);
    io_save_settings(kp);
}

static void
on_fps_changed(GtkSpinButton *spin, IoPlugin *kp)
{
    kp->fps = gtk_spin_button_get_value_as_int(spin);
    if (kp->tick_id != 0)
        io_restart_tick_timer(kp);
    io_save_settings(kp);
}

static void
on_enabled_toggled(GtkToggleButton *toggle, IoPlugin *kp)
{
    kp->enabled = gtk_toggle_button_get_active(toggle);

    if (!kp->enabled) {
        io_stop_tick_timer(kp);
        kp->phase = CENTER_PHASE;
        kp->prev_eye_pos = eye_pos_for_phase(kp->phase, kp->sine_sweep);
        gtk_widget_queue_draw(kp->area);
    } else {
        io_maybe_start_tick_timer(kp);
    }

    io_save_settings(kp);
}

static void
on_margin_color_set(GtkColorButton *button, IoPlugin *kp)
{
    GdkRGBA rgba;
    gtk_color_chooser_get_rgba(GTK_COLOR_CHOOSER(button), &rgba);
    kp->bg[0] = rgba.red;
    kp->bg[1] = rgba.green;
    kp->bg[2] = rgba.blue;
    gtk_widget_queue_draw(kp->area);
    io_save_settings(kp);
}

static void
on_off_is_bg_toggled(GtkToggleButton *toggle, IoPlugin *kp)
{
    kp->off_is_bg = gtk_toggle_button_get_active(toggle);
    gtk_widget_queue_draw(kp->area);
    io_save_settings(kp);
}

static void
on_show_rate_toggled(GtkToggleButton *toggle, IoPlugin *kp)
{
    kp->show_rate = gtk_toggle_button_get_active(toggle);
    gtk_widget_queue_draw(kp->area);
    io_save_settings(kp);
}

static void
on_sweep_pattern_changed(GtkToggleButton *toggle, IoPlugin *kp)
{
    if (!gtk_toggle_button_get_active(toggle))
        return;
    kp->sine_sweep = GPOINTER_TO_INT(g_object_get_data(G_OBJECT(toggle), "sine-sweep"));
    gtk_widget_queue_draw(kp->area);
    io_save_settings(kp);
}

static void
on_configure_plugin(XfcePanelPlugin *plugin, IoPlugin *kp)
{
    GtkWidget *dialog = gtk_dialog_new_with_buttons(
        "I/O Scanner", GTK_WINDOW(gtk_widget_get_toplevel(GTK_WIDGET(plugin))),
        GTK_DIALOG_DESTROY_WITH_PARENT, "_Close", GTK_RESPONSE_CLOSE, NULL);
    gtk_window_set_icon_name(GTK_WINDOW(dialog), "drive-harddisk");

    GtkWidget *grid = gtk_grid_new();
    gtk_grid_set_row_spacing(GTK_GRID(grid), 6);
    gtk_grid_set_column_spacing(GTK_GRID(grid), 12);
    gtk_container_set_border_width(GTK_CONTAINER(grid), 12);

    GtkWidget *enabled_check = gtk_check_button_new_with_label("Enabled (off freezes the scanner, centered)");
    gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(enabled_check), kp->enabled);
    g_signal_connect(enabled_check, "toggled", G_CALLBACK(on_enabled_toggled), kp);
    gtk_grid_attach(GTK_GRID(grid), enabled_check, 0, 8, 2, 1);

    GtkWidget *min_label = gtk_label_new("Min speed (idle disk), sweeps/sec:");
    gtk_widget_set_halign(min_label, GTK_ALIGN_START);
    GtkWidget *min_spin = gtk_spin_button_new_with_range(0.0, 10.0, 0.05);
    gtk_spin_button_set_value(GTK_SPIN_BUTTON(min_spin), kp->min_rate);
    g_signal_connect(min_spin, "value-changed", G_CALLBACK(on_min_rate_changed), kp);

    GtkWidget *max_label = gtk_label_new("Max speed (full-scale I/O), sweeps/sec:");
    gtk_widget_set_halign(max_label, GTK_ALIGN_START);
    GtkWidget *max_spin = gtk_spin_button_new_with_range(0.0, 10.0, 0.05);
    gtk_spin_button_set_value(GTK_SPIN_BUTTON(max_spin), kp->max_rate);
    g_signal_connect(max_spin, "value-changed", G_CALLBACK(on_max_rate_changed), kp);

    GtkWidget *factor_label = gtk_label_new("Rate factor (rate = factor * MB/s ^ exponent):");
    gtk_widget_set_halign(factor_label, GTK_ALIGN_START);
    GtkWidget *factor_spin = gtk_spin_button_new_with_range(0.001, 10.0, 0.01);
    gtk_spin_button_set_digits(GTK_SPIN_BUTTON(factor_spin), 3);
    gtk_spin_button_set_value(GTK_SPIN_BUTTON(factor_spin), kp->factor);
    g_signal_connect(factor_spin, "value-changed", G_CALLBACK(on_factor_changed), kp);

    GtkWidget *exponent_label = gtk_label_new("Rate exponent (0.301 = doubles every 10x MB/s):");
    gtk_widget_set_halign(exponent_label, GTK_ALIGN_START);
    GtkWidget *exponent_spin = gtk_spin_button_new_with_range(0.01, 2.0, 0.01);
    gtk_spin_button_set_digits(GTK_SPIN_BUTTON(exponent_spin), 3);
    gtk_spin_button_set_value(GTK_SPIN_BUTTON(exponent_spin), kp->exponent);
    g_signal_connect(exponent_spin, "value-changed", G_CALLBACK(on_exponent_changed), kp);

    GtkWidget *fps_label = gtk_label_new("Frame rate, fps:");
    gtk_widget_set_halign(fps_label, GTK_ALIGN_START);
    GtkWidget *fps_spin = gtk_spin_button_new_with_range(MIN_FPS, MAX_FPS, 1);
    gtk_spin_button_set_value(GTK_SPIN_BUTTON(fps_spin), kp->fps);
    g_signal_connect(fps_spin, "value-changed", G_CALLBACK(on_fps_changed), kp);

    gtk_grid_attach(GTK_GRID(grid), min_label, 0, 0, 1, 1);
    gtk_grid_attach(GTK_GRID(grid), min_spin, 1, 0, 1, 1);
    gtk_grid_attach(GTK_GRID(grid), max_label, 0, 1, 1, 1);
    gtk_grid_attach(GTK_GRID(grid), max_spin, 1, 1, 1, 1);
    gtk_grid_attach(GTK_GRID(grid), factor_label, 0, 2, 1, 1);
    gtk_grid_attach(GTK_GRID(grid), factor_spin, 1, 2, 1, 1);
    gtk_grid_attach(GTK_GRID(grid), exponent_label, 0, 3, 1, 1);
    gtk_grid_attach(GTK_GRID(grid), exponent_spin, 1, 3, 1, 1);
    gtk_grid_attach(GTK_GRID(grid), fps_label, 0, 4, 1, 1);
    gtk_grid_attach(GTK_GRID(grid), fps_spin, 1, 4, 1, 1);

    GtkWidget *margin_label = gtk_label_new("Margin color:");
    gtk_widget_set_halign(margin_label, GTK_ALIGN_START);
    GdkRGBA margin_rgba = { kp->bg[0], kp->bg[1], kp->bg[2], 1.0 };
    GtkWidget *margin_button = gtk_color_button_new_with_rgba(&margin_rgba);
    gtk_color_chooser_set_use_alpha(GTK_COLOR_CHOOSER(margin_button), FALSE);
    g_signal_connect(margin_button, "color-set", G_CALLBACK(on_margin_color_set), kp);
    gtk_grid_attach(GTK_GRID(grid), margin_label, 0, 5, 1, 1);
    gtk_grid_attach(GTK_GRID(grid), margin_button, 1, 5, 1, 1);

    GtkWidget *off_check = gtk_check_button_new_with_label("\"Off\" LEDs are fully invisible (vs. dim housing color)");
    gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(off_check), kp->off_is_bg);
    g_signal_connect(off_check, "toggled", G_CALLBACK(on_off_is_bg_toggled), kp);
    gtk_grid_attach(GTK_GRID(grid), off_check, 0, 6, 2, 1);

    GtkWidget *rate_check = gtk_check_button_new_with_label("Show MB/s number over the LEDs");
    gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(rate_check), kp->show_rate);
    g_signal_connect(rate_check, "toggled", G_CALLBACK(on_show_rate_toggled), kp);
    gtk_grid_attach(GTK_GRID(grid), rate_check, 0, 7, 2, 1);

    GtkWidget *sine_radio = gtk_radio_button_new_with_label(NULL, "Sine wave (eases at each end)");
    g_object_set_data(G_OBJECT(sine_radio), "sine-sweep", GINT_TO_POINTER(TRUE));
    GtkWidget *linear_radio = gtk_radio_button_new_with_label_from_widget(
        GTK_RADIO_BUTTON(sine_radio), "Linear (constant speed)");
    g_object_set_data(G_OBJECT(linear_radio), "sine-sweep", GINT_TO_POINTER(FALSE));
    gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(kp->sine_sweep ? sine_radio : linear_radio), TRUE);
    g_signal_connect(sine_radio, "toggled", G_CALLBACK(on_sweep_pattern_changed), kp);
    g_signal_connect(linear_radio, "toggled", G_CALLBACK(on_sweep_pattern_changed), kp);
    gtk_grid_attach(GTK_GRID(grid), sine_radio, 0, 9, 2, 1);
    gtk_grid_attach(GTK_GRID(grid), linear_radio, 0, 10, 2, 1);

    gtk_container_add(GTK_CONTAINER(gtk_dialog_get_content_area(GTK_DIALOG(dialog))), grid);
    gtk_widget_show_all(dialog);

    g_signal_connect(dialog, "response", G_CALLBACK(gtk_widget_destroy), NULL);
}

static gboolean
on_size_changed(XfcePanelPlugin *plugin, guint size, IoPlugin *kp)
{
    gtk_widget_set_size_request(kp->area, (gint) lround(size * VERTICAL_WIDTH_FRAC), size);
    gtk_widget_queue_draw(kp->area);
    return TRUE;
}

static void
io_free(XfcePanelPlugin *plugin, IoPlugin *kp)
{
    if (kp->sample_id != 0)
        g_source_remove(kp->sample_id);
    if (kp->tick_id != 0)
        g_source_remove(kp->tick_id);
    if (kp->screen_check_id != 0)
        g_source_remove(kp->screen_check_id);
    if (kp->tooltip_refresh_id != 0)
        g_source_remove(kp->tooltip_refresh_id);
    if (kp->dbus_conn)
        g_object_unref(kp->dbus_conn);
    g_free(kp);
}

static void
io_construct(XfcePanelPlugin *plugin)
{
    IoPlugin *kp = g_new0(IoPlugin, 1);
    kp->plugin = plugin;
    kp->last_tick_us = g_get_monotonic_time();
    kp->shown_mbps = -1;
    kp->prev_sectors_read = -1;
    io_load_settings(kp);
    kp->dbus_conn = g_bus_get_sync(G_BUS_TYPE_SESSION, NULL, NULL);

    kp->area = gtk_drawing_area_new();
    gtk_widget_add_events(kp->area, GDK_BUTTON_PRESS_MASK | GDK_BUTTON_RELEASE_MASK
                           | GDK_ENTER_NOTIFY_MASK | GDK_LEAVE_NOTIFY_MASK);
    g_signal_connect(kp->area, "draw", G_CALLBACK(on_draw), kp);
    gtk_widget_set_has_tooltip(kp->area, TRUE);
    g_signal_connect(kp->area, "query-tooltip", G_CALLBACK(on_query_tooltip), kp);
    g_signal_connect(kp->area, "enter-notify-event", G_CALLBACK(on_area_enter), kp);
    g_signal_connect(kp->area, "leave-notify-event", G_CALLBACK(on_area_leave), kp);

    gtk_container_add(GTK_CONTAINER(plugin), kp->area);
    gtk_widget_show_all(GTK_WIDGET(plugin));
    xfce_panel_plugin_add_action_widget(plugin, kp->area);

    sample_disk_io(kp);
    kp->sample_id = g_timeout_add(IO_SAMPLE_MS, on_sample, kp);

    kp->paused = display_is_off(kp) || screensaver_is_active(kp);
    if (kp->enabled && !kp->paused) {
        io_restart_tick_timer(kp);
    } else if (!kp->enabled) {
        kp->phase = CENTER_PHASE;
        kp->prev_eye_pos = eye_pos_for_phase(kp->phase, kp->sine_sweep);
    }
    kp->screen_check_id = g_timeout_add_seconds(SCREEN_CHECK_INTERVAL_S, on_screen_check_tick, kp);

    g_signal_connect(plugin, "free-data", G_CALLBACK(io_free), kp);
    g_signal_connect(plugin, "size-changed", G_CALLBACK(on_size_changed), kp);
    g_signal_connect(plugin, "configure-plugin", G_CALLBACK(on_configure_plugin), kp);

    xfce_panel_plugin_menu_show_configure(plugin);
    xfce_panel_plugin_set_expand(plugin, FALSE);
}

XFCE_PANEL_PLUGIN_REGISTER(io_construct);
