/*
 * wattage-panel: xfce4-panel plugin showing battery power draw and
 * estimated remaining time.
 *
 * The panel label shows the machine's own instant power_now reading and
 * the remaining time derived from it -- "what the machine reports".
 *
 * BAT0/energy_now turned out to update far more coarsely than expected on
 * this hardware (real ticks roughly every 4-5 minutes, in ~0.29Wh steps --
 * see power-logs, files named wattage-granularity) and occasionally bounces up by
 * a full step and back down within a few seconds (an EC readback glitch,
 * not real energy). A fixed-size trailing-average window is a bad fit for
 * an input that coarse: depending on exactly where in the window the one
 * available tick falls, the same tick can compute wildly different watt
 * values. So instead of that, every validated (monotonically decreasing)
 * energy_now tick since we last started running on battery is kept in
 * `ticks`, and the tooltip shows several escalating windows (10 min, 30
 * min, 1h, 2h, all) computed from however many real ticks actually fall in
 * each -- informational for now, while we decide what (if anything) should
 * drive the displayed reading instead of power_now.
 *
 * Built as an "external" plugin (X-XFCE-Internal=FALSE), same as
 * kitt-scanner, so a crash here takes down only this plugin's process.
 *
 * User-visible strings are translated via gettext, domain "wattage-panel"
 * (see the German catalog at po/wattage-panel.de.po) -- see kitt-scanner.c's
 * own i18n comment for why _() calls dgettext() directly instead of
 * gettext() + textdomain().
 */

#include <gtk/gtk.h>
#include <gdk/gdkx.h>
#include <X11/Xlib.h>
#include <X11/extensions/dpms.h>
#include <libintl.h>
#include <libxfce4panel/libxfce4panel.h>
#include <libxfce4util/libxfce4util.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

/* libxfce4util's xfce-i18n.h (pulled in above) already #defines _() as
 * bare gettext() -- redefine it to our per-plugin dgettext() instead. */
#undef _
#define _(String) dgettext("wattage-panel", String)

#define BAT_PATH "/sys/class/power_supply/BAT0"
#define SAMPLE_INTERVAL_MS 3000

/* Periodic history log for building an hourly consumption graph later.
 * Kept separate from SAMPLE_INTERVAL_MS (which drives the live label) so
 * the on-disk history doesn't balloon -- one row every 5 minutes is
 * plenty for an hour-granularity graph. */
#define LOG_INTERVAL_S (5 * 60)
#define LOG_SUBDIR "wattage-panel"
#define LOG_FILE "history.csv"

/* Persisted copy of the current session's `ticks` (time_s,energy_uwh per
 * line, oldest first), so a panel/plugin restart mid-session doesn't throw
 * away everything and start the averages over. Rewritten from scratch on
 * every genuine new discharge session, appended to on every real tick. */
#define TICKS_FILE "ticks.csv"

/* A persisted tick file is only trusted to resume the in-memory `ticks`
 * array if its last entry is within this long of "now" -- long enough to
 * survive a panel crash/restart (this hardware's real ticks land every
 * ~4-5 min, so even a couple of missed polls should stay well under this),
 * short enough to not accidentally splice in a session from hours ago. */
#define TICKS_RESUME_MAX_GAP_S (30 * 60)

/* Ring buffer of the last N raw energy_now readings, shown in the tooltip
 * when the debug checkbox is on -- independent of battery status, unlike
 * `ticks` below. */
#define DEBUG_RING_SIZE 10

typedef enum {
    BATT_DISCHARGING,
    BATT_CHARGING,
    BATT_OTHER
} BattStatus;

typedef struct {
    gint64 time_s;
    gdouble energy_uwh;
} EnergyPoint;

typedef struct {
    const gchar *label;
    gint64 seconds;
} AvgWindow;

static const AvgWindow AVG_WINDOWS[] = {
    { "10 min", 10 * 60 },
    { "30 min", 30 * 60 },
    { "1 h", 60 * 60 },
    { "2 h", 2 * 60 * 60 },
};
#define AVG_WINDOWS_COUNT (G_N_ELEMENTS(AVG_WINDOWS))

