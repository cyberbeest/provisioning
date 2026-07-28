/*
 * kitt-scanner: xfce4-panel plugin. Knight Rider style LED sweep whose
 * speed is driven by CPU load (same math as the xfce4-screensaver theme
 * this was ported from: kitt-scanner.py's KittWindow).
 * Built as an "external" plugin (X-XFCE-Internal=FALSE in the .desktop
 * file), so a crash in here takes down only this plugin's process, not
 * the panel.
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
#include <string.h>

#define ASPECT_RATIO 4 /* width = panel size * ASPECT_RATIO */
#define NUM_LEDS 24
#define LED_GAP_FRAC 0.22       /* gap between LEDs as a fraction of LED pitch */
#define GLOW_WIDTH 2.2          /* falloff width of the "eye", in LED units */
#define GLOW_CUTOFF_SIGMAS 3.5  /* brightness is negligible beyond this many GLOW_WIDTHs */
#define DEFAULT_FPS 40
#define MIN_FPS 1
#define MAX_FPS 60

#define DEFAULT_MIN_RATE 0.0     /* sweep-lengths/sec at 0% CPU load */
#define DEFAULT_MAX_RATE 2.86    /* sweep-lengths/sec at 100% CPU load */
#define DEFAULT_GAMMA 1.0        /* load exponent: >1 suppresses low load further, <1 boosts it */
#define LOAD_SAMPLE_MS 500        /* how often to read /proc/stat */
#define LOAD_SMOOTHING 0.35       /* exponential smoothing factor for load (0..1) */
#define MIN_REDRAW_DELTA_PX 1.0   /* skip a repaint unless the eye has moved this many pixels */
#define CENTER_PHASE 0.5          /* phase whose eye_pos is dead center, for the off switch */
#define SCREEN_CHECK_INTERVAL_S 2 /* how often to poll for screen lock / display standby */
#define DBUS_CALL_TIMEOUT_MS 300  /* per-call timeout for screensaver-state D-Bus queries */

/* Matches this theme's actual panel background (same value mem-liquid
 * uses, sampled directly off the live panel window: #F6F5F4) so the
 * plugin blends in by default rather than punching a black square into
 * the panel. The original near-black KITT "housing" look is still one
 * click away via the Margin color picker (see MarginColor below) --
 * user-selectable now rather than the X11-pixel-sampling auto-detect
 * this used to have, which was fragile and could land on white. */
static const gdouble DEFAULT_BG[3] = { 0.9647, 0.9608, 0.9569 };
static const gdouble DIM_LED_OFF[3] = { 0.12, 0.0, 0.0 };
static const gdouble LED_ON[3] = { 1.0, 0.05, 0.0 };

typedef struct {
    XfcePanelPlugin *plugin;
    GtkWidget *area;

    gdouble load;      /* smoothed CPU load, 0..1 */
    gdouble phase;      /* 0..2 ping-pong position along the LED bar */
    gdouble prev_eye_pos; /* eye_pos as of the last actual repaint, for damage tracking */
    gint64 last_tick_us;

    gdouble min_rate;  /* sweep-lengths/sec at 0% CPU load */
    gdouble max_rate;  /* sweep-lengths/sec at 100% CPU load */
    gdouble gamma;     /* load exponent applied before mapping to rate */
    gint fps;
    gboolean off_is_bg; /* "off" LEDs are pure background instead of a dim housing color */
    gboolean sine_sweep; /* TRUE: ease in/out (cosine) at the ends; FALSE: constant-speed linear sweep */
    gboolean enabled;  /* FALSE: freeze at dead center, no ticking */
    gboolean paused;   /* TRUE: screen locked or display in standby -- ticking suspended */
    gboolean show_percent; /* draw the CPU load number over the LEDs */
    gint shown_percent;    /* rounded % as of the last repaint, -1 = none yet */
    gdouble bg[3];

    long prev_idle;
    long prev_total;

    guint sample_id;
    guint tick_id;
    guint screen_check_id;
    GDBusConnection *dbus_conn; /* session bus, for screensaver-state queries; may be NULL */
} KittPlugin;

