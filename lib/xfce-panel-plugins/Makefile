CC = gcc
CFLAGS = -Wall -O2 -fPIC $(shell pkg-config --cflags gtk+-3.0 libxfce4panel-2.0 libxfce4util-1.0 x11 xext)
LIBS = $(shell pkg-config --libs gtk+-3.0 libxfce4panel-2.0 libxfce4util-1.0 x11 xext) -lm

PLUGIN_DIR = $(shell pkg-config --variable=libdir libxfce4panel-2.0)/xfce4/panel/plugins
DESKTOP_DIR = $(shell pkg-config --variable=datarootdir libxfce4panel-2.0)/xfce4/panel/plugins
LOCALE_DIR = /usr/share/locale

SOS = libcpuload-color.so libkitt-scanner.so libwattage-panel.so libmem-liquid.so
DESKTOPS = cpuload-color.desktop kitt-scanner.desktop wattage-panel.desktop mem-liquid.desktop

# gettext domains translated via po/<domain>.de.po -- see i18n comment at the
# top of kitt-scanner.c. cpuload-color isn't in this list: it's unused dead
# code (not referenced by any panel layout), so not worth translating.
I18N_DOMAINS = kitt-scanner mem-liquid wattage-panel
MOS = $(addsuffix .mo,$(I18N_DOMAINS))

all: $(SOS) $(MOS)

libcpuload-color.so: cpuload-color.c
	$(CC) -shared $(CFLAGS) -o $@ $< $(LIBS)

libkitt-scanner.so: kitt-scanner.c
	$(CC) -shared $(CFLAGS) -DLOCALE_DIR='"$(LOCALE_DIR)"' -o $@ $< $(LIBS)

libwattage-panel.so: wattage-panel.c
	$(CC) -shared $(CFLAGS) -DLOCALE_DIR='"$(LOCALE_DIR)"' -o $@ $< $(LIBS)

libmem-liquid.so: mem-liquid.c
	$(CC) -shared $(CFLAGS) -DLOCALE_DIR='"$(LOCALE_DIR)"' -o $@ $< $(LIBS)

%.mo: po/%.de.po
	msgfmt -o $@ $<

install: $(SOS) $(MOS)
	install -d $(DESTDIR)$(PLUGIN_DIR) $(DESTDIR)$(DESKTOP_DIR)
	install -m 644 $(SOS) $(DESTDIR)$(PLUGIN_DIR)/
	install -m 644 $(DESKTOPS) $(DESTDIR)$(DESKTOP_DIR)/
	install -d $(DESTDIR)$(LOCALE_DIR)/de/LC_MESSAGES
	for d in $(I18N_DOMAINS); do \
		install -m 644 $$d.mo $(DESTDIR)$(LOCALE_DIR)/de/LC_MESSAGES/$$d.mo; \
	done

clean:
	rm -f $(SOS) $(MOS)

.PHONY: all install clean