typedef struct {
    XfcePanelPlugin *plugin;
    GtkWidget *label;

    GArray *ticks; /* of EnergyPoint, oldest first: validated (monotonically
                       decreasing) energy_now readings since we last started
                       running on battery. ticks[0] is the energy reading at
                       the moment we started discharging (a seed, not a real
                       tick), so windows longer than the current run just
                       fall back to it. */
    gint64 battery_start_s;
    gdouble last_valid_energy;
    gboolean have_last_valid;

    EnergyPoint debug_ring[DEBUG_RING_SIZE];
    guint debug_ring_count;
    guint debug_ring_next;
    gboolean debug_raw;

    gboolean have_battery;
    guint sample_id;
    guint log_id;

    gboolean have_last;
    BattStatus last_status;
    gdouble last_watts;
    gdouble last_capacity;
    gdouble last_energy_uwh;
} WattPlugin;

static BattStatus
parse_status(const gchar *s)
{
    if (g_strcmp0(s, "Discharging") == 0)
        return BATT_DISCHARGING;
    if (g_strcmp0(s, "Charging") == 0)
        return BATT_CHARGING;
    return BATT_OTHER;
}

static gboolean
read_file_double(const gchar *path, gdouble *out)
{
    FILE *f = fopen(path, "r");
    if (!f)
        return FALSE;
    gboolean ok = fscanf(f, "%lf", out) == 1;
    fclose(f);
    return ok;
}

static gboolean
read_file_string(const gchar *path, gchar *buf, gsize buflen)
{
    FILE *f = fopen(path, "r");
    if (!f)
        return FALSE;
    gboolean ok = fgets(buf, (int) buflen, f) != NULL;
    fclose(f);
    if (ok)
        g_strchomp(buf);
    return ok;
}

/* Path to a file in our state dir (created if needed). Caller g_free()s. */
static gchar *
watt_state_path(const gchar *filename)
{
    gchar *dir = g_build_filename(g_get_user_state_dir(), LOG_SUBDIR, NULL);
    g_mkdir_with_parents(dir, 0755);
    gchar *path = g_build_filename(dir, filename, NULL);
    g_free(dir);
    return path;
}

/* Rewrites ticks.csv from scratch with just the seed point. Called
 * whenever a genuinely new discharge session starts, so a stale file left
 * over from a previous session never lingers to confuse a later resume. */
static void
watt_ticks_file_reset(gint64 time_s, gdouble energy_uwh)
{
    gchar *path = watt_state_path(TICKS_FILE);
    FILE *f = fopen(path, "w");
    g_free(path);
    if (!f)
        return;
    fprintf(f, "%" G_GINT64_FORMAT ",%.0f\n", time_s, energy_uwh);
    fclose(f);
}

static void
watt_ticks_file_append(gint64 time_s, gdouble energy_uwh)
{
    gchar *path = watt_state_path(TICKS_FILE);
    FILE *f = fopen(path, "a");
    g_free(path);
    if (!f)
        return;
    fprintf(f, "%" G_GINT64_FORMAT ",%.0f\n", time_s, energy_uwh);
    fclose(f);
}

/* Called the moment we start a fresh run on battery (plugin startup while
 * discharging, or a Charging/AC -> Discharging transition). Throws away
 * ticks from any previous run -- they belong to a different discharge
 * session and averaging across the gap would be meaningless -- and seeds
 * the array with the current reading as the run's starting point. */
static void
watt_reset_battery_ticks(WattPlugin *wp, gint64 now_s, gdouble energy_uwh)
{
    g_array_set_size(wp->ticks, 0);
    EnergyPoint seed = { .time_s = now_s, .energy_uwh = energy_uwh };
    g_array_append_val(wp->ticks, seed);
    wp->battery_start_s = now_s;
    wp->last_valid_energy = energy_uwh;
    wp->have_last_valid = TRUE;
    watt_ticks_file_reset(now_s, energy_uwh);
}