static gboolean
sample_cpu_load(KittPlugin *kp)
{
    FILE *f = fopen("/proc/stat", "r");
    if (!f)
        return FALSE;

    long user, nice, system, idle, iowait, irq, softirq, steal;
    int n = fscanf(f, "cpu %ld %ld %ld %ld %ld %ld %ld %ld",
                   &user, &nice, &system, &idle, &iowait, &irq, &softirq, &steal);
    fclose(f);
    if (n < 8)
        return FALSE;

    long total_idle = idle + iowait;
    long total = user + nice + system + idle + iowait + irq + softirq + steal;
    long d_idle = total_idle - kp->prev_idle;
    long d_total = total - kp->prev_total;
    kp->prev_idle = total_idle;
    kp->prev_total = total;

    if (d_total <= 0)
        return TRUE; /* leave kp->load unchanged on the first sample */

    gdouble instant = 1.0 - ((gdouble) d_idle / (gdouble) d_total);
    if (instant < 0.0)
        instant = 0.0;
    if (instant > 1.0)
        instant = 1.0;

    kp->load += (instant - kp->load) * LOAD_SMOOTHING;
    return TRUE;
}

static gboolean
on_sample(gpointer user_data)
{
    sample_cpu_load((KittPlugin *) user_data);
    return G_SOURCE_CONTINUE;
}

/* Coarse verbal read of CPU load, shown below the percentage in the
 * tooltip -- the numbers alone don't read at a glance. */
static const gchar *
cpu_status_text(gdouble load)
{
    if (load < 0.10)
        return "= Idle =";
    if (load < 0.40)
        return "= Light load =";
    if (load < 0.70)
        return "= Thinking hard =";
    if (load < 0.90)
        return "= Working hard =";
    return "= Maxed out =";
}

static gboolean
on_query_tooltip(GtkWidget *widget, gint x, gint y, gboolean keyboard_mode,
                  GtkTooltip *tooltip, gpointer user_data)
{
    KittPlugin *kp = user_data;
    gchar buf[64];
    g_snprintf(buf, sizeof(buf), "CPU load: %.0f%%\n%s",
               kp->load * 100.0, cpu_status_text(kp->load));
    gtk_tooltip_set_text(tooltip, buf);
    return TRUE;
}

typedef struct {
    gdouble bar_x, bar_y, bar_w, bar_h;
    gdouble pitch, led_w, radius;
} BarLayout;

