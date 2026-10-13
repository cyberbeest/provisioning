#!/usr/bin/env python3
"""Speak Claude's reply with Piper. Reads the full reply on stdin.

Speaks the <spoken>...</spoken> tag if present, else the first sentences.
Detaches itself so the caller returns at once; a new call stops the old one.
"""
import os, re, signal, subprocess, sys, time

HOME = os.path.expanduser("~/.local/share/claude-tts")
PIDFILE = os.path.join(HOME, "speaking.pid")
MUTE = os.path.join(HOME, "muted")
MAX_CHARS = 220

GERMAN_HINTS = {"der", "die", "das", "und", "ist", "nicht", "ich", "ein", "eine", "mit",
                "für", "auf", "zu", "den", "dem", "wir", "sie", "es", "aber", "auch", "wie"}


def stop_previous():
    try:
        pid = int(open(PIDFILE).read())
        os.killpg(pid, signal.SIGTERM)
    except (OSError, ValueError):
        pass


def capturing():
    """True while a program records from a real microphone (dictation does only while
    recording). Monitor sources, i.e. recordings of speaker output, don't count."""
    try:
        run = lambda *a: subprocess.run(["pactl", *a], capture_output=True, text=True, timeout=2).stdout
        monitors = {l.split("\t")[0] for l in run("list", "short", "sources").splitlines()
                    if l.split("\t")[1].endswith(".monitor")}
        return any(l.split("\t")[1] not in monitors
                   for l in run("list", "short", "source-outputs").splitlines() if l.strip())
    except (OSError, subprocess.SubprocessError, IndexError):
        return False


def clean(text):
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", " link ", text)
    text = re.sub(r"^\s*[#>*\-|]+\s*", "", text, flags=re.M)
    text = re.sub(r"[*_~#|]+", "", text)
    text = re.sub(r"(?:/[\w.\-~]+){2,}", " ", text)  # file paths
    return re.sub(r"\s+", " ", text).strip()


def pick_text(reply):
    tag = re.findall(r"<spoken>(.*?)</spoken>", reply, flags=re.S)
    if tag:
        return clean(tag[-1])
    body = clean(reply)
    out = ""
    for s in re.split(r"(?<=[.!?:])\s+", body):
        if out and len(out) + len(s) > MAX_CHARS:
            break
        out += (" " if out else "") + s
        if len(out) >= MAX_CHARS * 0.6:
            break
    return out[:MAX_CHARS].strip()


def voice_for(text):
    words = re.findall(r"[a-zäöüß]+", text.lower())
    de = sum(w in GERMAN_HINTS for w in words)
    if re.search(r"[äöüß]", text.lower()) and de >= 1 or de >= max(3, len(words) // 8):
        return "de_DE-thorsten-medium"
    return "en_US-ryan-medium"


def main():
    if "--stop" in sys.argv:
        stop_previous()
        return
    if "--toggle" in sys.argv:
        if os.path.exists(MUTE):
            os.remove(MUTE); print("on")
        else:
            open(MUTE, "w").close(); stop_previous(); print("off")
        return
    if os.path.exists(MUTE):
        return
    text = pick_text(sys.stdin.read())
    if not text or capturing():
        return
    stop_previous()
    if os.fork():
        return
    os.setsid()
    for fd in (0, 1, 2):
        os.close(fd)
    os.open(os.devnull, os.O_RDWR); os.dup(0); os.dup(0)
    open(PIDFILE, "w").write(str(os.getpid()))
    model = os.path.join(HOME, voice_for(text) + ".onnx")
    piper = subprocess.Popen([os.path.join(HOME, "venv/bin/python"), "-m", "piper",
                              "-m", model, "--output-raw"],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    play = subprocess.Popen(["paplay", "--raw", "--format=s16le", "--rate=22050", "--channels=1"],
                            stdin=piper.stdout)
    piper.stdin.write(text.encode()); piper.stdin.close()
    while play.poll() is None:
        if capturing():
            for proc in (play, piper):
                proc.kill()
            break
        time.sleep(0.25)


if __name__ == "__main__":
    main()