/* True if history.csv shows an AC/charging row timestamped after `since_s`
 * -- i.e. the machine was plugged in at some point after the last
 * persisted tick, so a persisted tick file spanning that gap belongs to a
 * session that has already ended, not the one still running now. */
static gboolean
watt_history_shows_ac_since(gint64 since_s)
{
    gchar *path = watt_state_path(LOG_FILE);
    FILE *f = fopen(path, "r");
    g_free(path);
    if (!f)
        return FALSE;

    gboolean found = FALSE;
    gchar line[256];
    fgets(line, sizeof(line), f); /* header */
    while (fgets(line, sizeof(line), f)) {
        gint64 ts;
        gchar status[16];
        if (sscanf(line, "%" G_GINT64_FORMAT ",%15[^,]", &ts, status) == 2 &&
            ts > since_s && g_strcmp0(status, "battery") != 0) {
            found = TRUE;
            break;
        }
    }
    fclose(f);
    return found;
}

/* Tries to resume a previous session's tick history after a plugin restart
 * (panel crash/restart, a plugin reinstall, etc.) instead of throwing it
 * away. Only trusts the persisted file as a genuine continuation of the
 * still-running discharge session -- not a stale leftover from an earlier
 * one -- when: the last persisted tick is recent, the battery hasn't
 * gained charge since then, and history.csv shows no AC/charging activity
 * in between. Leaves wp->ticks untouched and returns FALSE otherwise, so
 * the caller falls back to a plain reset. */
static gboolean
watt_try_resume_ticks(WattPlugin *wp, gint64 now_s, gdouble energy_uwh)
{
    gchar *path = watt_state_path(TICKS_FILE);
    FILE *f = fopen(path, "r");
    g_free(path);
    if (!f)
        return FALSE;

    GArray *loaded = g_array_new(FALSE, FALSE, sizeof(EnergyPoint));
    gchar line[64];
    while (fgets(line, sizeof(line), f)) {
        EnergyPoint p;
        if (sscanf(line, "%" G_GINT64_FORMAT ",%lf", &p.time_s, &p.energy_uwh) == 2)
            g_array_append_val(loaded, p);
    }
    fclose(f);

    if (loaded->len < 1) {
        g_array_free(loaded, TRUE);
        return FALSE;
    }

    const EnergyPoint *last = &g_array_index(loaded, EnergyPoint, loaded->len - 1);
    gboolean ok = (now_s - last->time_s) <= TICKS_RESUME_MAX_GAP_S &&
                  energy_uwh <= last->energy_uwh &&
                  !watt_history_shows_ac_since(last->time_s);

    if (!ok) {
        g_array_free(loaded, TRUE);
        return FALSE;
    }

    g_array_set_size(wp->ticks, 0);
    for (guint i = 0; i < loaded->len; i++)
        g_array_append_val(wp->ticks, g_array_index(loaded, EnergyPoint, i));
    gdouble last_energy = last->energy_uwh; /* last points into loaded, about to be freed */
    g_array_free(loaded, TRUE);

    wp->battery_start_s = g_array_index(wp->ticks, EnergyPoint, 0).time_s;
    wp->last_valid_energy = last_energy;
    wp->have_last_valid = TRUE;

    if (energy_uwh < last_energy) {
        /* The battery kept draining while we weren't running -- capture
         * that as one more real tick, same as a normal live update. */
        EnergyPoint p = { .time_s = now_s, .energy_uwh = energy_uwh };
        g_array_append_val(wp->ticks, p);
        wp->last_valid_energy = energy_uwh;
        watt_ticks_file_append(now_s, energy_uwh);
    }

    return TRUE;
}

/* Average power (W) over the trailing `window_s` seconds of validated
 * battery ticks, computed strictly from the first and last real tick that
 * fall inside the window -- never from `now_s`. ticks[0] is just the
 * energy_now value seen at the moment we started watching, not an observed
 * EC update, so it's excluded here: pairing it with one real tick would
 * fabricate a measured interval out of an arbitrary poll boundary. That
 * means a window with fewer than 2 *real* ticks in it (including a long
 * gap since the last real tick) reports "no data" rather than
 * freezing/drifting toward a stale number. */
