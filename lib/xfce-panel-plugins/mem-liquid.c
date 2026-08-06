/*
 * mem-liquid: xfce4-panel plugin. A square "tank" that fills like liquid
 * to show RAM usage -- virtual/swap memory is deliberately excluded from
 * the fill level (swap only buys time to close things gracefully before
 * a crash, it isn't "memory" in the sense a user cares about at a
 * glance), but swap is surfaced in the tooltip since it's still useful
 * context. If RAM itself is full, the tank reads 100% regardless of how
 * much swap is left. Root filesystem usage is surfaced in the tooltip
 * too (the panel is too crowded for a second tank), and the exclamation
 * mark also fires when disk usage crosses DISK_WARNING_LEVEL, not just
 * on RAM contention.
 *
 * Built as an "external" plugin (X-XFCE-Internal=FALSE in the .desktop
 * file), same convention as kitt-scanner and wattage-panel, so a crash
 * in here takes down only this plugin's process, not the panel.
 */

#include <gtk/gtk.h>
#include <gdk/gdkx.h>
#include <gio/gio.h>
#include <X11/Xlib.h>
#include <X11/extensions/dpms.h>
#include <libxfce4panel/libxfce4panel.h>
#include <libxfce4util/libxfce4util.h>
#include <ctype.h>
#include <dirent.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/statvfs.h>

#define MEM_SAMPLE_MS 2000        /* how often to read /proc/meminfo */
#define SCREEN_CHECK_INTERVAL_S 2 /* how often to poll for screen lock / display standby */
#define DBUS_CALL_TIMEOUT_MS 300  /* per-call timeout for screensaver-state D-Bus queries */

#define ASPECT_RATIO 1     /* square: width == panel size */
#define DEFAULT_FPS 6       /* liquid motion is slow -- low fps is plenty and saves CPU */
#define MIN_FPS 1
#define MAX_FPS 6

#define LEVEL_TIME_CONSTANT_S 1.4 /* how briskly the displayed level chases the real reading */

#define TANK_MARGIN_FRAC 0.10  /* tank inset from widget edge, as a fraction of the shorter side */
#define TANK_CORNER_FRAC 0.16  /* tank corner radius, as a fraction of tank size */

#define WAVE_AMPLITUDE_FRAC 0.028 /* wave amplitude as a fraction of tank height */
#define WAVE1_SPATIAL_FREQ 1.0    /* cycles across the tank width */
#define WAVE2_SPATIAL_FREQ 2.3
#define WAVE1_SPEED 0.55          /* rad/s -- deliberately slow and non-integer-ratio */
#define WAVE2_SPEED 0.87

#define NUM_BUBBLES 6

#define WARNING_LEVEL 0.80    /* RAM fraction at/above which we flag contention */
#define WARNING_PULSE_SPEED 4.2 /* rad/s -- a slow, deliberate blink, not a strobe */

#define DISK_PATH "/"
#define DISK_WARNING_LEVEL 0.80 /* disk fraction at/above which we flag low free space */

#define TOP_PROC_COUNT 3            /* how many processes to list in the tooltip */
#define TOP_PROC_MIN_KIB 1024       /* hide processes using less RSS than this */
#define TOOLTIP_REFRESH_INTERVAL_S 3 /* how often the tooltip's numbers update while hovered */

static const gdouble BUBBLE_X_FRAC[NUM_BUBBLES]   = { 0.16, 0.34, 0.52, 0.71, 0.86, 0.26 };
static const gdouble BUBBLE_SPEED[NUM_BUBBLES]     = { 0.055, 0.041, 0.067, 0.048, 0.061, 0.073 };
static const gdouble BUBBLE_PHASE[NUM_BUBBLES]     = { 0.05, 0.42, 0.71, 0.18, 0.88, 0.55 };
static const gdouble BUBBLE_RADIUS_FRAC[NUM_BUBBLES] = { 0.020, 0.026, 0.016, 0.022, 0.018, 0.024 };
static const gdouble BUBBLE_WOBBLE_SPEED[NUM_BUBBLES] = { 0.31, 0.24, 0.38, 0.27, 0.34, 0.22 };

/* Matches this theme's actual panel background (sampled directly off the
 * live panel window: #F6F5F4), rather than trying to auto-detect it at
 * runtime -- that auto-detection (as tried in kitt-scanner) is fragile in
 * practice, so a plain color picker in the properties dialog is a more
 * honest default: correct out of the box for the stock theme, and
 * user-adjustable for anyone running something else. */
static const gdouble DEFAULT_MARGIN_RGB[3] = { 0.9647, 0.9608, 0.9569 };
static const gdouble GLASS_BG[3] = { 0.08, 0.10, 0.13 };
static const gdouble GLASS_BORDER[3] = { 0.55, 0.60, 0.65 };

/* Fill color ramps from a calm blue (plenty of headroom) through amber
 * (getting tight) to red (nearly full) -- same "fuel gauge" language
 * most people already read at a glance. */
