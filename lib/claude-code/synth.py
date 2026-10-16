#!/usr/bin/env python3
"""Piper helper, run with the venv's python: synth.py MODEL LENGTH_SCALE.

Reads one sentence per line on stdin. Writes to stdout: the sample rate (u32), then for
each sentence a frame: byte count (u32), seconds spent synthesizing it (f32), raw s16le PCM.
speak.py uses the timings to decide when playback can start without running dry.
"""
import struct, sys, time


def name_process(name="claude-voice"):
    """Shows up as `claude-voice` instead of `python` in /proc comm, so the panel's CPU list can say "Claude's voice"."""
    try:
        import ctypes
        ctypes.CDLL(None).prctl(15, name.encode(), 0, 0, 0)   # PR_SET_NAME
    except (OSError, AttributeError):
        pass


name_process()

from piper import PiperVoice, SynthesisConfig

voice = PiperVoice.load(sys.argv[1])
config = SynthesisConfig(length_scale=float(sys.argv[2]))
out = sys.stdout.buffer
out.write(struct.pack("<I", voice.config.sample_rate))
out.flush()
for line in sys.stdin:
    sentence = line.strip()
    if not sentence:
        continue
    started = time.time()
    pcm = b"".join(chunk.audio_int16_bytes for chunk in voice.synthesize(sentence, syn_config=config))
    out.write(struct.pack("<If", len(pcm), time.time() - started) + pcm)
    out.flush()