static gboolean
watt_window_average(WattPlugin *wp, gint64 now_s, gint64 window_s,
                     gdouble *out_watts, guint *out_ticks)
{
    if (wp->ticks->len < 3) /* seed + at least 2 real ticks */
        return FALSE;

    gint64 cutoff = now_s - window_s;
    guint end_idx = wp->ticks->len - 1;
    if (g_array_index(wp->ticks, EnergyPoint, end_idx).time_s < cutoff)
        return FALSE; /* no tick at all inside the window */

    guint start_idx = end_idx;
    while (start_idx > 1 &&
           g_array_index(wp->ticks, EnergyPoint, start_idx - 1).time_s >= cutoff)
        start_idx--;

    if (start_idx >= end_idx)
        return FALSE; /* only 1 real tick inside the window */

    const EnergyPoint *start = &g_array_index(wp->ticks, EnergyPoint, start_idx);
    const EnergyPoint *end = &g_array_index(wp->ticks, EnergyPoint, end_idx);
    gint64 span_s = end->time_s - start->time_s;
    gdouble diff_uwh = start->energy_uwh - end->energy_uwh;
    if (span_s <= 0 || diff_uwh <= 0.0)
        return FALSE;

    *out_watts = (diff_uwh / 1000000.0) / (span_s / 3600.0);
    *out_ticks = end_idx - start_idx + 1;
    return TRUE;
}

