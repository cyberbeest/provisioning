/*
 * cpuload-color: minimal native xfce4-panel plugin.
 * Paints a solid color from black (idle) to red (100% CPU load).
 * Built as an "external" plugin (X-XFCE-Internal=FALSE in the .desktop
 * file), so a crash in here takes down only this plugin's process, not
 * the panel.
 */

#include <gtk/gtk.h>
#include <libxfce4panel/libxfce4panel.h>
#include <stdio.h>

#define POLL_INTERVAL_MS 500
#define ASPECT_RATIO 4 /* width = panel size * ASPECT_RATIO */

typedef struct {
    XfcePanelPlugin *plugin;
    GtkWidget *area;
    gdouble load;
    guint timeout_id;
    long prev_idle;
    long prev_total;
} CpuColorPlugin;

static gboolean
sample_cpu_load(CpuColorPlugin *cp)
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
    long d_idle = total_idle - cp->prev_idle;
    long d_total = total - cp->prev_total;
    cp->prev_idle = total_idle;
    cp->prev_total = total;

    if (d_total <= 0)
        return TRUE; /* leave cp->load unchanged on the first sample */

    gdouble load = 1.0 - ((gdouble) d_idle / (gdouble) d_total);
    if (load < 0.0)
        load = 0.0;
    if (load > 1.0)
        load = 1.0;
    cp->load = load;
    return TRUE;
}

static gboolean
on_tick(gpointer user_data)
{
    CpuColorPlugin *cp = user_data;
    if (sample_cpu_load(cp))
        gtk_widget_queue_draw(cp->area);
    return G_SOURCE_CONTINUE;
}

static gboolean
on_draw(GtkWidget *widget, cairo_t *cr, gpointer user_data)
{
    CpuColorPlugin *cp = user_data;
    GtkAllocation alloc;
    gtk_widget_get_allocation(widget, &alloc);

    cairo_set_source_rgb(cr, cp->load, 0.0, 0.0);
    cairo_rectangle(cr, 0, 0, alloc.width, alloc.height);
    cairo_fill(cr);
    return TRUE;
}

static gboolean
on_size_changed(XfcePanelPlugin *plugin, guint size, CpuColorPlugin *cp)
{
    gtk_widget_set_size_request(cp->area, size * ASPECT_RATIO, size);
    return TRUE;
}

static void
cpu_color_free(XfcePanelPlugin *plugin, CpuColorPlugin *cp)
{
    if (cp->timeout_id != 0)
        g_source_remove(cp->timeout_id);
    g_free(cp);
}

static void
cpu_color_construct(XfcePanelPlugin *plugin)
{
    CpuColorPlugin *cp = g_new0(CpuColorPlugin, 1);
    cp->plugin = plugin;

    cp->area = gtk_drawing_area_new();
    gtk_widget_add_events(cp->area, GDK_BUTTON_PRESS_MASK | GDK_BUTTON_RELEASE_MASK);
    g_signal_connect(cp->area, "draw", G_CALLBACK(on_draw), cp);

    gtk_container_add(GTK_CONTAINER(plugin), cp->area);
    gtk_widget_show_all(GTK_WIDGET(plugin));
    xfce_panel_plugin_add_action_widget(plugin, cp->area);

    sample_cpu_load(cp); /* prime the counters, first sample has no delta */
    cp->timeout_id = g_timeout_add(POLL_INTERVAL_MS, on_tick, cp);

    g_signal_connect(plugin, "free-data", G_CALLBACK(cpu_color_free), cp);
    g_signal_connect(plugin, "size-changed", G_CALLBACK(on_size_changed), cp);

    xfce_panel_plugin_set_expand(plugin, FALSE);
}

XFCE_PANEL_PLUGIN_REGISTER(cpu_color_construct);