static const gdouble COLOR_LOW[3]  = { 0.20, 0.55, 0.90 };
static const gdouble COLOR_MID[3]  = { 0.95, 0.75, 0.15 };
static const gdouble COLOR_HIGH[3] = { 0.90, 0.15, 0.15 };
#define COLOR_MID_STOP 0.75

typedef struct {
    XfcePanelPlugin *plugin;
    GtkWidget *area;

    gdouble level;         /* displayed fill 0..1, smoothed towards target_level */
    gdouble target_level;  /* most recent RAM-used fraction, 0..1 */
    gdouble swap_frac;     /* most recent swap-used fraction, 0..1 (0 if no swap) */
    gulong mem_total_kib;
    gulong mem_used_kib;

    gdouble disk_frac;     /* most recent disk-used fraction of DISK_PATH, 0..1 */
    guint64 disk_total_bytes;
    guint64 disk_used_bytes;

    gdouble wave_phase1;
    gdouble wave_phase2;
    gdouble anim_time_s;   /* free-running clock for bubble motion */
    gint64 last_tick_us;

    gint fps;
    gboolean show_percent;
    gboolean enabled;      /* FALSE: freeze wave/bubble motion, level still updates */
    gboolean paused;       /* TRUE: screen locked or display in standby -- ticking suspended */
    gdouble margin_rgb[3]; /* widget background outside the tank, user-selectable */

    guint sample_id;
    guint tick_id;
    guint screen_check_id;
    guint tooltip_refresh_id; /* re-queries the tooltip periodically while hovered; 0 when not hovering */
    GDBusConnection *dbus_conn; /* session bus, for screensaver-state queries; may be NULL */
} MemPlugin;

static gboolean
read_meminfo(gulong *total_kib, gulong *avail_kib, gulong *swap_total_kib, gulong *swap_free_kib)
{
    FILE *f = fopen("/proc/meminfo", "r");
    if (!f)
        return FALSE;

    *total_kib = *avail_kib = *swap_total_kib = *swap_free_kib = 0;
    gboolean have_total = FALSE, have_avail = FALSE;

    char line[256];
    while (fgets(line, sizeof(line), f)) {
        gulong val;
        if (sscanf(line, "MemTotal: %lu kB", &val) == 1) {
            *total_kib = val;
            have_total = TRUE;
        } else if (sscanf(line, "MemAvailable: %lu kB", &val) == 1) {
            *avail_kib = val;
            have_avail = TRUE;
        } else if (sscanf(line, "SwapTotal: %lu kB", &val) == 1) {
            *swap_total_kib = val;
        } else if (sscanf(line, "SwapFree: %lu kB", &val) == 1) {
            *swap_free_kib = val;
        }
    }
    fclose(f);
    return have_total && have_avail && *total_kib > 0;
}

static gboolean
sample_memory(MemPlugin *mp)
{
    gulong total, avail, swap_total, swap_free;
    if (!read_meminfo(&total, &avail, &swap_total, &swap_free))
        return FALSE;

    gulong used = total > avail ? total - avail : 0;
    gdouble frac = (gdouble) used / (gdouble) total;
    mp->target_level = CLAMP(frac, 0.0, 1.0);
    mp->mem_total_kib = total;
    mp->mem_used_kib = used;
    mp->swap_frac = swap_total > 0 ? CLAMP(1.0 - (gdouble) swap_free / (gdouble) swap_total, 0.0, 1.0) : 0.0;
    return TRUE;
}

static void
sample_disk(MemPlugin *mp)
{
    struct statvfs st;
    if (statvfs(DISK_PATH, &st) != 0 || st.f_blocks == 0)
        return;

    guint64 total = (guint64) st.f_blocks * st.f_frsize;
    guint64 avail = (guint64) st.f_bavail * st.f_frsize;
    guint64 used = total > avail ? total - avail : 0;

    mp->disk_frac = CLAMP((gdouble) used / (gdouble) total, 0.0, 1.0);
    mp->disk_total_bytes = total;
    mp->disk_used_bytes = used;
}

static gboolean
on_sample(gpointer user_data)
{
    MemPlugin *mp = user_data;
    sample_memory(mp);
    sample_disk(mp);
    gtk_widget_queue_draw(mp->area); /* keep the level current even while animation is frozen */
    return G_SOURCE_CONTINUE;
}

/* Coarse verbal read of RAM usage, shown below the percentage in the
 * tooltip -- mirrors kitt-scanner's cpu_status_text. Only used below
 * WARNING_LEVEL; at/above that the contention warning takes over instead. */
static const gchar *
mem_status_text(gdouble frac)
{
    if (frac < 0.10)
        return "= Idle =";
    if (frac < 0.40)
        return "= Light load =";
    if (frac < 0.70)
        return "= Steady =";
    return "= Filling up =";
}

typedef struct {
    gchar comm[256];
    gulong rss_kib;
} TopProc;

