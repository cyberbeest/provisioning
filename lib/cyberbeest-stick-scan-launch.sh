#!/bin/bash
# Started at login of the live image (via /etc/xdg/autostart, added by
# remaster-live-stick.sh). Does nothing unless the stick was booted with
# "cyberbeest-scan" on the kernel command line -- i.e. from the first boot
# menu entry, "Scan this computer for malware" -- in which case it replaces
# the desktop experience with the fullscreen scan window.
grep -qw cyberbeest-scan /proc/cmdline || exit 0

# State dir shared between the unprivileged GUI (drops the Cancel file) and
# the root scan helper (writes reports).
sudo -n install -d -m 1777 /run/cyberbeest-scan

# A scan takes hours: no screen lock, blanking or sleep on idle/lid close.
xset s off -dpms s noblank 2>/dev/null || true
for prop in /lock/enabled /saver/enabled; do
	xfconf-query -c xfce4-screensaver -p "$prop" -n -t bool -s false 2>/dev/null || true
done
xfce4-screensaver-command --exit 2>/dev/null || true

# Relaunch if the window is closed or crashes; the scan is the whole point.
while :; do
	systemd-inhibit --what=sleep:idle:handle-lid-switch --who="Cyberbeest scan" \
		--why="Malware scan in progress" \
		python3 /usr/local/lib/cyberbeest/cyberbeest_scanner_gui.py --stick
	sleep 2
done
