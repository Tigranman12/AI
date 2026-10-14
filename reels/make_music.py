#!/usr/bin/env python3
"""Synthesize an original, royalty-free baroque-pop backing track (numpy only).

Pop drums and bass under baroque colours: a two-choir harpsichord playing
running arpeggios, a string section with vibrato, and a violin melody over
Pachelbel's Canon progression. The mix gets hall reverb, tape-style
saturation and a little vinyl crackle for a warm, nostalgic sound.

Structure (in bars): 3-bar intro (harpsichord + strings, snare roll into
the drop), 8-bar verse, chorus with the violin melody until the last
3 bars, then a final ringing chord.

    python3 make_music.py -o track.wav --seconds 45.5 --bpm 128
"""

import argparse
import wave
from functools import lru_cache

import numpy as np

SR = 44100

# Pachelbel's Canon: C G Am Em F C F G. (bass root, chord tones)
CHORDS = [
    (36, [60, 64, 67]),
    (43, [59, 62, 67]),
    (45, [57, 60, 64]),
    (40, [55, 59, 64]),
    (41, [57, 60, 65]),
    (36, [55, 60, 64]),
    (41, [57, 60, 65]),
    (43, [59, 62, 67]),
]
FINAL = (36, [55, 60, 64, 67])

# Violin melody for the chorus: two half notes per bar over the 8 chords.
MELODY = [(79, 76), (74, 71), (72, 76), (71, 67), (69, 72), (67, 76), (77, 81), (79, 74)]

INTRO_BARS = 3
VERSE_BARS = 8
OUTRO_BARS = 3

rng = np.random.default_rng(7)


def hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def t_axis(seconds):
    return np.arange(int(seconds * SR)) / SR


def place(buf, sound, at):
    i = int(at * SR)
    if i >= len(buf) or i < 0:
        return
    j = min(len(buf), i + len(sound))
    buf[i:j] += sound[: j - i]


def soft_saw(freq, t, harmonics=8, rolloff=1.4, vibrato=None):
    phase = 2 * np.pi * freq * t
    if vibrato is not None:
        phase = 2 * np.pi * np.cumsum(freq * vibrato) / SR
    out = np.zeros_like(t)
    for k in range(1, harmonics + 1):
        out += np.sin(k * phase) / (k ** rolloff)
    return out


# --- instruments -----------------------------------------------------------

@lru_cache(maxsize=None)
def harpsichord(midi):
    """Two plucked choirs (8' and 4'), bright attack whose upper harmonics die first."""
    t = t_axis(1.4)
    out = np.zeros_like(t)
    for choir, (shift, detune, gain) in enumerate(((0, 1.0, 1.0), (12, 1.0015, 0.45))):
        f = hz(midi + shift) * detune
        for k in range(1, 22):
            if f * k > SR / 2.2:
                break
            out += gain * np.sin(2 * np.pi * f * k * t + choir) * np.exp(-t * (2.2 + 0.9 * k)) / k ** 0.75
    click = rng.standard_normal(len(t)) * np.exp(-t * 400) * 0.25
    return (out + click) * 0.075


def strings(notes, seconds, gain=0.03):
    """Section of three detuned voices per note with vibrato and a slow bow attack."""
    t = t_axis(seconds)
    env = np.minimum(1, t / 0.35) * np.minimum(1, (seconds - t) / 0.25)
    out = np.zeros_like(t)
    for m in notes:
        for v, det in enumerate((0.996, 1.0, 1.004)):
            vib = 1 + 0.004 * np.sin(2 * np.pi * (5.2 + 0.4 * v) * t + v)
            out += soft_saw(hz(m) * det, t, 12, 1.25, vib)
    return out * env * gain


def violin(midi, seconds):
    t = t_axis(seconds)
    depth = 0.007 * np.minimum(1, t / 0.4)  # vibrato blooms after the attack
    vib = 1 + depth * np.sin(2 * np.pi * 5.8 * t)
    env = np.minimum(1, t / 0.07) * np.minimum(1, (seconds - t) / 0.12) * (1 - 0.15 * t / seconds)
    return soft_saw(hz(midi), t, 16, 1.1, vib) * env * 0.075


def kick():
    t = t_axis(0.35)
    f = 45 + 95 * np.exp(-t * 28)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)


def snare(gain=0.55):
    t = t_axis(0.25)
    noise = np.diff(rng.standard_normal(len(t) + 1)) * 0.35
    tone = np.sin(2 * np.pi * 190 * t) * 0.5
    return (noise * np.exp(-t * 16) + tone * np.exp(-t * 30)) * gain


def hat(open_=False):
    t = t_axis(0.18 if open_ else 0.05)
    noise = np.diff(np.diff(rng.standard_normal(len(t) + 2)))
    return noise * np.exp(-t * (18 if open_ else 70)) * 0.06


def cymbal():
    t = t_axis(2.5)
    noise = np.diff(np.diff(rng.standard_normal(len(t) + 2)))
    return noise * np.exp(-t * 1.6) * 0.08


# --- effects ---------------------------------------------------------------

def fft_convolve(x, ir):
    size = 1 << int(np.ceil(np.log2(len(x) + len(ir))))
    y = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)
    return y[: len(x)]


def hall_ir(seed, seconds=2.4):
    r = np.random.default_rng(seed)
    t = t_axis(seconds)
    ir = r.standard_normal(len(t)) * np.exp(-t * 2.9)
    ir = np.convolve(ir, np.ones(4) / 4, mode="same")  # darken the tail
    ir[: int(0.02 * SR)] = 0  # pre-delay
    return ir / np.sqrt(np.sum(ir ** 2))