static void
watt_update_label(WattPlugin *wp)
{
    gchar status_buf[32] = { 0 };
    gdouble power_uw = 0, energy_uwh = 0, capacity = 0;

    if (!wp->have_battery) {
        gtk_label_set_text(GTK_LABEL(wp->label), _("no battery"));
        return;
    }

    read_file_string(BAT_PATH "/status", status_buf, sizeof(status_buf));
    read_file_double(BAT_PATH "/power_now", &power_uw);
    read_file_double(BAT_PATH "/energy_now", &energy_uwh);
    read_file_double(BAT_PATH "/capacity", &capacity);

    BattStatus status = parse_status(status_buf);
    gint64 now_s = g_get_real_time() / G_USEC_PER_SEC;

    wp->debug_ring[wp->debug_ring_next] = (EnergyPoint) { .time_s = now_s, .energy_uwh = energy_uwh };
    wp->debug_ring_next = (wp->debug_ring_next + 1) % DEBUG_RING_SIZE;
    if (wp->debug_ring_count < DEBUG_RING_SIZE)
        wp->debug_ring_count++;

    if (status == BATT_DISCHARGING) {
        if (!wp->have_last_valid || wp->last_status != BATT_DISCHARGING) {
            /* Only try to resume a persisted session on a true process
             * startup (wp->have_last still FALSE) -- a live AC/charging ->
             * Discharging transition seen during this process's own
             * lifetime is unambiguously a fresh session, so go straight to
             * a plain reset for that case. */
            gboolean resumed = !wp->have_last && watt_try_resume_ticks(wp, now_s, energy_uwh);
            if (!resumed)
                watt_reset_battery_ticks(wp, now_s, energy_uwh);
        } else if (energy_uwh < wp->last_valid_energy) {
            EnergyPoint tick = { .time_s = now_s, .energy_uwh = energy_uwh };
            g_array_append_val(wp->ticks, tick);
            wp->last_valid_energy = energy_uwh;
            watt_ticks_file_append(now_s, energy_uwh);
        }
        /* energy_uwh == last_valid_energy: no new tick yet, nothing to do.
         * energy_uwh > last_valid_energy: EC readback glitch (observed
         * bouncing up a full ~0.29Wh step and back down within 2-4s on
         * this hardware) -- drop it instead of recording bogus "energy
         * gained back" as a tick. */
    } else {
        wp->have_last_valid = FALSE; /* reseed next time we go on battery */
    }

    /* Prefer the machine's own instant power_now reading. Some hardware
     * (seen on the GRTY/E140 board) never populates power_now at all -- it
     * reads a flat 0 -- so fall back to the 10-minute tick-based average in
     * that case. Confirmed on that hardware (via a CPU-burn test) that
     * energy_now itself updates on a real, load-responsive ~20s cadence
     * there, fine-grained enough for a 10-minute window to track actual
     * draw rather than just being a slow-moving average. */
    gdouble watts = power_uw / 1000000.0;
    gboolean watts_is_average = FALSE;
    if (watts <= 0.0 && status == BATT_DISCHARGING) {
        gdouble avg_w;
        guint avg_ticks;
        if (watt_window_average(wp, now_s, AVG_WINDOWS[0].seconds, &avg_w, &avg_ticks)) {
            watts = avg_w;
            watts_is_average = TRUE;
        }
    }

    gchar text[64];
    switch (status) {
        case BATT_DISCHARGING:
            if (watts > 0.0) {
                gdouble hours = energy_uwh / (watts * 1000000.0);
                gint h = (gint) hours;
                gint m = (gint) ((hours - h) * 60);
                g_snprintf(text, sizeof(text), "%.1fW -%d:%02d", watts, h, m);
            } else {
                g_snprintf(text, sizeof(text), "%.1fW", watts);
            }
            break;
        case BATT_CHARGING:
            /* Short on purpose: this is the whole panel label, not a
             * sentence -- "lädt" (not a translated "chg") stays terse. */
            g_snprintf(text, sizeof(text), _("%.1fW chg"), watts);
            break;
        default:
            g_snprintf(text, sizeof(text), _("AC"));
            break;
    }
    gtk_label_set_text(GTK_LABEL(wp->label), text);

    GString *tooltip = g_string_new(NULL);
    g_string_append_printf(tooltip,
                            watts_is_average
                                ? _("Battery: %.0f%% (%s)\nPower: %.1f W (10 min average)")
                                : _("Battery: %.0f%% (%s)\nPower: %.1f W (instant, as reported)"),
                            capacity, status_buf, watts);

    if (status == BATT_DISCHARGING) {
        gint64 elapsed_s = now_s - wp->battery_start_s;
        gchar elapsed_buf[32];
        g_snprintf(elapsed_buf, sizeof(elapsed_buf), "%d:%02d",
                   (int) (elapsed_s / 60), (int) (elapsed_s % 60));
        g_string_append_printf(tooltip, _("\n\nAverages since on battery (%s):"), elapsed_buf);

        for (guint i = 0; i < AVG_WINDOWS_COUNT; i++) {
            gdouble w;
            guint ticks;
            /* No elapsed-time gate needed here: watt_window_average already
             * requires 2 real ticks inside the window (the seed alone can't
             * satisfy that), so a window shows up as soon as it has genuine
             * data, even if we haven't been on battery for its full nominal
             * length yet. */
            if (watt_window_average(wp, now_s, AVG_WINDOWS[i].seconds, &w, &ticks))
                g_string_append_printf(tooltip, "\n  %-6s: %.1f W  (%u %s)",
                                        AVG_WINDOWS[i].label, w, ticks, ticks == 1 ? _("tick") : _("ticks"));
            else
                g_string_append_printf(tooltip, "\n  %-6s: %s", AVG_WINDOWS[i].label, _("not enough data yet"));
        }

        gdouble session_w;
        guint session_ticks;
        if (watt_window_average(wp, now_s, elapsed_s + 1, &session_w, &session_ticks))
            g_string_append_printf(tooltip, "\n  %-6s: %.1f W  (%u %s)",
                                    _("all"), session_w, session_ticks, session_ticks == 1 ? _("tick") : _("ticks"));
        else
            g_string_append_printf(tooltip, "\n  %-6s: %s", _("all"), _("not enough data yet"));
    }

    if (wp->debug_raw) {
        g_string_append(tooltip, _("\n\nLast raw energy_now readings:"));
        guint n = wp->debug_ring_count;
        guint ring_start = (wp->debug_ring_next + DEBUG_RING_SIZE - n) % DEBUG_RING_SIZE;
        for (guint k = 0; k < n; k++) {
            const EnergyPoint *s = &wp->debug_ring[(ring_start + k) % DEBUG_RING_SIZE];
            time_t t = (time_t) s->time_s;
            struct tm tm_buf;
            gchar time_str[16] = "??:??:??";
            if (localtime_r(&t, &tm_buf))
                strftime(time_str, sizeof(time_str), "%H:%M:%S", &tm_buf);
            g_string_append_printf(tooltip, "\n%s  %.0f uWh", time_str, s->energy_uwh);
        }
    }

    gtk_widget_set_tooltip_text(wp->label, tooltip->str);
    g_string_free(tooltip, TRUE);

    wp->last_status = status;
    wp->last_watts = watts;
    wp->last_capacity = capacity;
    wp->last_energy_uwh = energy_uwh;
    wp->have_last = TRUE;
}