/* Parses /proc/<pid>/status rather than statm: VmRSS is already in KiB and
 * spares us a page-size multiplication, and status's line-per-field layout
 * is far less brittle to parse than statm's positional columns. comm comes
 * from the Name: line, which -- unlike /proc/<pid>/stat's "(comm)" field --
 * is never wrapped in parens that could themselves appear in the name. */
static gboolean
read_proc_rss(const gchar *pid_str, TopProc *out)
{
    gchar path[64];
    g_snprintf(path, sizeof(path), "/proc/%s/status", pid_str);
    FILE *f = fopen(path, "r");
    if (!f)
        return FALSE;

    gboolean have_name = FALSE, have_rss = FALSE;
    gchar line[256];
    while (fgets(line, sizeof(line), f)) {
        gulong val;
        if (sscanf(line, "Name: %255s", out->comm) == 1) {
            have_name = TRUE;
        } else if (sscanf(line, "VmRSS: %lu kB", &val) == 1) {
            out->rss_kib = val;
            have_rss = TRUE;
            break; /* VmRSS comes after Name in every kernel's status layout */
        }
    }
    fclose(f);
    return have_name && have_rss;
}

static gint
top_proc_cmp(gconstpointer a, gconstpointer b)
{
    const TopProc *ta = a, *tb = b;
    if (ta->rss_kib < tb->rss_kib) return 1;
    if (ta->rss_kib > tb->rss_kib) return -1;
    return 0;
}

/* Unlike CPU share, RSS needs no before/after delta -- it's already a
 * point-in-time reading -- so this is a single /proc scan. Still only ever
 * called from on_query_tooltip: scanning every process's status file is
 * needless overhead for a number nobody is looking at, so it stays gated
 * behind the tooltip actually being shown. */
static gint
get_top_processes(TopProc *out, gint max_out)
{
    GArray *procs = g_array_new(FALSE, FALSE, sizeof(TopProc));

    DIR *d = opendir("/proc");
    if (d) {
        struct dirent *ent;
        while ((ent = readdir(d))) {
            if (!isdigit((unsigned char) ent->d_name[0]))
                continue;
            TopProc tp;
            if (!read_proc_rss(ent->d_name, &tp) || tp.rss_kib < TOP_PROC_MIN_KIB)
                continue;
            g_array_append_val(procs, tp);
        }
        closedir(d);
    }

    g_array_sort(procs, top_proc_cmp);
    gint n = MIN((gint) procs->len, max_out);
    for (gint i = 0; i < n; i++)
        out[i] = g_array_index(procs, TopProc, i);

    g_array_free(procs, TRUE);
    return n;
}

static gboolean
on_query_tooltip(GtkWidget *widget, gint x, gint y, gboolean keyboard_mode,
                  GtkTooltip *tooltip, gpointer user_data)
{
    (void) widget; (void) x; (void) y; (void) keyboard_mode;
    MemPlugin *mp = user_data;
    gchar buf[320];
    gdouble used_gib = mp->mem_used_kib / 1048576.0;
    gdouble total_gib = mp->mem_total_kib / 1048576.0;
    gdouble disk_used_gib = mp->disk_used_bytes / 1073741824.0;
    gdouble disk_total_gib = mp->disk_total_bytes / 1073741824.0;

    gint n = g_snprintf(buf, sizeof(buf), "RAM: %.0f%% used (%.1f / %.1f GiB)",
                         mp->target_level * 100.0, used_gib, total_gib);
    if (mp->swap_frac > 0.005)
        n += g_snprintf(buf + n, sizeof(buf) - n, "\nSwap: %.0f%% used", mp->swap_frac * 100.0);
    if (mp->disk_total_bytes > 0)
        n += g_snprintf(buf + n, sizeof(buf) - n, "\nDisk: %.0f%% used (%.1f / %.1f GiB)",
                         mp->disk_frac * 100.0, disk_used_gib, disk_total_gib);

    gboolean mem_warning = mp->target_level >= WARNING_LEVEL;
    gboolean disk_warning = mp->disk_frac >= DISK_WARNING_LEVEL;
    if (mem_warning && disk_warning)
        n += g_snprintf(buf + n, sizeof(buf) - n,
                   "\n\xE2\x9A\xA0 Memory contention and disk space are both tight");
    else if (mem_warning)
        n += g_snprintf(buf + n, sizeof(buf) - n,
                   "\n\xE2\x9A\xA0 Memory contention -- consider closing some programs");
    else if (disk_warning)
        n += g_snprintf(buf + n, sizeof(buf) - n,
                   "\n\xE2\x9A\xA0 Disk space low -- consider freeing some up");
    else
        n += g_snprintf(buf + n, sizeof(buf) - n, "\n%s", mem_status_text(mp->target_level));

    TopProc top[TOP_PROC_COUNT];
    gint top_n = get_top_processes(top, TOP_PROC_COUNT);
    if (top_n > 0) {
        n += g_snprintf(buf + n, sizeof(buf) - n, "\n\nTop RAM:");
        for (gint i = 0; i < top_n && n < (gint) sizeof(buf); i++)
            n += g_snprintf(buf + n, sizeof(buf) - n, "\n%s  %.0f MiB",
                             top[i].comm, top[i].rss_kib / 1024.0);
    }

    gtk_tooltip_set_text(tooltip, buf);
    return TRUE;
}