def saturate(x, drive=1.8):
    return np.tanh(drive * x) / np.tanh(drive)


# --- arrangement -----------------------------------------------------------

def build(seconds, bpm):
    beat = 60 / bpm
    bar = 4 * beat
    n = int(seconds * SR)
    drums, bass, pads, harp, lead = (np.zeros(n) for _ in range(5))
    pump = np.ones(n)

    total_bars = int(np.ceil(seconds / bar))
    final_bar = max(INTRO_BARS + 1, total_bars - OUTRO_BARS)
    chorus_start = INTRO_BARS + VERSE_BARS
    k = kick()

    for b in range(final_bar):
        root, triad = CHORDS[b % len(CHORDS)]
        t0 = b * bar
        intro = b < INTRO_BARS
        chorus = b >= chorus_start

        # Strings: chord plus a cello an octave under the root.
        place(pads, strings(triad, bar + 0.2, 0.026 if intro else 0.032), t0)
        place(pads, strings([root + 12], bar + 0.2, 0.03), t0)

        # Harpsichord: 8ths in intro/verse, running 16ths in the chorus.
        pattern = [triad[0], triad[1], triad[2], triad[0] + 12, triad[2], triad[1], triad[0] + 12, triad[1] + 12]
        steps = 16 if chorus else 8
        for i in range(steps):
            note = pattern[i % len(pattern)] + 12
            place(harp, harpsichord(note), t0 + i * bar / steps)

        if chorus:
            m1, m2 = MELODY[(b - chorus_start) % len(MELODY)]
            place(lead, violin(m1, 2 * beat), t0)
            place(lead, violin(m2, 2 * beat), t0 + 2 * beat)
            if b == chorus_start:
                place(drums, cymbal(), t0)

        if intro:
            if b == INTRO_BARS - 1:  # snare roll into the drop
                for i in range(8):
                    place(drums, snare(0.15 + 0.05 * i), t0 + 2 * beat + i * beat / 4)
            continue

        for bt in range(4):
            tb = t0 + bt * beat
            place(drums, k, tb)
            i, dur = int(tb * SR), int(0.3 * SR)
            if i < n:
                j = min(n, i + dur)
                pump[i:j] = np.minimum(pump[i:j], 0.4 + 0.6 * (np.arange(j - i) / dur) ** 0.6)
            if bt in (1, 3):
                place(drums, snare(0.62 if chorus else 0.55), tb)
            place(drums, hat(), tb)
            place(drums, hat(open_=True), tb + beat / 2)
            if chorus:
                place(drums, hat(), tb + beat / 4)
                place(drums, hat(), tb + 3 * beat / 4)

        for i in range(8):
            t = t_axis(beat / 2)
            note = root + (12 if i % 2 else 0)
            env = np.minimum(1, t / 0.005) * np.exp(-t * 4)
            place(bass, soft_saw(hz(note), t, 6) * env * 0.32, t0 + i * beat / 2)

    # Final chord: rolled harpsichord, held strings and a last kick + cymbal.
    t0 = final_bar * bar
    root, chord = FINAL
    ring = seconds - t0
    place(drums, k, t0)
    place(drums, cymbal(), t0)
    place(bass, soft_saw(hz(root), t_axis(ring), 6) * np.exp(-t_axis(ring) * 0.8) * 0.3, t0)
    place(pads, strings(chord + [root + 12], ring, 0.03), t0)
    for i, m in enumerate(chord + [chord[0] + 12, chord[2] + 12]):
        place(harp, harpsichord(m + 12), t0 + i * 0.045)
    place(lead, violin(84, min(ring, 3 * beat)), t0)

    dry = drums + (bass + pads) * pump + harp * (0.8 + 0.2 * pump) + lead

    # Hall reverb, mostly on the harpsichord, strings and violin.
    send = pads * 0.9 + harp * 0.8 + lead * 1.0 + drums * 0.12
    left = dry + 0.32 * fft_convolve(send, hall_ir(1))
    right = dry + 0.32 * fft_convolve(send, hall_ir(2))
    d = int(0.011 * SR)
    right = np.concatenate([np.zeros(d), right[:-d]]) * 0.35 + right * 0.65

    stereo = np.stack([left, right], axis=1)
    stereo /= np.max(np.abs(stereo))
    stereo = saturate(stereo)

    # Vinyl: soft hiss plus sparse crackles, added after saturation.
    for ch in range(2):
        crackle = np.zeros(n)
        for at in rng.uniform(0, seconds, int(seconds * 12)):
            place(crackle, rng.standard_normal(30) * np.exp(-np.arange(30) / 6) * rng.uniform(0.02, 0.07), at)
        hiss = np.convolve(rng.standard_normal(n), np.ones(6) / 6, mode="same") * 0.005
        stereo[:, ch] += crackle + hiss

    # Short fade so the reverb tail doesn't click at the end.
    tail = int(0.4 * SR)
    stereo[-tail:] *= np.linspace(1, 0, tail)[:, None]
    stereo /= np.max(np.abs(stereo)) / 0.89
    return stereo


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--output", default="track.wav")
    ap.add_argument("--seconds", type=float, default=45.5)
    ap.add_argument("--bpm", type=float, default=128)
    args = ap.parse_args()

    audio = (build(args.seconds, args.bpm) * 32767).astype(np.int16)
    with wave.open(args.output, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(audio.tobytes())
    print(f"wrote {args.output} ({args.seconds:.1f}s, {args.bpm:g} BPM)")


if __name__ == "__main__":
    main()
