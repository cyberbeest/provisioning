#!/usr/bin/env python3
"""Speak Claude's reply with Piper. Reads the full reply on stdin.

Speaks the <spoken>...</spoken> tag if present, else the first sentences.
Detaches itself so the caller returns at once; a new call stops the old one.
"""
import os, re, signal, struct, subprocess, sys, threading, time

HOME = os.path.expanduser("~/.local/share/claude-tts")
PIDFILE = os.path.join(HOME, "speaking.pid")
MUTE = os.path.join(HOME, "muted")
MAX_CHARS = 220
LENGTH_SCALE = 0.81  # below 1.0 speaks faster

GERMAN_HINTS = {"der", "die", "das", "und", "ist", "nicht", "ich", "ein", "eine", "mit",
                "für", "auf", "zu", "den", "dem", "wir", "sie", "es", "aber", "auch", "wie"}


def log(line):
    path = os.path.join(HOME, "speak.log")
    try:
        if os.path.getsize(path) > 20000:
            os.replace(path, path + ".1")
    except OSError:
        pass
    with open(path, "a") as f:
        f.write(time.strftime("%H:%M:%S ") + line + "\n")


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


KINDS = ("yes", "no", "problem", "success", "uploaded", "downloaded", "question", "info", "collaborate")


def parse_reply(reply):
    """Returns (kind, text): the message type and what to say."""
    tag = re.findall(r"<spoken(?:\s+type=[\"']?(\w+)[\"']?)?\s*>(.*?)</spoken>", reply, flags=re.S)
    if tag:
        kind, spoken = tag[-1]
        return (kind if kind in KINDS else "info"), clean(spoken)
    return "info", pick_text(reply)


def pick_text(reply):
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
    return "en_GB-alan-medium"


SENTENCE_SPLIT = re.compile(r"(?<=[.!?:])\s+")
SAFETY = 1.15  # assume synthesis may be this much slower than measured so far


def can_start(frames, chars, is_done):
    """True when playback can run through without a gap. frames: (pcm, audio_s, synth_s) received
    so far; chars: characters per sentence. Every pending sentence must be ready by the time
    the audio before it has played."""
    if is_done:
        return True
    n = len(frames)
    if n == 0:
        return False
    done_chars = max(1, sum(chars[:n]))
    buffered = sum(f[1] for f in frames)
    synth_per_char = sum(f[2] for f in frames) / done_chars * SAFETY
    audio_per_char = buffered / done_chars
    wait, playable = 0.0, buffered
    for c in chars[n:]:
        wait += c * synth_per_char
        if wait > playable:
            return False
        playable += c * audio_per_char
    return True


def play_reply(kind, text):
    """Runs in the detached child: earcon at once, then speech, starting as soon as it can run unbroken."""
    t0 = time.time()
    model = os.path.join(HOME, voice_for(text) + ".onnx")
    sentences = [x for x in SENTENCE_SPLIT.split(text) if x.strip()]
    chars = [len(x) for x in sentences]
    synth = subprocess.Popen([os.path.join(HOME, "venv/bin/python"), os.path.join(HOME, "synth.py"),
                              model, str(LENGTH_SCALE)], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    synth.stdin.write(("\n".join(sentences) + "\n").encode())
    synth.stdin.close()

    frames, state, cond = [], {"rate": 22050, "done": False}, threading.Condition()

    def read_exact(n):
        buf = b""
        while len(buf) < n:
            piece = synth.stdout.read(n - len(buf))
            if not piece:
                return None
            buf += piece
        return buf

    def reader():
        head = read_exact(4)
        if head:
            state["rate"] = struct.unpack("<I", head)[0]
            while True:
                head = read_exact(8)
                if head is None:
                    break
                size, took = struct.unpack("<If", head)
                pcm = read_exact(size)
                if pcm is None:
                    break
                with cond:
                    frames.append((pcm, size / 2 / state["rate"], took))
                    cond.notify_all()
        with cond:
            state["done"] = True
            cond.notify_all()

    threading.Thread(target=reader, daemon=True).start()

    earcon = None
    path = os.path.join(HOME, "sounds", kind + ".wav")
    if os.path.exists(path):  # starts at once, while Piper is still loading
        earcon = subprocess.Popen(["paplay", path], stderr=subprocess.PIPE, text=True)

    def abort():
        for proc in (synth, earcon):
            if proc and proc.poll() is None:
                proc.kill()

    while time.time() - t0 < 90:  # the limit is only a safety net
        with cond:
            if can_start(frames, chars, state["done"]):
                break
            cond.wait(0.1)
        if capturing():
            abort()
            return
    started = time.time() - t0
    if earcon:
        earcon.wait()
        log(f"earcon {kind}: rc={earcon.returncode} {earcon.stderr.read().strip()}")

    play = subprocess.Popen(["paplay", "--raw", "--format=s16le", f"--rate={state['rate']}", "--channels=1"],
                            stdin=subprocess.PIPE)

    def feeder():
        i = 0
        while True:
            with cond:
                while i >= len(frames) and not state["done"]:
                    log(f"starved: waiting for sentence {i + 1}")
                    cond.wait(0.2)
                if i >= len(frames):
                    break
                pcm = frames[i][0]
            i += 1
            try:
                play.stdin.write(pcm)
                play.stdin.flush()
            except (BrokenPipeError, ValueError):
                return
        try:
            play.stdin.close()
        except OSError:
            pass

    threading.Thread(target=feeder, daemon=True).start()
    with cond:
        log(f"speech starts after {started:.1f}s with {len(frames)}/{len(sentences)} sentences ready")
    while play.poll() is None:
        if capturing():
            play.kill()
            abort()
            break
        time.sleep(0.25)
    synth.kill()


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
    kind, text = parse_reply(sys.stdin.read())
    if not text or capturing():
        return
    stop_previous()
    if os.fork():
        return
    os.setsid()
    # dup2, not close+open: Python's own fds are non-inheritable, which left paplay without stdio
    dn_r, dn_w = os.open(os.devnull, os.O_RDONLY), os.open(os.devnull, os.O_WRONLY)
    os.dup2(dn_r, 0); os.dup2(dn_w, 1); os.dup2(dn_w, 2)
    open(PIDFILE, "w").write(str(os.getpid()))
    play_reply(kind, text)


if __name__ == "__main__":
    main()