static gboolean
on_tooltip_refresh_tick(gpointer user_data)
{
    MemPlugin *mp = user_data;
    gtk_widget_trigger_tooltip_query(mp->area);
    return G_SOURCE_CONTINUE;
}

/* Mirrors kitt-scanner's hover-refresh timer: forces the tooltip to
 * re-query itself every couple of seconds, but only while the pointer is
 * actually over the widget, so the periodic /proc scan it triggers never
 * runs when nobody could be looking at the result. */
static gboolean
on_area_enter(GtkWidget *widget, GdkEventCrossing *event, gpointer user_data)
{
    MemPlugin *mp = user_data;
    if (mp->tooltip_refresh_id == 0)
        mp->tooltip_refresh_id = g_timeout_add_seconds(TOOLTIP_REFRESH_INTERVAL_S, on_tooltip_refresh_tick, mp);
    return FALSE;
}

static gboolean
on_area_leave(GtkWidget *widget, GdkEventCrossing *event, gpointer user_data)
{
    MemPlugin *mp = user_data;
    if (mp->tooltip_refresh_id != 0) {
        g_source_remove(mp->tooltip_refresh_id);
        mp->tooltip_refresh_id = 0;
    }
    return FALSE;
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

static void
level_color(gdouble frac, gdouble *out_rgb)
{
    if (frac <= COLOR_MID_STOP) {
        gdouble t = frac / COLOR_MID_STOP;
        for (int i = 0; i < 3; i++)
            out_rgb[i] = COLOR_LOW[i] + (COLOR_MID[i] - COLOR_LOW[i]) * t;
    } else {
        gdouble t = (frac - COLOR_MID_STOP) / (1.0 - COLOR_MID_STOP);
        for (int i = 0; i < 3; i++)
            out_rgb[i] = COLOR_MID[i] + (COLOR_HIGH[i] - COLOR_MID[i]) * t;
    }
}

typedef struct {
    gdouble x, y, w, h; /* tank rect */
    gdouble r;          /* tank corner radius */
} TankLayout;

static void
compute_tank_layout(gdouble w, gdouble h, TankLayout *lay)
{
    gdouble side = MIN(w, h) * (1.0 - 2.0 * TANK_MARGIN_FRAC);
    lay->x = (w - side) / 2.0;
    lay->y = (h - side) / 2.0;
    lay->w = side;
    lay->h = side;
    lay->r = side * TANK_CORNER_FRAC;
}

/* Height of the wavy surface above the tank floor, at horizontal position
 * x_norm (0..1 across the tank), for a liquid whose still level is
 * level_frac (0..1 fraction of tank height). */
static gdouble
wave_surface_height(gdouble x_norm, gdouble level_frac, gdouble ph1, gdouble ph2, gdouble tank_h)
{
    gdouble amp = WAVE_AMPLITUDE_FRAC * tank_h;
    gdouble wave = sin(2 * M_PI * WAVE1_SPATIAL_FREQ * x_norm + ph1)
        + 0.5 * sin(2 * M_PI * WAVE2_SPATIAL_FREQ * x_norm + ph2);
    return level_frac * tank_h + amp * (wave / 1.5);
}

static gboolean
on_tick(gpointer user_data)
{
    MemPlugin *mp = user_data;

    gint64 now = g_get_monotonic_time();
    gdouble dt = (now - mp->last_tick_us) / 1e6;
    mp->last_tick_us = now;
    if (dt <= 0.0 || dt > 1.0)
        dt = 1.0 / mp->fps;

    gdouble alpha = 1.0 - exp(-dt / LEVEL_TIME_CONSTANT_S);
    mp->level += (mp->target_level - mp->level) * alpha;

    mp->wave_phase1 = fmod(mp->wave_phase1 + dt * WAVE1_SPEED, 2 * M_PI);
    mp->wave_phase2 = fmod(mp->wave_phase2 + dt * WAVE2_SPEED, 2 * M_PI);
    mp->anim_time_s += dt;

    gtk_widget_queue_draw(mp->area);
    return G_SOURCE_CONTINUE;
}

static gboolean
on_draw(GtkWidget *widget, cairo_t *cr, gpointer user_data)
{
    MemPlugin *mp = user_data;
    GtkAllocation alloc;
    gtk_widget_get_allocation(widget, &alloc);
    gdouble w = alloc.width, h = alloc.height;

    cairo_set_source_rgb(cr, mp->margin_rgb[0], mp->margin_rgb[1], mp->margin_rgb[2]);
    cairo_paint(cr);

    TankLayout lay;
    compute_tank_layout(w, h, &lay);
    if (lay.w <= 4 || lay.h <= 4)
        return TRUE;

    gdouble color[3];
    level_color(mp->level, color);

    cairo_save(cr);
    rounded_rect(cr, lay.x, lay.y, lay.w, lay.h, lay.r);
    cairo_clip(cr);

    /* Glass base, visible above the liquid surface. */
    cairo_set_source_rgb(cr, GLASS_BG[0], GLASS_BG[1], GLASS_BG[2]);
    cairo_paint(cr);

    /* Liquid body, wavy top edge. */
    const int STEPS = 24;
    cairo_move_to(cr, lay.x, lay.y + lay.h);
    for (int i = 0; i <= STEPS; i++) {
        gdouble x_norm = (gdouble) i / STEPS;
        gdouble surf_h = wave_surface_height(x_norm, mp->level, mp->wave_phase1, mp->wave_phase2, lay.h);
        gdouble x = lay.x + x_norm * lay.w;
        gdouble y = lay.y + lay.h - surf_h;
        cairo_line_to(cr, x, y);
    }
    cairo_line_to(cr, lay.x + lay.w, lay.y + lay.h);
    cairo_close_path(cr);

    cairo_pattern_t *grad = cairo_pattern_create_linear(0, lay.y, 0, lay.y + lay.h);
    cairo_pattern_add_color_stop_rgb(grad, 0.0,
        MIN(1.0, color[0] + 0.20), MIN(1.0, color[1] + 0.20), MIN(1.0, color[2] + 0.20));
    cairo_pattern_add_color_stop_rgb(grad, 1.0,
        color[0] * 0.70, color[1] * 0.70, color[2] * 0.70);
    cairo_set_source(cr, grad);
    cairo_fill_preserve(cr);
    cairo_pattern_destroy(grad);

    /* Thin bright rim right at the surface, for a glossy highlight. */
    cairo_set_source_rgba(cr, 1.0, 1.0, 1.0, 0.35);
    cairo_set_line_width(cr, MAX(1.0, lay.h * 0.01));
    cairo_new_path(cr);
    for (int i = 0; i <= STEPS; i++) {
        gdouble x_norm = (gdouble) i / STEPS;
        gdouble surf_h = wave_surface_height(x_norm, mp->level, mp->wave_phase1, mp->wave_phase2, lay.h);
        gdouble x = lay.x + x_norm * lay.w;
        gdouble y = lay.y + lay.h - surf_h;
        if (i == 0)
            cairo_move_to(cr, x, y);
        else
            cairo_line_to(cr, x, y);
    }
    cairo_stroke(cr);

    /* Rising bubbles, only drawn while inside the liquid body. */
    for (int i = 0; i < NUM_BUBBLES; i++) {
        gdouble y_frac = fmod(mp->anim_time_s * BUBBLE_SPEED[i] + BUBBLE_PHASE[i], 1.0);
        gdouble bubble_height = y_frac * (mp->level * lay.h);
        if (bubble_height < 2.0)
            continue; /* respawning at the floor */

        gdouble wobble = 0.02 * lay.w * sin(mp->anim_time_s * BUBBLE_WOBBLE_SPEED[i] + BUBBLE_PHASE[i] * 7.0);
        gdouble bx = lay.x + BUBBLE_X_FRAC[i] * lay.w + wobble;
        gdouble by = lay.y + lay.h - bubble_height;
        gdouble br = BUBBLE_RADIUS_FRAC[i] * lay.w;

        gdouble fade = CLAMP(1.0 - y_frac, 0.15, 1.0);
        cairo_set_source_rgba(cr, 1.0, 1.0, 1.0, 0.25 * fade);
        cairo_arc(cr, bx, by, br, 0, 2 * M_PI);
        cairo_fill(cr);
    }

    cairo_restore(cr); /* drop the clip */

    /* Glass rim outline. */
    rounded_rect(cr, lay.x, lay.y, lay.w, lay.h, lay.r);
    cairo_set_source_rgba(cr, GLASS_BORDER[0], GLASS_BORDER[1], GLASS_BORDER[2], 0.8);
    cairo_set_line_width(cr, MAX(1.0, lay.h * 0.02));
    cairo_stroke(cr);

    gboolean warning = mp->level >= WARNING_LEVEL || mp->disk_frac >= DISK_WARNING_LEVEL;

    cairo_save(cr);
    rounded_rect(cr, lay.x, lay.y, lay.w, lay.h, lay.r);
    cairo_clip(cr);

    if (mp->show_percent) {
        gchar buf[8];
        g_snprintf(buf, sizeof(buf), "%.0f", mp->level * 100.0);

        /* Once the warning mark takes over the tank, the number becomes a
         * small badge at the bottom rather than competing for the same
         * space -- at panel-icon scale there isn't room for both to read
         * clearly at equal size. */
        cairo_text_extents_t ext;
        cairo_select_font_face(cr, "sans-serif", CAIRO_FONT_SLANT_NORMAL, CAIRO_FONT_WEIGHT_BOLD);
        cairo_set_font_size(cr, lay.h * (warning ? 0.16 : 0.30));
        cairo_text_extents(cr, buf, &ext);

        gdouble vert_frac = warning ? 0.87 : 0.5;
        gdouble tx = lay.x + lay.w / 2.0 - (ext.width / 2.0 + ext.x_bearing);
        gdouble ty = lay.y + lay.h * vert_frac - (ext.height / 2.0 + ext.y_bearing);

        cairo_set_source_rgba(cr, 0.0, 0.0, 0.0, 0.55);
        cairo_move_to(cr, tx + 1, ty + 1);
        cairo_show_text(cr, buf);

        cairo_set_source_rgba(cr, 1.0, 1.0, 1.0, 0.92);
        cairo_move_to(cr, tx, ty);
        cairo_show_text(cr, buf);
    }

    if (warning) {
        /* Cycles red <-> yellow rather than fading alpha -- a hue swing
         * reads clearly even at a few fps and at icon scale, where a
         * subtle opacity pulse just disappears. Sized to dominate the
         * tank: at the tiny scale a panel icon renders at, anything more
         * modest disappears too. */
        gdouble pulse = 0.5 + 0.5 * sin(mp->anim_time_s * WARNING_PULSE_SPEED);
        static const gdouble WARN_RED[3] = { 0.95, 0.10, 0.10 };
        static const gdouble WARN_YELLOW[3] = { 1.0, 0.85, 0.10 };
        gdouble mark_rgb[3];
        for (int i = 0; i < 3; i++)
            mark_rgb[i] = WARN_RED[i] + (WARN_YELLOW[i] - WARN_RED[i]) * pulse;

        const char *mark = "!";
        cairo_text_extents_t ext;
        cairo_select_font_face(cr, "sans-serif", CAIRO_FONT_SLANT_NORMAL, CAIRO_FONT_WEIGHT_BOLD);
        cairo_set_font_size(cr, lay.h * 0.85);
        cairo_text_extents(cr, mark, &ext);

        gdouble tx = lay.x + lay.w / 2.0 - (ext.width / 2.0 + ext.x_bearing);
        gdouble ty = lay.y + lay.h / 2.0 - (ext.height / 2.0 + ext.y_bearing);

        cairo_move_to(cr, tx, ty);
        cairo_text_path(cr, mark);
        cairo_set_line_width(cr, lay.h * 0.035);
        cairo_set_source_rgba(cr, 0.0, 0.0, 0.0, 0.8);
        cairo_stroke_preserve(cr);
        cairo_set_source_rgb(cr, mark_rgb[0], mark_rgb[1], mark_rgb[2]);
        cairo_fill(cr);
    }

    cairo_restore(cr);

    return TRUE;
}

static void
mem_load_settings(MemPlugin *mp)
{
    mp->fps = DEFAULT_FPS;
    mp->show_percent = TRUE;
    mp->enabled = TRUE;
    memcpy(mp->margin_rgb, DEFAULT_MARGIN_RGB, sizeof(mp->margin_rgb));

    gchar *file = xfce_panel_plugin_save_location(mp->plugin, FALSE);
    if (!file)
        return;

    XfceRc *rc = xfce_rc_simple_open(file, TRUE);
    g_free(file);
    if (!rc)
        return;

    xfce_rc_set_group(rc, "General");
    mp->fps = xfce_rc_read_int_entry(rc, "FPS", DEFAULT_FPS);
    mp->fps = CLAMP(mp->fps, MIN_FPS, MAX_FPS);
    mp->show_percent = xfce_rc_read_bool_entry(rc, "ShowPercent", TRUE);
    mp->enabled = xfce_rc_read_bool_entry(rc, "Enabled", TRUE);

    const gchar *color_str = xfce_rc_read_entry(rc, "MarginColor", NULL);
    if (color_str) {
        GdkRGBA rgba;
        if (gdk_rgba_parse(&rgba, color_str)) {
            mp->margin_rgb[0] = rgba.red;
            mp->margin_rgb[1] = rgba.green;
            mp->margin_rgb[2] = rgba.blue;
        }
    }
    xfce_rc_close(rc);
}

static void
mem_save_settings(MemPlugin *mp)
{
    gchar *file = xfce_panel_plugin_save_location(mp->plugin, TRUE);
    if (!file)
        return;

    XfceRc *rc = xfce_rc_simple_open(file, FALSE);
    g_free(file);
    if (!rc)
        return;

    GdkRGBA rgba = { mp->margin_rgb[0], mp->margin_rgb[1], mp->margin_rgb[2], 1.0 };
    gchar *color_str = gdk_rgba_to_string(&rgba);

    xfce_rc_set_group(rc, "General");
    xfce_rc_write_int_entry(rc, "FPS", mp->fps);
    xfce_rc_write_bool_entry(rc, "ShowPercent", mp->show_percent);
    xfce_rc_write_bool_entry(rc, "Enabled", mp->enabled);
    xfce_rc_write_entry(rc, "MarginColor", color_str);
    g_free(color_str);
    xfce_rc_close(rc);
}

static gboolean
display_is_off(MemPlugin *mp)
{
    Display *dpy = GDK_DISPLAY_XDISPLAY(gtk_widget_get_display(GTK_WIDGET(mp->plugin)));

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
screensaver_is_active(MemPlugin *mp)
{
    return query_screensaver_active(mp->dbus_conn, "org.freedesktop.ScreenSaver",
                                     "/org/freedesktop/ScreenSaver", "org.freedesktop.ScreenSaver")
        || query_screensaver_active(mp->dbus_conn, "org.xfce.ScreenSaver",
                                     "/org/xfce/ScreenSaver", "org.xfce.ScreenSaver");
}

static void
mem_restart_tick_timer(MemPlugin *mp)
{
    if (mp->tick_id != 0)
        g_source_remove(mp->tick_id);
    mp->tick_id = g_timeout_add(1000 / mp->fps, on_tick, mp);
}

static void
mem_maybe_start_tick_timer(MemPlugin *mp)
{
    if (!mp->enabled || mp->paused || mp->tick_id != 0)
        return;
    mp->last_tick_us = g_get_monotonic_time();
    mem_restart_tick_timer(mp);
}

static void
mem_stop_tick_timer(MemPlugin *mp)
{
    if (mp->tick_id != 0) {
        g_source_remove(mp->tick_id);
        mp->tick_id = 0;
    }
}

static gboolean
on_screen_check_tick(gpointer user_data)
{
    MemPlugin *mp = user_data;

    gboolean should_pause = display_is_off(mp) || screensaver_is_active(mp);
    if (should_pause != mp->paused) {
        mp->paused = should_pause;
        if (mp->paused)
            mem_stop_tick_timer(mp);
        else
            mem_maybe_start_tick_timer(mp);
    }
    return G_SOURCE_CONTINUE;
}

static void
on_fps_changed(GtkSpinButton *spin, MemPlugin *mp)
{
    mp->fps = gtk_spin_button_get_value_as_int(spin);
    if (mp->tick_id != 0)
        mem_restart_tick_timer(mp);
    mem_save_settings(mp);
}

static void
on_enabled_toggled(GtkToggleButton *toggle, MemPlugin *mp)
{
    mp->enabled = gtk_toggle_button_get_active(toggle);

    if (!mp->enabled)
        mem_stop_tick_timer(mp);
    else
        mem_maybe_start_tick_timer(mp);

    gtk_widget_queue_draw(mp->area);
    mem_save_settings(mp);
}

static void
on_show_percent_toggled(GtkToggleButton *toggle, MemPlugin *mp)
{
    mp->show_percent = gtk_toggle_button_get_active(toggle);
    gtk_widget_queue_draw(mp->area);
    mem_save_settings(mp);
}

static void
on_margin_color_set(GtkColorButton *button, MemPlugin *mp)
{
    GdkRGBA rgba;
    gtk_color_chooser_get_rgba(GTK_COLOR_CHOOSER(button), &rgba);
    mp->margin_rgb[0] = rgba.red;
    mp->margin_rgb[1] = rgba.green;
    mp->margin_rgb[2] = rgba.blue;
    gtk_widget_queue_draw(mp->area);
    mem_save_settings(mp);
}

static void
on_configure_plugin(XfcePanelPlugin *plugin, MemPlugin *mp)
{
    GtkWidget *dialog = gtk_dialog_new_with_buttons(
        "Memory Liquid", GTK_WINDOW(gtk_widget_get_toplevel(GTK_WIDGET(plugin))),
        GTK_DIALOG_DESTROY_WITH_PARENT, "_Close", GTK_RESPONSE_CLOSE, NULL);
    gtk_window_set_icon_name(GTK_WINDOW(dialog), "utilities-system-monitor");

    GtkWidget *grid = gtk_grid_new();
    gtk_grid_set_row_spacing(GTK_GRID(grid), 6);
    gtk_grid_set_column_spacing(GTK_GRID(grid), 12);
    gtk_container_set_border_width(GTK_CONTAINER(grid), 12);

    GtkWidget *enabled_check = gtk_check_button_new_with_label("Enabled (off freezes the liquid motion)");
    gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(enabled_check), mp->enabled);
    g_signal_connect(enabled_check, "toggled", G_CALLBACK(on_enabled_toggled), mp);
    gtk_grid_attach(GTK_GRID(grid), enabled_check, 0, 0, 2, 1);

    GtkWidget *fps_label = gtk_label_new("Frame rate, fps:");
    gtk_widget_set_halign(fps_label, GTK_ALIGN_START);
    GtkWidget *fps_spin = gtk_spin_button_new_with_range(MIN_FPS, MAX_FPS, 1);
    gtk_spin_button_set_value(GTK_SPIN_BUTTON(fps_spin), mp->fps);
    g_signal_connect(fps_spin, "value-changed", G_CALLBACK(on_fps_changed), mp);
    gtk_grid_attach(GTK_GRID(grid), fps_label, 0, 1, 1, 1);
    gtk_grid_attach(GTK_GRID(grid), fps_spin, 1, 1, 1, 1);

    GtkWidget *percent_check = gtk_check_button_new_with_label("Show percentage inside the tank");
    gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(percent_check), mp->show_percent);
    g_signal_connect(percent_check, "toggled", G_CALLBACK(on_show_percent_toggled), mp);
    gtk_grid_attach(GTK_GRID(grid), percent_check, 0, 2, 2, 1);

    GtkWidget *margin_label = gtk_label_new("Margin color:");
    gtk_widget_set_halign(margin_label, GTK_ALIGN_START);
    GdkRGBA margin_rgba = { mp->margin_rgb[0], mp->margin_rgb[1], mp->margin_rgb[2], 1.0 };
    GtkWidget *margin_button = gtk_color_button_new_with_rgba(&margin_rgba);
    gtk_color_chooser_set_use_alpha(GTK_COLOR_CHOOSER(margin_button), FALSE);
    g_signal_connect(margin_button, "color-set", G_CALLBACK(on_margin_color_set), mp);
    gtk_grid_attach(GTK_GRID(grid), margin_label, 0, 3, 1, 1);
    gtk_grid_attach(GTK_GRID(grid), margin_button, 1, 3, 1, 1);

    gtk_container_add(GTK_CONTAINER(gtk_dialog_get_content_area(GTK_DIALOG(dialog))), grid);
    gtk_widget_show_all(dialog);

    g_signal_connect(dialog, "response", G_CALLBACK(gtk_widget_destroy), NULL);
}

