#!/usr/bin/env python3
"""Synthesize an original, royalty-free retro pop backing track (numpy only).

120 BPM, I-V-vi-IV progression, four-on-the-floor drums, bass, warm pads
with sidechain pump, a plucked arpeggio and a little vinyl crackle for a
nostalgic feel. The first bar is an intro (pads, arp, crackle); the beat
drops on bar 2.

    python3 make_music.py -o track.wav --seconds 17
"""

import argparse
import wave

import numpy as np

SR = 44100
BPM = 120
BEAT = 60 / BPM
BAR = 4 * BEAT

# C - G - Am - F, as MIDI notes (root + triad an octave up).
CHORDS = [
    (36, [60, 64, 67]),
    (43, [59, 62, 67]),
    (45, [57, 60, 64]),
    (41, [57, 60, 65]),
]

rng = np.random.default_rng(7)


def hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def t_axis(seconds):
    return np.arange(int(seconds * SR)) / SR


def place(buf, sound, at):
    i = int(at * SR)
    if i >= len(buf):
        return
    j = min(len(buf), i + len(sound))
    buf[i:j] += sound[: j - i]


def soft_saw(freq, t, harmonics=8):
    # Band-limited saw with a gentle roll-off: warm rather than buzzy.
    out = np.zeros_like(t)
    for k in range(1, harmonics + 1):
        out += np.sin(2 * np.pi * freq * k * t) / (k ** 1.4)
    return out


def kick():
    t = t_axis(0.35)
    f = 45 + 95 * np.exp(-t * 28)
    phase = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(phase) * np.exp(-t * 9) * 1.0


def snare():
    t = t_axis(0.25)
    noise = np.diff(rng.standard_normal(len(t) + 1)) * 0.35
    tone = np.sin(2 * np.pi * 190 * t) * 0.5
    return (noise * np.exp(-t * 16) + tone * np.exp(-t * 30)) * 0.55


def hat(open_=False):
    t = t_axis(0.18 if open_ else 0.05)
    noise = np.diff(np.diff(rng.standard_normal(len(t) + 2)))
    return noise * np.exp(-t * (18 if open_ else 70)) * 0.09


def pluck(midi, length=0.3):
    t = t_axis(length)
    return soft_saw(hz(midi), t, 6) * np.exp(-t * 11) * 0.16


def build(seconds):
    n = int(seconds * SR)
    drums = np.zeros(n)
    bass = np.zeros(n)
    pads = np.zeros(n)
    arp = np.zeros(n)
    pump = np.ones(n)

    bars = int(np.ceil(seconds / BAR))
    k, s = kick(), snare()
    for b in range(bars):
        root, triad = CHORDS[b % len(CHORDS)]
        t0 = b * BAR
        intro = b == 0

        # Pads: detuned chord held for the bar.
        t = t_axis(BAR)
        env = np.minimum(1, t / 0.08) * np.minimum(1, (BAR - t) / 0.05)
        chord = sum(soft_saw(hz(m) * d, t, 5) for m in triad for d in (0.997, 1.003))
        place(pads, chord * env * 0.045, t0)

        # Arpeggio in 8ths over the triad (up, then the top note an octave higher).
        pattern = triad + [triad[2] + 5, triad[1] + 12, triad[2], triad[1], triad[0] + 12]
        for i in range(8):
            place(arp, pluck(pattern[i % len(pattern)] + 12), t0 + i * BEAT / 2)

        if intro:
            continue

        for beat in range(4):
            tb = t0 + beat * BEAT
            place(drums, k, tb)
            # Sidechain pump: duck pads/bass right after each kick.
            i = int(tb * SR)
            dur = int(0.3 * SR)
            if i < n:
                j = min(n, i + dur)
                pump[i:j] = np.minimum(pump[i:j], 0.35 + 0.65 * (np.arange(j - i) / dur) ** 0.6)
            if beat in (1, 3):
                place(drums, s, tb)
            place(drums, hat(), tb)
            place(drums, hat(open_=True), tb + BEAT / 2)

        # Bass: octave-bouncing 8ths on the root.
        for i in range(8):
            t = t_axis(BEAT / 2)
            note = root + (12 if i % 2 else 0)
            env = np.minimum(1, t / 0.005) * np.exp(-t * 4)
            place(bass, soft_saw(hz(note), t, 5) * env * 0.33, t0 + i * BEAT / 2)

    mix = drums + (bass + pads) * pump + arp * (0.75 + 0.25 * pump)

    # Vinyl: soft hiss plus sparse crackles.
    crackle = np.zeros(n)
    for at in rng.uniform(0, seconds, int(seconds * 14)):
        place(crackle, rng.standard_normal(30) * np.exp(-np.arange(30) / 6) * rng.uniform(0.02, 0.08), at)
    hiss = np.convolve(rng.standard_normal(n), np.ones(6) / 6, mode="same") * 0.006
    mix += crackle + hiss

    # Slight stereo width from a short delay on the right channel.
    d = int(0.012 * SR)
    left = mix + arp * 0.15
    right = np.concatenate([np.zeros(d), mix[:-d]]) * 0.6 + mix * 0.4
    stereo = np.stack([left, right], axis=1)
    stereo /= np.max(np.abs(stereo)) / 0.89
    return stereo


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--output", default="track.wav")
    ap.add_argument("--seconds", type=float, default=17.0)
    args = ap.parse_args()

    audio = (build(args.seconds) * 32767).astype(np.int16)
    with wave.open(args.output, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(audio.tobytes())
    print(f"wrote {args.output} ({args.seconds:.1f}s, {BPM} BPM)")


if __name__ == "__main__":
    main()