static void
compute_layout(gdouble w, gdouble h, BarLayout *lay)
{
    lay->bar_w = w * 0.92;
    lay->bar_h = h * 0.5;
    lay->bar_x = (w - lay->bar_w) / 2;
    lay->bar_y = (h - lay->bar_h) / 2;

    lay->pitch = lay->bar_w / NUM_LEDS;
    lay->led_w = lay->pitch * (1 - LED_GAP_FRAC);
    lay->radius = MIN(lay->led_w, lay->bar_h) / 2;
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
    KittPlugin *kp = user_data;

    gint64 now = g_get_monotonic_time();
    gdouble dt = (now - kp->last_tick_us) / 1e6;
    kp->last_tick_us = now;

    gdouble shaped_load = pow(kp->load, kp->gamma);
    gdouble rate = kp->min_rate + (kp->max_rate - kp->min_rate) * shaped_load;
    if (rate <= 0.0)
        return G_SOURCE_CONTINUE; /* both speeds are 0: truly nothing to do */

    /* Always accumulate phase, even on ticks we don't repaint, so slow
     * drift isn't lost -- it just batches up until it crosses a pixel. */
    kp->phase = fmod(kp->phase + dt * rate, 2.0);
    gdouble new_eye_pos = eye_pos_for_phase(kp->phase, kp->sine_sweep);

    GtkAllocation alloc;
    gtk_widget_get_allocation(kp->area, &alloc);
    BarLayout lay;
    compute_layout(alloc.width, alloc.height, &lay);

    if (kp->show_percent) {
        /* Full-widget redraw when the percentage overlay is on, so a load
         * change alone (with the eye barely moving) still keeps the number
         * current -- the fine-grained per-LED invalidation below only
         * tracks the sweep position, not the number's value. But skip the
         * redraw entirely when neither the eye nor the number actually
         * moved, rather than repainting at the full tick rate for nothing. */
        gboolean eye_moved = fabs(new_eye_pos - kp->prev_eye_pos) * lay.pitch >= MIN_REDRAW_DELTA_PX;
        gint percent = (gint) lround(kp->load * 100.0);
        kp->prev_eye_pos = new_eye_pos;
        if (!eye_moved && percent == kp->shown_percent)
            return G_SOURCE_CONTINUE;
        kp->shown_percent = percent;
        gtk_widget_queue_draw(kp->area);
        return G_SOURCE_CONTINUE;
    }

    gdouble px_delta = fabs(new_eye_pos - kp->prev_eye_pos) * lay.pitch;
    if (px_delta < MIN_REDRAW_DELTA_PX)
        return G_SOURCE_CONTINUE; /* nothing visibly moved yet */

    /* Union of the last-painted and new position (each ± the glow's hard
     * cutoff) so any LED that has now crossed the cutoff gets one more
     * paint at the true 0.0 -- otherwise its last-ever paint is the tiny
     * nonzero value from right before it crossed, frozen there forever. */
    gdouble lo = MIN(kp->prev_eye_pos, new_eye_pos);
    gdouble hi = MAX(kp->prev_eye_pos, new_eye_pos);
    kp->prev_eye_pos = new_eye_pos;

    gdouble margin = GLOW_WIDTH * GLOW_CUTOFF_SIGMAS;
    gint x0 = (gint) floor(lay.bar_x + (lo - margin) * lay.pitch);
    gint x1 = (gint) ceil(lay.bar_x + (hi + margin) * lay.pitch + lay.led_w);
    x0 = CLAMP(x0, 0, alloc.width);
    x1 = CLAMP(x1, 0, alloc.width);

    /* floor/ceil (not a plain gint truncation) so a fractional bar_y or
     * bar_h -- routine at odd panel heights -- can't shave a sliver off
     * the bottom edge's invalidation, leaving a stale row of LED pixels
     * behind once the eye moves on. */
    gint y0 = (gint) floor(lay.bar_y) - 1;
    gint y1 = (gint) ceil(lay.bar_y + lay.bar_h) + 1;
    y0 = CLAMP(y0, 0, alloc.height);
    y1 = CLAMP(y1, 0, alloc.height);

    gtk_widget_queue_draw_area(kp->area, x0, y0, x1 - x0, y1 - y0);
    return G_SOURCE_CONTINUE;
}

