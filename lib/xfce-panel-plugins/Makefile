CC = gcc
CFLAGS = -Wall -O2 -fPIC $(shell pkg-config --cflags gtk+-3.0 libxfce4panel-2.0 libxfce4util-1.0 x11 xext)
LIBS = $(shell pkg-config --libs gtk+-3.0 libxfce4panel-2.0 libxfce4util-1.0 x11 xext) -lm

PLUGIN_DIR = $(shell pkg-config --variable=libdir libxfce4panel-2.0)/xfce4/panel/plugins
DESKTOP_DIR = $(shell pkg-config --variable=datarootdir libxfce4panel-2.0)/xfce4/panel/plugins

SOS = libcpuload-color.so libkitt-scanner.so libwattage-panel.so libmem-liquid.so
DESKTOPS = cpuload-color.desktop kitt-scanner.desktop wattage-panel.desktop mem-liquid.desktop

all: $(SOS)

libcpuload-color.so: cpuload-color.c
	$(CC) -shared $(CFLAGS) -o $@ $< $(LIBS)

libkitt-scanner.so: kitt-scanner.c
	$(CC) -shared $(CFLAGS) -o $@ $< $(LIBS)

libwattage-panel.so: wattage-panel.c
	$(CC) -shared $(CFLAGS) -o $@ $< $(LIBS)

libmem-liquid.so: mem-liquid.c
	$(CC) -shared $(CFLAGS) -o $@ $< $(LIBS)

install: $(SOS)
	install -d $(DESTDIR)$(PLUGIN_DIR) $(DESTDIR)$(DESKTOP_DIR)
	install -m 644 $(SOS) $(DESTDIR)$(PLUGIN_DIR)/
	install -m 644 $(DESKTOPS) $(DESTDIR)$(DESKTOP_DIR)/

clean:
	rm -f $(SOS)

.PHONY: all install clean
