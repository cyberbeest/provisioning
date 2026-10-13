#!/usr/bin/env python3
"""Generate the message-type earcons into sounds/*.wav (stdlib only).

Each is two or three short tones, so the pitch contour tells the type:
  yes          two quick tones, up
  no           two soft tones, down
  problem      harsh low buzz, a tritone apart, three pulses
  success      rising major triple, last one held
  uploaded     fast chirp, up (three steps)
  downloaded   fast chirp, down (three steps)
  question     a flat tone, then a glide that ends high and open
  info         two equal soft bell tones
  collaborate  high-low-high bells: your turn
"""
import math, os, struct, wave

RATE = 44100
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sounds")


def tone(freq, ms, shape="sine", end_freq=None, amp=0.35, decay=False):
    n = int(RATE * ms / 1000)
    out, phase = [], 0.0
    for i in range(n):
        t = i / n
        f = freq if end_freq is None else freq + (end_freq - freq) * t
        phase += 2 * math.pi * f / RATE
        s = math.sin(phase)
        if shape == "square":
            s = 1.0 if s >= 0 else -1.0
            s = 0.6 * s + 0.4 * math.sin(phase)  # softened, less piercing
        elif shape == "triangle":
            s = 2 / math.pi * math.asin(s)
        attack = min(1.0, i / (RATE * 0.006))
        release = min(1.0, (n - i) / (RATE * 0.02))
        env = attack * release * ((1 - t) ** 1.5 if decay else 1.0)
        out.append(amp * env * s)
    return out


def gap(ms):
    return [0.0] * int(RATE * ms / 1000)


LEAD_IN_MS = 400  # the sound card is suspended when idle and swallows the start of a sound


def seq(*parts):
    return gap(LEAD_IN_MS) + [x for p in parts for x in p]


SOUNDS = {
    "yes": seq(tone(523, 90), gap(25), tone(784, 130)),
    "no": seq(tone(392, 130, "triangle", amp=0.3), gap(30), tone(262, 190, "triangle", amp=0.3)),
    "problem": seq(tone(220, 150, "square", amp=0.28), gap(40), tone(311, 150, "square", amp=0.28),
                   gap(40), tone(220, 260, "square", amp=0.28)),
    "success": seq(tone(523, 90), gap(20), tone(659, 90), gap(20), tone(784, 90), gap(20),
                   tone(1047, 320, decay=True)),
    "uploaded": seq(tone(600, 55), gap(10), tone(800, 55), gap(10), tone(1000, 90, decay=True)),
    "downloaded": seq(tone(1000, 55), gap(10), tone(800, 55), gap(10), tone(600, 90, decay=True)),
    "question": seq(tone(440, 130), gap(40), tone(523, 260, end_freq=784)),
    "info": seq(tone(659, 130, amp=0.22, decay=True), gap(60), tone(659, 130, amp=0.22, decay=True)),
    "collaborate": seq(tone(880, 140, decay=True), gap(50), tone(659, 140, decay=True), gap(50),
                       tone(880, 260, decay=True)),
}


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, samples in SOUNDS.items():
        with wave.open(os.path.join(OUT, name + ".wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
            w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, s)) * 32767)) for s in samples))
    print("wrote", ", ".join(SOUNDS))


if __name__ == "__main__":
    main()