static gboolean
on_draw(GtkWidget *widget, cairo_t *cr, gpointer user_data)
{
    KittPlugin *kp = user_data;
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
        /* Hard zero past the cutoff (not just asymptotically small): this
         * must exactly match the invalidation margin in on_tick, so any
         * LED that falls outside the repaint window was already painted
         * at its true resting color the last time it was touched. */
        gdouble brightness = dist > hard_cutoff
            ? 0.0
            : exp(-(dist * dist) / (2 * GLOW_WIDTH * GLOW_WIDTH));

        gdouble r = led_off[0] + (LED_ON[0] - led_off[0]) * brightness;
        gdouble g = led_off[1] + (LED_ON[1] - led_off[1]) * brightness;
        gdouble b = led_off[2] + (LED_ON[2] - led_off[2]) * brightness;

        gdouble x = lay.bar_x + i * lay.pitch + (lay.pitch - lay.led_w) / 2;

        cairo_set_source_rgb(cr, r, g, b);
        rounded_rect(cr, x, lay.bar_y, lay.led_w, lay.bar_h, lay.radius);
        cairo_fill(cr);
    }

    if (kp->show_percent) {
        gchar buf[8];
        g_snprintf(buf, sizeof(buf), "%.0f%%", kp->load * 100.0);

        cairo_text_extents_t ext;
        cairo_select_font_face(cr, "sans-serif", CAIRO_FONT_SLANT_NORMAL, CAIRO_FONT_WEIGHT_BOLD);
        cairo_set_font_size(cr, h * 0.32);
        cairo_text_extents(cr, buf, &ext);

        gdouble tx = w / 2.0 - (ext.width / 2.0 + ext.x_bearing);
        gdouble ty = h / 2.0 - (ext.height / 2.0 + ext.y_bearing);

        /* Dark fill with a light halo outline (not a fixed white-on-dark
         * scheme) so it stays legible whether "off" LEDs read as the dim
         * housing color or as the (possibly light) panel background. */
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
kitt_load_settings(KittPlugin *kp)
{
    kp->min_rate = DEFAULT_MIN_RATE;
    kp->max_rate = DEFAULT_MAX_RATE;
    kp->gamma = DEFAULT_GAMMA;
    kp->fps = DEFAULT_FPS;
    kp->off_is_bg = TRUE;
    kp->sine_sweep = TRUE;
    kp->enabled = TRUE;
    kp->show_percent = FALSE;
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
    kp->gamma = g_ascii_strtod(xfce_rc_read_entry(rc, "Gamma", "1.0"), NULL);
    kp->fps = xfce_rc_read_int_entry(rc, "FPS", DEFAULT_FPS);
    kp->fps = CLAMP(kp->fps, MIN_FPS, MAX_FPS);
    kp->off_is_bg = xfce_rc_read_bool_entry(rc, "OffIsBg", TRUE);
    kp->sine_sweep = xfce_rc_read_bool_entry(rc, "SineSweep", TRUE);
    kp->enabled = xfce_rc_read_bool_entry(rc, "Enabled", TRUE);
    kp->show_percent = xfce_rc_read_bool_entry(rc, "ShowPercent", FALSE);

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
kitt_save_settings(KittPlugin *kp)
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
    xfce_rc_write_entry(rc, "Gamma", g_ascii_dtostr(buf, sizeof(buf), kp->gamma));
    xfce_rc_write_int_entry(rc, "FPS", kp->fps);
    xfce_rc_write_bool_entry(rc, "OffIsBg", kp->off_is_bg);
    xfce_rc_write_bool_entry(rc, "SineSweep", kp->sine_sweep);
    xfce_rc_write_bool_entry(rc, "Enabled", kp->enabled);
    xfce_rc_write_bool_entry(rc, "ShowPercent", kp->show_percent);
    xfce_rc_write_entry(rc, "MarginColor", color_str);
    g_free(color_str);
    xfce_rc_close(rc);
}

static gboolean
display_is_off(KittPlugin *kp)
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

/* Both freedesktop-convention screensavers (gnome-screensaver, light-locker,
 * mate-screensaver, cinnamon-screensaver, ...) and xfce4-screensaver's own
 * legacy name expose an identically-shaped GetActive() -> (b) method; try
 * both bus names since only one will actually be running. */
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
screensaver_is_active(KittPlugin *kp)
{
    return query_screensaver_active(kp->dbus_conn, "org.freedesktop.ScreenSaver",
                                     "/org/freedesktop/ScreenSaver", "org.freedesktop.ScreenSaver")
        || query_screensaver_active(kp->dbus_conn, "org.xfce.ScreenSaver",
                                     "/org/xfce/ScreenSaver", "org.xfce.ScreenSaver");
}

static void
kitt_restart_tick_timer(KittPlugin *kp)
{
    if (kp->tick_id != 0)
        g_source_remove(kp->tick_id);
    kp->tick_id = g_timeout_add(1000 / kp->fps, on_tick, kp);
}

/* Starts ticking iff nothing is currently holding it back; a no-op otherwise. */
static void
kitt_maybe_start_tick_timer(KittPlugin *kp)
{
    if (!kp->enabled || kp->paused || kp->tick_id != 0)
        return;
    kp->last_tick_us = g_get_monotonic_time();
    kitt_restart_tick_timer(kp);
}

static void
kitt_stop_tick_timer(KittPlugin *kp)
{
    if (kp->tick_id != 0) {
        g_source_remove(kp->tick_id);
        kp->tick_id = 0;
    }
}

static gboolean
on_screen_check_tick(gpointer user_data)
{
    KittPlugin *kp = user_data;

    gboolean should_pause = display_is_off(kp) || screensaver_is_active(kp);
    if (should_pause != kp->paused) {
        kp->paused = should_pause;
        if (kp->paused)
            kitt_stop_tick_timer(kp);
        else
            kitt_maybe_start_tick_timer(kp);
    }
    return G_SOURCE_CONTINUE;
}

static void
on_min_rate_changed(GtkSpinButton *spin, KittPlugin *kp)
{
    kp->min_rate = gtk_spin_button_get_value(spin);
    kitt_save_settings(kp);
}

static void
on_max_rate_changed(GtkSpinButton *spin, KittPlugin *kp)
{
    kp->max_rate = gtk_spin_button_get_value(spin);
    kitt_save_settings(kp);
}

static void
on_gamma_changed(GtkSpinButton *spin, KittPlugin *kp)
{
    kp->gamma = gtk_spin_button_get_value(spin);
    kitt_save_settings(kp);
}

static void
on_fps_changed(GtkSpinButton *spin, KittPlugin *kp)
{
    kp->fps = gtk_spin_button_get_value_as_int(spin);
    if (kp->tick_id != 0)
        kitt_restart_tick_timer(kp); /* already running: just apply the new rate */
    kitt_save_settings(kp);
}

static void
on_enabled_toggled(GtkToggleButton *toggle, KittPlugin *kp)
{
    kp->enabled = gtk_toggle_button_get_active(toggle);

    if (!kp->enabled) {
        kitt_stop_tick_timer(kp);
        kp->phase = CENTER_PHASE;
        kp->prev_eye_pos = eye_pos_for_phase(kp->phase, kp->sine_sweep);
        gtk_widget_queue_draw(kp->area);
    } else {
        kitt_maybe_start_tick_timer(kp);
    }

    kitt_save_settings(kp);
}

static void
on_margin_color_set(GtkColorButton *button, KittPlugin *kp)
{
    GdkRGBA rgba;
    gtk_color_chooser_get_rgba(GTK_COLOR_CHOOSER(button), &rgba);
    kp->bg[0] = rgba.red;
    kp->bg[1] = rgba.green;
    kp->bg[2] = rgba.blue;
    gtk_widget_queue_draw(kp->area);
    kitt_save_settings(kp);
}

static void
on_off_is_bg_toggled(GtkToggleButton *toggle, KittPlugin *kp)
{
    kp->off_is_bg = gtk_toggle_button_get_active(toggle);
    gtk_widget_queue_draw(kp->area);
    kitt_save_settings(kp);
}

static void
on_show_percent_toggled(GtkToggleButton *toggle, KittPlugin *kp)
{
    kp->show_percent = gtk_toggle_button_get_active(toggle);
    gtk_widget_queue_draw(kp->area);
    kitt_save_settings(kp);
}

static void
on_sweep_pattern_changed(GtkToggleButton *toggle, KittPlugin *kp)
{
    if (!gtk_toggle_button_get_active(toggle))
        return; /* only act on the radio button that just became active */
    kp->sine_sweep = GPOINTER_TO_INT(g_object_get_data(G_OBJECT(toggle), "sine-sweep"));
    gtk_widget_queue_draw(kp->area);
    kitt_save_settings(kp);
}

static void
on_configure_plugin(XfcePanelPlugin *plugin, KittPlugin *kp)
{
    GtkWidget *dialog = gtk_dialog_new_with_buttons(
        "KITT Scanner", GTK_WINDOW(gtk_widget_get_toplevel(GTK_WIDGET(plugin))),
        GTK_DIALOG_DESTROY_WITH_PARENT, "_Close", GTK_RESPONSE_CLOSE, NULL);
    gtk_window_set_icon_name(GTK_WINDOW(dialog), "utilities-system-monitor");

    GtkWidget *grid = gtk_grid_new();
    gtk_grid_set_row_spacing(GTK_GRID(grid), 6);
    gtk_grid_set_column_spacing(GTK_GRID(grid), 12);
    gtk_container_set_border_width(GTK_CONTAINER(grid), 12);

    GtkWidget *enabled_check = gtk_check_button_new_with_label("Enabled (off freezes the scanner, centered)");
    gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(enabled_check), kp->enabled);
    g_signal_connect(enabled_check, "toggled", G_CALLBACK(on_enabled_toggled), kp);
    gtk_grid_attach(GTK_GRID(grid), enabled_check, 0, 9, 2, 1);

    GtkWidget *min_label = gtk_label_new("Min speed (0% CPU load), sweeps/sec:");
    gtk_widget_set_halign(min_label, GTK_ALIGN_START);
    GtkWidget *min_spin = gtk_spin_button_new_with_range(0.0, 10.0, 0.05);
    gtk_spin_button_set_value(GTK_SPIN_BUTTON(min_spin), kp->min_rate);
    g_signal_connect(min_spin, "value-changed", G_CALLBACK(on_min_rate_changed), kp);

    GtkWidget *max_label = gtk_label_new("Max speed (100% CPU load), sweeps/sec:");
    gtk_widget_set_halign(max_label, GTK_ALIGN_START);
    GtkWidget *max_spin = gtk_spin_button_new_with_range(0.0, 10.0, 0.05);
    gtk_spin_button_set_value(GTK_SPIN_BUTTON(max_spin), kp->max_rate);
    g_signal_connect(max_spin, "value-changed", G_CALLBACK(on_max_rate_changed), kp);

    GtkWidget *gamma_label = gtk_label_new("Gamma (>1 slows low load further, <1 speeds it up):");
    gtk_widget_set_halign(gamma_label, GTK_ALIGN_START);
    GtkWidget *gamma_spin = gtk_spin_button_new_with_range(0.1, 10.0, 0.1);
    gtk_spin_button_set_value(GTK_SPIN_BUTTON(gamma_spin), kp->gamma);
    g_signal_connect(gamma_spin, "value-changed", G_CALLBACK(on_gamma_changed), kp);

    GtkWidget *fps_label = gtk_label_new("Frame rate, fps:");
    gtk_widget_set_halign(fps_label, GTK_ALIGN_START);
    GtkWidget *fps_spin = gtk_spin_button_new_with_range(MIN_FPS, MAX_FPS, 1);
    gtk_spin_button_set_value(GTK_SPIN_BUTTON(fps_spin), kp->fps);
    g_signal_connect(fps_spin, "value-changed", G_CALLBACK(on_fps_changed), kp);

    gtk_grid_attach(GTK_GRID(grid), min_label, 0, 0, 1, 1);
    gtk_grid_attach(GTK_GRID(grid), min_spin, 1, 0, 1, 1);
    gtk_grid_attach(GTK_GRID(grid), max_label, 0, 1, 1, 1);
    gtk_grid_attach(GTK_GRID(grid), max_spin, 1, 1, 1, 1);
    gtk_grid_attach(GTK_GRID(grid), gamma_label, 0, 2, 1, 1);
    gtk_grid_attach(GTK_GRID(grid), gamma_spin, 1, 2, 1, 1);
    gtk_grid_attach(GTK_GRID(grid), fps_label, 0, 3, 1, 1);
    gtk_grid_attach(GTK_GRID(grid), fps_spin, 1, 3, 1, 1);

    GtkWidget *margin_label = gtk_label_new("Margin color:");
    gtk_widget_set_halign(margin_label, GTK_ALIGN_START);
    GdkRGBA margin_rgba = { kp->bg[0], kp->bg[1], kp->bg[2], 1.0 };
    GtkWidget *margin_button = gtk_color_button_new_with_rgba(&margin_rgba);
    gtk_color_chooser_set_use_alpha(GTK_COLOR_CHOOSER(margin_button), FALSE);
    g_signal_connect(margin_button, "color-set", G_CALLBACK(on_margin_color_set), kp);
    gtk_grid_attach(GTK_GRID(grid), margin_label, 0, 4, 1, 1);
    gtk_grid_attach(GTK_GRID(grid), margin_button, 1, 4, 1, 1);

    GtkWidget *off_check = gtk_check_button_new_with_label("\"Off\" LEDs are fully invisible (vs. dim housing color)");
    gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(off_check), kp->off_is_bg);
    g_signal_connect(off_check, "toggled", G_CALLBACK(on_off_is_bg_toggled), kp);
    gtk_grid_attach(GTK_GRID(grid), off_check, 0, 5, 2, 1);

    GtkWidget *sweep_label = gtk_label_new("Sweep pattern:");
    gtk_widget_set_halign(sweep_label, GTK_ALIGN_START);
    gtk_grid_attach(GTK_GRID(grid), sweep_label, 0, 6, 2, 1);

    GtkWidget *sine_radio = gtk_radio_button_new_with_label(NULL, "Sine wave (eases at each end)");
    g_object_set_data(G_OBJECT(sine_radio), "sine-sweep", GINT_TO_POINTER(TRUE));
    GtkWidget *linear_radio = gtk_radio_button_new_with_label_from_widget(
        GTK_RADIO_BUTTON(sine_radio), "Linear (constant speed)");
    g_object_set_data(G_OBJECT(linear_radio), "sine-sweep", GINT_TO_POINTER(FALSE));
    gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(kp->sine_sweep ? sine_radio : linear_radio), TRUE);
    g_signal_connect(sine_radio, "toggled", G_CALLBACK(on_sweep_pattern_changed), kp);
    g_signal_connect(linear_radio, "toggled", G_CALLBACK(on_sweep_pattern_changed), kp);
    gtk_grid_attach(GTK_GRID(grid), sine_radio, 0, 7, 2, 1);
    gtk_grid_attach(GTK_GRID(grid), linear_radio, 0, 8, 2, 1);

    GtkWidget *percent_check = gtk_check_button_new_with_label("Show CPU load percentage over the LEDs");
    gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(percent_check), kp->show_percent);
    g_signal_connect(percent_check, "toggled", G_CALLBACK(on_show_percent_toggled), kp);
    gtk_grid_attach(GTK_GRID(grid), percent_check, 0, 10, 2, 1);

    gtk_container_add(GTK_CONTAINER(gtk_dialog_get_content_area(GTK_DIALOG(dialog))), grid);
    gtk_widget_show_all(dialog);

    g_signal_connect(dialog, "response", G_CALLBACK(gtk_widget_destroy), NULL);
}