/* Same DPMS query kitt-scanner uses to detect a blanked screen. */
static gboolean
display_is_off(WattPlugin *wp)
{
    Display *dpy = GDK_DISPLAY_XDISPLAY(gtk_widget_get_display(GTK_WIDGET(wp->plugin)));

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
on_sample(gpointer user_data)
{
    watt_update_label((WattPlugin *) user_data);
    return G_SOURCE_CONTINUE;
}

static const gchar *
status_log_name(BattStatus status)
{
    switch (status) {
        case BATT_DISCHARGING:
            return "battery";
        case BATT_CHARGING:
            return "charging";
        default:
            return "ac";
    }
}

/* Appends one row to the on-disk history (timestamp, AC/battery/charging,
 * watts, battery %, screen on/off, raw energy_now) so an hour-granularity
 * graph can be built later without keeping the plugin running the whole
 * time, and so past sessions can be re-analyzed (e.g. actual %/hour
 * decline, or tick spacing) without having had a dedicated logger running
 * at the time. */
static void
watt_append_log(WattPlugin *wp)
{
    if (!wp->have_last)
        return;

    gchar *dir = g_build_filename(g_get_user_state_dir(), LOG_SUBDIR, NULL);
    if (g_mkdir_with_parents(dir, 0755) != 0) {
        g_free(dir);
        return;
    }
    gchar *path = g_build_filename(dir, LOG_FILE, NULL);
    g_free(dir);

    gboolean new_file = !g_file_test(path, G_FILE_TEST_EXISTS);
    FILE *f = fopen(path, "a");
    g_free(path);
    if (!f)
        return;

    if (new_file)
        fputs("timestamp,status,watts,battery_pct,screen,energy_now_uwh\n", f);

    gint64 now_s = g_get_real_time() / G_USEC_PER_SEC;
    const gchar *screen = display_is_off(wp) ? "off" : "on";
    /* energy_now_uwh is appended as the last column so old rows (written
     * before this field existed, with a 5-column header) still parse fine
     * by name -- readers just won't find this column on those rows. */
    fprintf(f, "%" G_GINT64_FORMAT ",%s,%.2f,%.0f,%s,%.0f\n", now_s, status_log_name(wp->last_status),
            wp->last_watts, wp->last_capacity, screen, wp->last_energy_uwh);
    fclose(f);
}

static gboolean
on_log_sample(gpointer user_data)
{
    watt_append_log((WattPlugin *) user_data);
    return G_SOURCE_CONTINUE;
}

static void
watt_load_settings(WattPlugin *wp)
{
    wp->debug_raw = FALSE;

    gchar *file = xfce_panel_plugin_save_location(wp->plugin, FALSE);
    if (!file)
        return;

    XfceRc *rc = xfce_rc_simple_open(file, TRUE);
    g_free(file);
    if (!rc)
        return;

    xfce_rc_set_group(rc, "General");
    wp->debug_raw = xfce_rc_read_bool_entry(rc, "DebugRaw", FALSE);
    xfce_rc_close(rc);
}

static void
watt_save_settings(WattPlugin *wp)
{
    gchar *file = xfce_panel_plugin_save_location(wp->plugin, TRUE);
    if (!file)
        return;

    XfceRc *rc = xfce_rc_simple_open(file, FALSE);
    g_free(file);
    if (!rc)
        return;

    xfce_rc_set_group(rc, "General");
    xfce_rc_write_bool_entry(rc, "DebugRaw", wp->debug_raw);
    xfce_rc_close(rc);
}

static void
on_debug_raw_toggled(GtkToggleButton *toggle, WattPlugin *wp)
{
    wp->debug_raw = gtk_toggle_button_get_active(toggle);
    watt_update_label(wp);
    watt_save_settings(wp);
}

static void
on_configure_plugin(XfcePanelPlugin *plugin, WattPlugin *wp)
{
    GtkWidget *dialog = gtk_dialog_new_with_buttons(
        "Battery Wattage", GTK_WINDOW(gtk_widget_get_toplevel(GTK_WIDGET(plugin))),
        GTK_DIALOG_DESTROY_WITH_PARENT, _("_Close"), GTK_RESPONSE_CLOSE, NULL);
    gtk_window_set_icon_name(GTK_WINDOW(dialog), "battery");

    GtkWidget *grid = gtk_grid_new();
    gtk_grid_set_row_spacing(GTK_GRID(grid), 6);
    gtk_grid_set_column_spacing(GTK_GRID(grid), 12);
    gtk_container_set_border_width(GTK_CONTAINER(grid), 12);

    GtkWidget *debug_check = gtk_check_button_new_with_label(
        _("Show last 10 raw energy_now readings in tooltip (debug)"));
    gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(debug_check), wp->debug_raw);
    g_signal_connect(debug_check, "toggled", G_CALLBACK(on_debug_raw_toggled), wp);
    gtk_grid_attach(GTK_GRID(grid), debug_check, 0, 0, 2, 1);

    gtk_container_add(GTK_CONTAINER(gtk_dialog_get_content_area(GTK_DIALOG(dialog))), grid);
    gtk_widget_show_all(dialog);

    g_signal_connect(dialog, "response", G_CALLBACK(gtk_widget_destroy), NULL);
}

