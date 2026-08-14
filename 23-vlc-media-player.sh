#!/bin/bash
# Installs VLC media player -- plain apt package, in Debian main, no repo
# setup needed -- and removes Parole (the GStreamer-based player that ships
# by default with the xfce4 metapackage), since Parole failed to seek
# through some video files while VLC handles them fine. Also sets VLC as
# the default handler for common video mimetypes and disables VLC's "allow
# metadata network access" dialog (defaults it to off instead of asking).
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/23-vlc-media-player.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing VLC ==="
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y vlc

echo "--- Removing Parole (redundant with VLC, had seek bugs) ---"
apt-get -o DPkg::Lock::Timeout=60 remove -y parole
apt-get -o DPkg::Lock::Timeout=60 autoremove -y

TARGET_USER="${SUDO_USER:-cyberbeest}"

echo "--- Setting VLC as default video player for $TARGET_USER ---"
VIDEO_MIMES="video/mp4 video/x-matroska video/x-msvideo video/quicktime video/webm video/mpeg video/x-flv video/3gpp video/x-ms-wmv video/ogg"
su - "$TARGET_USER" -c "xdg-mime default vlc.desktop $VIDEO_MIMES"

echo "--- Disabling VLC's metadata-network-access prompt (default: off) ---"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/vlc"
VLCRC="$TARGET_HOME/.config/vlc/vlcrc"
if [ ! -f "$VLCRC" ]; then
    printf '[core]\nmetadata-network-access=0\n' > "$VLCRC"
    chown "$TARGET_USER:$TARGET_USER" "$VLCRC"
elif grep -q '^metadata-network-access=' "$VLCRC"; then
    sed -i 's/^metadata-network-access=.*/metadata-network-access=0/' "$VLCRC"
elif grep -q '^#metadata-network-access=' "$VLCRC"; then
    sed -i 's/^#metadata-network-access=.*/metadata-network-access=0/' "$VLCRC"
else
    echo 'metadata-network-access=0' >> "$VLCRC"
fi

echo "--- Enabling 'continue playback' (resume position, no prompt) ---"
if grep -q '^qt-continue=' "$VLCRC"; then
    sed -i 's/^qt-continue=.*/qt-continue=2/' "$VLCRC"
elif grep -q '^#qt-continue=' "$VLCRC"; then
    sed -i 's/^#qt-continue=.*/qt-continue=2/' "$VLCRC"
else
    echo 'qt-continue=2' >> "$VLCRC"
fi

echo "=== done ==="
