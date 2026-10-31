#!/usr/bin/env python3
"""Speak Claude's reply with Piper. Reads the full reply on stdin.

Speaks the <spoken>...</spoken> tag if present, else the first sentences.
Detaches itself so the caller returns at once; a new call stops the old one.
"""
import glob, os, re, shutil, signal, socket, struct, subprocess, sys, threading, time

HOME = os.path.expanduser("~/.local/share/claude-tts")
PIDFILE = os.path.join(HOME, "speaking.pid")
MUTE = os.path.join(HOME, "muted")
VOLFILE = os.path.join(HOME, "volume")  # percent, 100 = full
MAX_CHARS = 220
TINY_SOCK = os.path.join(HOME, "tiny.sock")
TINY_SPEED = 1.3   # TinyTTS speaking rate, 1.0 = its natural pace
LENGTH_SCALE = 0.81  # Piper: below 1.0 speaks faster
BEEP_PAUSE = 1.0  # seconds of silence between the beep and the speech

GERMAN_HINTS = {"der", "die", "das", "und", "ist", "nicht", "ich", "ein", "eine", "mit",
                "für", "auf", "zu", "den", "dem", "wir", "sie", "es", "aber", "auch", "wie"}


def volume_arg():
    try:
        pct = max(0, min(100, int(open(VOLFILE).read().strip())))
    except (OSError, ValueError):
        pct = 100
    return f"--volume={pct * 65536 // 100}"


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


def tiny_node():
    found = shutil.which("node") or next(iter(sorted(glob.glob(os.path.expanduser("~/.config/nvm/versions/node/*/bin/node")))), None)
    return found if found and os.path.exists(os.path.join(HOME, "tiny", "tinytts.onnx")) else None


def tiny_connect():
    """A connection to the resident TinyTTS server, or None."""
    s = socket.socket(socket.AF_UNIX)
    try:
        s.connect(TINY_SOCK)
        return s
    except OSError:
        s.close()
        return None


def tiny_warm_up():
    """Starts the TinyTTS server if it is not running; it needs ~14 s to load, so the reply that
    finds it still loading is spoken by Piper."""
    node = tiny_node()
    if not node:
        return
    if os.path.exists(TINY_SOCK):
        probe = tiny_connect()
        if probe:
            probe.close()
            return
        os.remove(TINY_SOCK)  # left behind by a crashed server
    if os.path.exists(TINY_SOCK + ".starting") and time.time() - os.path.getmtime(TINY_SOCK + ".starting") < 60:
        return
    open(TINY_SOCK + ".starting", "w").close()
    dn = open(os.devnull, "r+b")
    subprocess.Popen([node, os.path.join(HOME, "synth_tiny.js"), "--serve", TINY_SOCK,
                      os.path.join(HOME, "tiny", "tinytts.onnx"), str(TINY_SPEED)],
                     stdin=dn, stdout=dn, stderr=dn, start_new_session=True)


ACRONYM = re.compile(r"\b[A-Z]{2,6}s?\b")
SPOKEN_AS_WORDS = {"OK", "NASA", "RAM", "LAN", "WLAN", "SIM", "PIN", "GUI", "SQL", "USB", "LUKS", "GRUB"}


# Words TinyTTS gets wrong, respelled for its ears; keys are matched case-insensitively as whole words.
RESPELL = {"tuesday": "Tooz day", "tinytts": "Tiny T T S"}
RESPELL_RE = re.compile(r"\b(" + "|".join(RESPELL) + r")\b", re.I)


def spell_acronyms(text):
    """TinyTTS cannot read acronyms: "TTS" becomes "T T S" (plural s dropped, it would be spelled too)."""
    def spell(m):
        word = m.group(0)
        if word in SPOKEN_AS_WORDS:
            return word
        return " ".join(word.rstrip("s")) + ("'s" if word.endswith("s") else "")
    text = RESPELL_RE.sub(lambda m: RESPELL[m.group(0).lower()], text)
    return ACRONYM.sub(spell, text)


ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
        "sixteen seventeen eighteen nineteen").split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
SCALES = ((10**9, "billion"), (10**6, "million"), (10**3, "thousand"))
NUMBER = re.compile(r"(?<![\w.])-?\d+(?:[.,]\d+)*%?(?!\d)")