static gboolean
on_size_changed(XfcePanelPlugin *plugin, guint size, KittPlugin *kp)
{
    gtk_widget_set_size_request(kp->area, size * ASPECT_RATIO, size);
    gtk_widget_queue_draw(kp->area);
    return TRUE;
}

static void
kitt_free(XfcePanelPlugin *plugin, KittPlugin *kp)
{
    if (kp->sample_id != 0)
        g_source_remove(kp->sample_id);
    if (kp->tick_id != 0)
        g_source_remove(kp->tick_id);
    if (kp->screen_check_id != 0)
        g_source_remove(kp->screen_check_id);
    if (kp->dbus_conn)
        g_object_unref(kp->dbus_conn);
    g_free(kp);
}

static void
kitt_construct(XfcePanelPlugin *plugin)
{
    KittPlugin *kp = g_new0(KittPlugin, 1);
    kp->plugin = plugin;
    kp->last_tick_us = g_get_monotonic_time();
    kp->shown_percent = -1; /* force the first repaint once show_percent is on, rather than matching a coincidental 0% */
    kitt_load_settings(kp);
    kp->dbus_conn = g_bus_get_sync(G_BUS_TYPE_SESSION, NULL, NULL);

    kp->area = gtk_drawing_area_new();
    gtk_widget_add_events(kp->area, GDK_BUTTON_PRESS_MASK | GDK_BUTTON_RELEASE_MASK);
    g_signal_connect(kp->area, "draw", G_CALLBACK(on_draw), kp);
    gtk_widget_set_has_tooltip(kp->area, TRUE);
    g_signal_connect(kp->area, "query-tooltip", G_CALLBACK(on_query_tooltip), kp);

    gtk_container_add(GTK_CONTAINER(plugin), kp->area);
    gtk_widget_show_all(GTK_WIDGET(plugin));
    xfce_panel_plugin_add_action_widget(plugin, kp->area);

    sample_cpu_load(kp); /* prime the counters, first sample has no delta */
    kp->sample_id = g_timeout_add(LOAD_SAMPLE_MS, on_sample, kp);

    kp->paused = display_is_off(kp) || screensaver_is_active(kp);
    if (kp->enabled && !kp->paused) {
        kitt_restart_tick_timer(kp);
    } else if (!kp->enabled) {
        kp->phase = CENTER_PHASE;
        kp->prev_eye_pos = eye_pos_for_phase(kp->phase, kp->sine_sweep);
    }
    kp->screen_check_id = g_timeout_add_seconds(SCREEN_CHECK_INTERVAL_S, on_screen_check_tick, kp);

    g_signal_connect(plugin, "free-data", G_CALLBACK(kitt_free), kp);
    g_signal_connect(plugin, "size-changed", G_CALLBACK(on_size_changed), kp);
    g_signal_connect(plugin, "configure-plugin", G_CALLBACK(on_configure_plugin), kp);

    xfce_panel_plugin_menu_show_configure(plugin);
    xfce_panel_plugin_set_expand(plugin, FALSE);
}

XFCE_PANEL_PLUGIN_REGISTER(kitt_construct);