static void
watt_free(XfcePanelPlugin *plugin, WattPlugin *wp)
{
    (void) plugin;
    if (wp->sample_id != 0)
        g_source_remove(wp->sample_id);
    if (wp->log_id != 0)
        g_source_remove(wp->log_id);
    g_array_free(wp->ticks, TRUE);
    g_free(wp);
}

static void
watt_construct(XfcePanelPlugin *plugin)
{
    bindtextdomain("wattage-panel", LOCALE_DIR);
    bind_textdomain_codeset("wattage-panel", "UTF-8");

    WattPlugin *wp = g_new0(WattPlugin, 1);
    wp->plugin = plugin;
    wp->ticks = g_array_new(FALSE, FALSE, sizeof(EnergyPoint));
    wp->have_battery = g_file_test(BAT_PATH, G_FILE_TEST_IS_DIR);
    watt_load_settings(wp);

    wp->label = gtk_label_new(wp->have_battery ? "..." : _("no battery"));
    gtk_container_add(GTK_CONTAINER(plugin), wp->label);
    gtk_widget_show_all(GTK_WIDGET(plugin));
    xfce_panel_plugin_add_action_widget(plugin, wp->label);

    if (wp->have_battery) {
        watt_update_label(wp);
        wp->sample_id = g_timeout_add(SAMPLE_INTERVAL_MS, on_sample, wp);
        watt_append_log(wp);
        wp->log_id = g_timeout_add_seconds(LOG_INTERVAL_S, on_log_sample, wp);
    }

    g_signal_connect(plugin, "free-data", G_CALLBACK(watt_free), wp);
    g_signal_connect(plugin, "configure-plugin", G_CALLBACK(on_configure_plugin), wp);

    xfce_panel_plugin_menu_show_configure(plugin);
    xfce_panel_plugin_set_expand(plugin, FALSE);
}

XFCE_PANEL_PLUGIN_REGISTER(watt_construct);