def number_words(n):
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + (" " + ONES[n % 10] if n % 10 else "")
    if n < 1000:
        return ONES[n // 100] + " hundred" + (" " + number_words(n % 100) if n % 100 else "")
    for size, name in SCALES:
        if n >= size:
            return number_words(n // size) + " " + name + (" " + number_words(n % size) if n % size else "")


def say_number(m):
    """TinyTTS has no number reading and makes noise of digits: "42%" -> "forty two percent"."""
    token = m.group(0)
    percent = token.endswith("%")
    token = token.rstrip("%")
    neg = token.startswith("-")
    token = token.lstrip("-")
    if re.fullmatch(r"\d+(?:\.\d+){2,}", token):      # 192.168.1.1: each part on its own
        out = " dot ".join(number_words(int(p)) for p in token.split("."))
    elif re.fullmatch(r"\d{1,3}(?:,\d{3})+", token):  # 1,234,567
        out = number_words(int(token.replace(",", "")))
    elif re.fullmatch(r"\d+\.\d+", token):           # 3.14: digits after the point one by one
        whole, frac = token.split(".")
        out = number_words(int(whole)) + " point " + " ".join(ONES[int(d)] for d in frac)
    elif re.fullmatch(r"\d+", token):
        n = int(token)
        if len(token) == 4 and 1900 <= n <= 2099 and n % 100:   # years: "twenty twenty six"
            out = number_words(n // 100) + " " + ("oh " + ONES[n % 100] if n % 100 < 10 else number_words(n % 100))
        elif len(token) > 1 and token[0] == "0":                 # 007, 0123: digit by digit
            out = " ".join(ONES[int(d)] for d in token)
        elif n >= 10**12:
            out = " ".join(ONES[int(d)] for d in token)
        else:
            out = number_words(n)
    else:
        out = " ".join(ONES[int(d)] if d.isdigit() else d for d in token)
    after = m.string[m.end():m.end() + 1]
    return ("minus " if neg else "") + out + (" percent" if percent else "") + (" " if after.isalpha() else "")


def spell_numbers(text):
    return NUMBER.sub(say_number, text)


class Synth:
    """The synthesizer feeding play_reply: stdout to read frames from, kill() to give up."""
    def __init__(self, voice, sentences):
        payload = ("\n".join(sentences) + "\n").encode()
        self.sock = tiny_connect() if voice == "en_GB-alan-medium" else None
        if self.sock:
            self.sock.sendall(spell_acronyms(spell_numbers(payload.decode())).encode())
            self.sock.shutdown(socket.SHUT_WR)
            self.stdout = self.sock.makefile("rb")
            log("synth: TinyTTS")
        else:
            self.proc = subprocess.Popen([os.path.join(HOME, "venv/bin/python"), os.path.join(HOME, "synth.py"),
                                          os.path.join(HOME, voice + ".onnx"), str(LENGTH_SCALE)],
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            self.proc.stdin.write(payload)
            self.proc.stdin.close()
            self.stdout = self.proc.stdout
            log("synth: Piper")

    def kill(self):
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.sock.close()
        elif self.proc.poll() is None:
            self.proc.kill()


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
    sentences = [x for x in SENTENCE_SPLIT.split(text) if x.strip()]
    chars = [len(x) for x in sentences]
    synth = Synth(voice_for(text), sentences)

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

    def abort():
        synth.kill()

    while time.time() - t0 < 90:  # the limit is only a safety net
        with cond:
            if can_start(frames, chars, state["done"]):
                break
            cond.wait(0.1)
        if capturing():
            abort()
            return
    path = os.path.join(HOME, "sounds", kind + ".wav")
    if os.path.exists(path):  # the beep comes just before the speech, not while Piper is still working
        done = subprocess.run(["paplay", volume_arg(), path], capture_output=True, text=True)
        log(f"earcon {kind}: rc={done.returncode} {done.stderr.strip()}")
        time.sleep(BEEP_PAUSE)
    started = time.time() - t0

    play = subprocess.Popen(["paplay", volume_arg(), "--raw", "--format=s16le", f"--rate={state['rate']}", "--channels=1"],
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
        if not os.path.exists(MUTE):
            tiny_warm_up()  # a prompt was just sent: have TinyTTS loaded by the time the reply comes
        return
    if "--volume" in sys.argv:
        i = sys.argv.index("--volume")
        try:
            pct = max(0, min(100, int(sys.argv[i + 1])))
        except (IndexError, ValueError):
            print("usage: --volume 0-100"); return
        open(VOLFILE, "w").write(str(pct)); print(f"volume {pct}%")
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