static gboolean
on_size_changed(XfcePanelPlugin *plugin, guint size, MemPlugin *mp)
{
    gtk_widget_set_size_request(mp->area, size * ASPECT_RATIO, size);
    gtk_widget_queue_draw(mp->area);
    return TRUE;
}

static void
mem_free(XfcePanelPlugin *plugin, MemPlugin *mp)
{
    if (mp->sample_id != 0)
        g_source_remove(mp->sample_id);
    if (mp->tick_id != 0)
        g_source_remove(mp->tick_id);
    if (mp->screen_check_id != 0)
        g_source_remove(mp->screen_check_id);
    if (mp->tooltip_refresh_id != 0)
        g_source_remove(mp->tooltip_refresh_id);
    if (mp->dbus_conn)
        g_object_unref(mp->dbus_conn);
    g_free(mp);
}

static void
mem_construct(XfcePanelPlugin *plugin)
{
    MemPlugin *mp = g_new0(MemPlugin, 1);
    mp->plugin = plugin;
    mp->last_tick_us = g_get_monotonic_time();
    mem_load_settings(mp);
    mp->dbus_conn = g_bus_get_sync(G_BUS_TYPE_SESSION, NULL, NULL);

    mp->area = gtk_drawing_area_new();
    gtk_widget_add_events(mp->area, GDK_BUTTON_PRESS_MASK | GDK_BUTTON_RELEASE_MASK
                           | GDK_ENTER_NOTIFY_MASK | GDK_LEAVE_NOTIFY_MASK);
    g_signal_connect(mp->area, "draw", G_CALLBACK(on_draw), mp);
    gtk_widget_set_has_tooltip(mp->area, TRUE);
    g_signal_connect(mp->area, "query-tooltip", G_CALLBACK(on_query_tooltip), mp);
    g_signal_connect(mp->area, "enter-notify-event", G_CALLBACK(on_area_enter), mp);
    g_signal_connect(mp->area, "leave-notify-event", G_CALLBACK(on_area_leave), mp);

    gtk_container_add(GTK_CONTAINER(plugin), mp->area);
    gtk_widget_show_all(GTK_WIDGET(plugin));
    xfce_panel_plugin_add_action_widget(plugin, mp->area);

    sample_memory(mp);
    sample_disk(mp);
    mp->level = mp->target_level; /* start full rather than animating up from empty */
    mp->sample_id = g_timeout_add(MEM_SAMPLE_MS, on_sample, mp);

    mp->paused = display_is_off(mp) || screensaver_is_active(mp);
    if (mp->enabled && !mp->paused)
        mem_restart_tick_timer(mp);
    mp->screen_check_id = g_timeout_add_seconds(SCREEN_CHECK_INTERVAL_S, on_screen_check_tick, mp);

    g_signal_connect(plugin, "free-data", G_CALLBACK(mem_free), mp);
    g_signal_connect(plugin, "size-changed", G_CALLBACK(on_size_changed), mp);
    g_signal_connect(plugin, "configure-plugin", G_CALLBACK(on_configure_plugin), mp);

    xfce_panel_plugin_menu_show_configure(plugin);
    xfce_panel_plugin_set_expand(plugin, FALSE);
}

XFCE_PANEL_PLUGIN_REGISTER(mem_construct);
