/*
 * wattage-panel: xfce4-panel plugin showing battery power draw and
 * estimated remaining time.
 *
 * The kernel's power_now (BAT0/power_now) is a very short-term
 * instantaneous reading that has been observed to never report below
 * ~3.8W even when real draw is lower. This plugin can instead compute
 * its own wattage by averaging energy_now deltas over a configurable
 * trailing window (kept in memory -- no history file needed, unlike the
 * genmon script this replaces), which is both more stable and more
 * accurate for the remaining-time estimate. Both modes are available,
 * toggled from the plugin's own Properties dialog.
 *
 * Built as an "external" plugin (X-XFCE-Internal=FALSE), same as
 * kitt-scanner, so a crash here takes down only this plugin's process.
 */

#include <gtk/gtk.h>
#include <gdk/gdkx.h>
#include <X11/Xlib.h>
#include <X11/extensions/dpms.h>
#include <libxfce4panel/libxfce4panel.h>
#include <libxfce4util/libxfce4util.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

#define BAT_PATH "/sys/class/power_supply/BAT0"
#define SAMPLE_INTERVAL_MS 3000

/* Periodic history log for building an hourly consumption graph later.
 * Kept separate from SAMPLE_INTERVAL_MS (which drives the live label) so
 * the on-disk history doesn't balloon -- one row every 5 minutes is
 * plenty for an hour-granularity graph. */
#define LOG_INTERVAL_S (5 * 60)
#define LOG_SUBDIR "wattage-panel"
#define LOG_FILE "history.csv"

#define DEFAULT_USE_LONGTERM TRUE
#define DEFAULT_AVG_MINUTES 5
#define MIN_AVG_MINUTES 1
#define MAX_AVG_MINUTES 60

/* Below this, fall back to the instant reading: energy_now has limited
 * granularity, so a too-short dt makes the diff/dt division noisy. Once
 * this much data exists, the average window grows with elapsed time
 * (anchored at plugin start / last status change) up to avg_minutes. */
#define MIN_WINDOW_SPAN_S 20

/* Don't switch to the long-term average until at least this fraction of
 * the configured averaging window has elapsed -- with only a few seconds
 * of data, a single quantization step in energy_now can produce wildly
 * wrong watt/remaining-time readings (e.g. 50W, 0:30 remaining). */
#define MIN_WINDOW_FRACTION 0.5

typedef enum {
    BATT_DISCHARGING,
    BATT_CHARGING,
    BATT_OTHER
} BattStatus;

typedef struct {
    gint64 time_s;
    gdouble energy_uwh;
    BattStatus status;
} WattSample;

