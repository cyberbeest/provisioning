#!/bin/bash
# Installs Dictate (lib/dictate/, see PROVENANCE.md there): push-to-talk voice
# dictation that types into whatever window has focus. Runs entirely on this
# machine -- the speech model (parakeet-primeline, German + other European
# languages, CPU-only via sherpa-onnx) is downloaded once here and nothing
# is sent anywhere afterwards. The model comes from cyberbeest.com/models
# (SHA-256-verified; Hugging Face is the fallback). Cloud providers (Groq/OpenAI) exist in the app
# but are never configured by this script, and the panel icon's tooltip says
# in plain words whether audio stays local.
#
# On by default: it autostarts at login as a panel icon with no window
# (Settings has a checkbox to turn that off). The model is not loaded at
# login: the first hotkey press loads it while the user speaks (~6 s of CPU on
# the N3350, so little is left to wait for). It then stays in RAM while plenty
# is free and is unloaded after 5 idle minutes only when memory gets short.
#
# Global hotkey (F9, hold to talk) is read through pynput/X11. The evdev
# backend would need the account in group `input`, i.e. read access to every
# keyboard -- not worth it on X11, so it is deliberately not set up.
#
# The app's Python packages go into a private venv (pinned to the versions
# it was tested with), the model into ~/.local/share/dictate/models.
#
# Idempotent: safe to re-run. Needs network (apt, PyPI, Hugging Face); if the
# model download fails the app still installs and offers a "Download model"
# button in its Settings.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/65-dictate.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing Dictate ==="

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
APP_DIR="$TARGET_HOME/.local/share/dictate/app"
run_as_user() { sudo -u "$TARGET_USER" -H "$@"; }

echo "--- Installing system packages ---"
# xdotool types the result; libportaudio2 is sounddevice's runtime library;
# the xcb libraries are what Qt's X11 platform plugin loads.
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y \
    python3-venv xdotool libnotify-bin libportaudio2 libxcb-cursor0 \
    libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
    libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1

echo "--- Installing the app to $APP_DIR ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" \
    "$TARGET_HOME/.local/share/dictate" "$APP_DIR"
for f in core.py gui.py i18n.py local_stt.py evdev_listener.py LICENSE; do
    install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR/lib/dictate/$f" "$APP_DIR/$f"
done
chmod 755 "$APP_DIR/gui.py"

echo "--- Creating the Python environment (large download: Qt + sherpa-onnx) ---"
if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
    run_as_user python3 -m venv "$APP_DIR/.venv"
fi
run_as_user "$APP_DIR/.venv/bin/pip" install --quiet --disable-pip-version-check \
    PyQt6==6.11.0 sounddevice==0.5.6 pynput==1.8.2 requests numpy==2.5.3 \
    sherpa-onnx==1.13.8 soundfile==0.14.0 huggingface_hub==2.2.0

echo "--- Writing default settings (only if there are none yet) ---"
CONF_DIR="$TARGET_HOME/.config/dictate"
CONF="$CONF_DIR/config.json"
if [ ! -f "$CONF" ]; then
    install -d -o "$TARGET_USER" -g "$TARGET_USER" "$CONF_DIR"
    THREADS="$(nproc)"; [ "$THREADS" -gt 4 ] && THREADS=4
    cat > "$CONF" <<EOF
{
  "provider": "parakeet_local",
  "mode": "ptt",
  "key": "f9",
  "model": "parakeet-primeline-int8",
  "threshold": 0.0,
  "local_stt_num_threads": $THREADS,
  "local_stt_idle_minutes": 5,
  "start_hidden": true,
  "language": "auto"
}
EOF
    chown "$TARGET_USER:$TARGET_USER" "$CONF"
else
    echo "(kept existing $CONF)"
fi

# The profile dialog's "Dictation" checkbox (PROVISIONING_DICTATION_MODEL):
# unticked for e.g. VM test runs. A missing profile file or variable means
# "download", the behavior of a standalone run. Dictate fetches a missing
# model by itself on the first hotkey press, so skipping is harmless.
PROVISIONING_DICTATION_MODEL="yes"
if [ -f "$DIR/.provisioning-profile.env" ]; then
    # shellcheck disable=SC1091
    . "$DIR/.provisioning-profile.env"
fi

if [ "$PROVISIONING_DICTATION_MODEL" = "no" ]; then
    echo "--- Speech model download disabled in the provisioning profile -- skipping ---"
else
echo "--- Downloading the speech model (~640 MB, one-time) ---"
run_as_user bash -c "cd '$APP_DIR' && '$APP_DIR/.venv/bin/python' -c '
import local_stt
if local_stt.model_installed():
    print(\"model already installed\")
else:
    seen = []
    def log_progress(msg):  # one line per file, not one per progress tick
        key = msg.split(\" (\")[0]
        if key not in seen:
            seen.append(key)
            print(msg, flush=True)
    local_stt.download_model(progress_cb=log_progress)
'" || echo "WARNING: model download failed -- Dictate retries on the first hotkey press"
fi

echo "--- Installing menu entry and autostart ---"
DESKTOP_BODY="[Desktop Entry]
Type=Application
Name=Dictate
GenericName=Voice dictation
Comment=Voice dictation, entirely on this computer
Exec=$APP_DIR/.venv/bin/python $APP_DIR/gui.py
Icon=audio-input-microphone
Terminal=false
Categories=Utility;Audio;Accessibility;
StartupNotify=false"
install -d -o "$TARGET_USER" -g "$TARGET_USER" \
    "$TARGET_HOME/.local/share/applications" "$TARGET_HOME/.config/autostart"
# Autostart is switched on by the first install only; a re-run must not undo
# the user turning it off in Dictate's Settings.
FIRST_INSTALL=0
[ -f "$TARGET_HOME/.local/share/applications/dictate.desktop" ] || FIRST_INSTALL=1
printf '%s\n' "$DESKTOP_BODY" > "$TARGET_HOME/.local/share/applications/dictate.desktop"
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/share/applications/dictate.desktop"
if [ "$FIRST_INSTALL" = 1 ]; then
    printf '%s\nX-GNOME-Autostart-enabled=true\n' "$DESKTOP_BODY" > "$TARGET_HOME/.config/autostart/dictate.desktop"
    chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.config/autostart/dictate.desktop"
fi
run_as_user update-desktop-database "$TARGET_HOME/.local/share/applications" >/dev/null 2>&1 || true

echo "=== $(date) : done (Dictate starts at next login, or launch it from the menu) ==="