typedef struct {
    XfcePanelPlugin *plugin;
    GtkWidget *label;

    GArray *history; /* of WattSample, oldest first */

    gboolean use_longterm;
    gint avg_minutes;

    gboolean have_battery;
    guint sample_id;
    guint log_id;

    gboolean have_last;
    BattStatus last_status;
    gdouble last_watts;
    gdouble last_capacity;
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

static void
watt_prune_history(WattPlugin *wp, gint64 now_s)
{
    gint64 cutoff = now_s - (gint64) wp->avg_minutes * 60 * 2;
    guint drop = 0;
    while (drop < wp->history->len &&
           g_array_index(wp->history, WattSample, drop).time_s < cutoff)
        drop++;
    if (drop > 0)
        g_array_remove_range(wp->history, 0, drop);
}

/* Oldest sample within the averaging window belonging to the current,
 * unbroken run of `status` -- a status change (e.g. plugging into AC,
 * or unplugging again) resets the average, even if older samples with
 * a matching status are still sitting further back in the history
 * buffer (which retains up to 2x the averaging window). Walking from
 * the newest sample backwards and stopping at the first mismatch is
 * what enforces that contiguity; a plain "oldest sample anywhere in
 * the window with this status" scan would wrongly straddle the gap
 * and blend pre-AC and post-AC energy readings into one average. NULL
 * if there is no history yet. */
static const WattSample *
watt_find_window_start(WattPlugin *wp, gint64 now_s, BattStatus status)
{
    gint64 cutoff = now_s - (gint64) wp->avg_minutes * 60;
    const WattSample *start = NULL;
    for (guint i = wp->history->len; i > 0; i--) {
        const WattSample *s = &g_array_index(wp->history, WattSample, i - 1);
        if (s->status != status || s->time_s < cutoff)
            break;
        start = s;
    }
    return start;
}

static void
watt_update_label(WattPlugin *wp)
{
    gchar status_buf[32] = { 0 };
    gdouble power_uw = 0, energy_uwh = 0, capacity = 0;

    if (!wp->have_battery) {
        gtk_label_set_text(GTK_LABEL(wp->label), "no battery");
        return;
    }

    read_file_string(BAT_PATH "/status", status_buf, sizeof(status_buf));
    read_file_double(BAT_PATH "/power_now", &power_uw);
    read_file_double(BAT_PATH "/energy_now", &energy_uwh);
    read_file_double(BAT_PATH "/capacity", &capacity);

    BattStatus status = parse_status(status_buf);
    gint64 now_s = g_get_real_time() / G_USEC_PER_SEC;

    WattSample sample = { .time_s = now_s, .energy_uwh = energy_uwh, .status = status };
    g_array_append_val(wp->history, sample);
    watt_prune_history(wp, now_s);

    gdouble watts_instant = power_uw / 1000000.0;
    gdouble watts = watts_instant;
    gboolean have_longterm = FALSE;
    gint64 span_s = 0; /* actual length of the averaging window in use */

    const WattSample *start = watt_find_window_start(wp, now_s, status);
    if (start) {
        span_s = now_s - start->time_s;
        gint64 min_span_s = MAX(MIN_WINDOW_SPAN_S,
                                 (gint64) (wp->avg_minutes * 60 * MIN_WINDOW_FRACTION));
        if (span_s >= min_span_s) {
            gdouble diff_uwh = fabs(start->energy_uwh - energy_uwh);
            /* energy_now on some hardware only updates every 15-60s; if it
             * hasn't ticked over yet within our window, a zero diff would
             * read as a bogus 0.0W rather than "not enough data yet". */
            if (diff_uwh > 0.0) {
                gdouble hours = span_s / 3600.0;
                watts = (diff_uwh / 1000000.0) / hours;
                have_longterm = TRUE;
            }
        }
    }

    if (!(wp->use_longterm && have_longterm))
        watts = watts_instant;

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
            g_snprintf(text, sizeof(text), "%.1fW chg", watts);
            break;
        default:
            g_snprintf(text, sizeof(text), "AC");
            break;
    }
    gtk_label_set_text(GTK_LABEL(wp->label), text);

    const gchar *avg_state = !wp->use_longterm ? "off, using instant power_now"
                             : have_longterm    ? "active"
                                                 : "warming up";

    /* The window's oldest kept sample lands a sample interval or so after
     * the theoretical cutoff, so once the window is effectively full,
     * span_s asymptotes just under avg_minutes*60 (e.g. perpetually
     * "4:58 of 5") instead of ever reaching it. Purely cosmetic: once
     * within one sample interval of full, just display it as full. */
    gint64 display_span_s = span_s;
    gint64 full_span_s = (gint64) wp->avg_minutes * 60;
    if (have_longterm && full_span_s - span_s <= SAMPLE_INTERVAL_MS / 1000)
        display_span_s = full_span_s;

    gchar span_buf[32];
    if (display_span_s >= 60)
        g_snprintf(span_buf, sizeof(span_buf), "%d:%02d", (int) (display_span_s / 60), (int) (display_span_s % 60));
    else
        g_snprintf(span_buf, sizeof(span_buf), "%ds", (int) display_span_s);

    gchar tooltip[220];
    g_snprintf(tooltip, sizeof(tooltip),
               "Battery: %.0f%% (%s)\nPower: %.1f W (instant: %.1f W)\n"
               "Long-term average window: %s of %d min (%s)",
               capacity, status_buf, watts, watts_instant, span_buf, wp->avg_minutes, avg_state);
    gtk_widget_set_tooltip_text(wp->label, tooltip);

    wp->last_status = status;
    wp->last_watts = watts;
    wp->last_capacity = capacity;
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
 * watts) so an hour-granularity graph can be built later without keeping
 * the plugin running the whole time. Uses whatever watts value is
 * currently on display (long-term average when available, else instant),
 * so it stays consistent with what the user was actually looking at. */
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
        fputs("timestamp,status,watts,battery_pct,screen\n", f);

    gint64 now_s = g_get_real_time() / G_USEC_PER_SEC;
    const gchar *screen = display_is_off(wp) ? "off" : "on";
    fprintf(f, "%" G_GINT64_FORMAT ",%s,%.2f,%.0f,%s\n", now_s, status_log_name(wp->last_status),
            wp->last_watts, wp->last_capacity, screen);
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
    wp->use_longterm = DEFAULT_USE_LONGTERM;
    wp->avg_minutes = DEFAULT_AVG_MINUTES;

    gchar *file = xfce_panel_plugin_save_location(wp->plugin, FALSE);
    if (!file)
        return;

    XfceRc *rc = xfce_rc_simple_open(file, TRUE);
    g_free(file);
    if (!rc)
        return;

    xfce_rc_set_group(rc, "General");
    wp->use_longterm = xfce_rc_read_bool_entry(rc, "UseLongtermWatts", DEFAULT_USE_LONGTERM);
    wp->avg_minutes = xfce_rc_read_int_entry(rc, "AvgMinutes", DEFAULT_AVG_MINUTES);
    wp->avg_minutes = CLAMP(wp->avg_minutes, MIN_AVG_MINUTES, MAX_AVG_MINUTES);
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
    xfce_rc_write_bool_entry(rc, "UseLongtermWatts", wp->use_longterm);
    xfce_rc_write_int_entry(rc, "AvgMinutes", wp->avg_minutes);
    xfce_rc_close(rc);
}

static void
on_use_longterm_toggled(GtkToggleButton *toggle, WattPlugin *wp)
{
    wp->use_longterm = gtk_toggle_button_get_active(toggle);
    watt_update_label(wp);
    watt_save_settings(wp);
}

static void
on_avg_minutes_changed(GtkSpinButton *spin, WattPlugin *wp)
{
    wp->avg_minutes = gtk_spin_button_get_value_as_int(spin);
    watt_update_label(wp);
    watt_save_settings(wp);
}

static void
on_configure_plugin(XfcePanelPlugin *plugin, WattPlugin *wp)
{
    GtkWidget *dialog = gtk_dialog_new_with_buttons(
        "Battery Wattage", GTK_WINDOW(gtk_widget_get_toplevel(GTK_WIDGET(plugin))),
        GTK_DIALOG_DESTROY_WITH_PARENT, "_Close", GTK_RESPONSE_CLOSE, NULL);
    gtk_window_set_icon_name(GTK_WINDOW(dialog), "battery");

    GtkWidget *grid = gtk_grid_new();
    gtk_grid_set_row_spacing(GTK_GRID(grid), 6);
    gtk_grid_set_column_spacing(GTK_GRID(grid), 12);
    gtk_container_set_border_width(GTK_CONTAINER(grid), 12);

    GtkWidget *longterm_check = gtk_check_button_new_with_label(
        "Use long-term average watts (avoids power_now's ~3.8W floor)");
    gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(longterm_check), wp->use_longterm);
    g_signal_connect(longterm_check, "toggled", G_CALLBACK(on_use_longterm_toggled), wp);
    gtk_grid_attach(GTK_GRID(grid), longterm_check, 0, 0, 2, 1);

    GtkWidget *avg_label = gtk_label_new("Average window, minutes:");
    gtk_widget_set_halign(avg_label, GTK_ALIGN_START);
    GtkWidget *avg_spin = gtk_spin_button_new_with_range(MIN_AVG_MINUTES, MAX_AVG_MINUTES, 1);
    gtk_spin_button_set_value(GTK_SPIN_BUTTON(avg_spin), wp->avg_minutes);
    g_signal_connect(avg_spin, "value-changed", G_CALLBACK(on_avg_minutes_changed), wp);
    gtk_grid_attach(GTK_GRID(grid), avg_label, 0, 1, 1, 1);
    gtk_grid_attach(GTK_GRID(grid), avg_spin, 1, 1, 1, 1);

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
    g_array_free(wp->history, TRUE);
    g_free(wp);
}

static void
watt_construct(XfcePanelPlugin *plugin)
{
    WattPlugin *wp = g_new0(WattPlugin, 1);
    wp->plugin = plugin;
    wp->history = g_array_new(FALSE, FALSE, sizeof(WattSample));
    wp->have_battery = g_file_test(BAT_PATH, G_FILE_TEST_IS_DIR);
    watt_load_settings(wp);

    wp->label = gtk_label_new(wp->have_battery ? "..." : "no battery");
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
