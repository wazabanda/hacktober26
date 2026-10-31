"""Synthesize the film's soundtrack from timeline.json (numpy only) -> demo/work/music.wav.

120 BPM in C. Every hit (kick, plucks, taps, chimes, whooshes) sits on the same beat grid as the cuts.
"""

import json
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
TL = json.loads((HERE / "timeline.json").read_text())
SR, DUR, BPM = 48000, TL["duration"], TL["bpm"]
BEAT = 60 / BPM
N = int(SR * DUR)
L = np.zeros(N)
R = np.zeros(N)
rng = np.random.default_rng(7)


def hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def add(sig, t, gain=1.0, pan=0.0):
    i = int(t * SR)
    if i >= N:
        return
    sig = sig[: N - i] * gain
    L[i:i + len(sig)] += sig * np.sqrt(0.5 * (1 - pan))
    R[i:i + len(sig)] += sig * np.sqrt(0.5 * (1 + pan))


def env(n, a, d, sustain=0.0, curve=6.0):
    t = np.arange(n) / SR
    e = np.minimum(1, t / max(a, 1e-4)) * (sustain + (1 - sustain) * np.exp(-curve * np.maximum(0, t - a) / max(d, 1e-4)))
    return e


def lowpass(x, cutoff):
    a = np.exp(-2 * np.pi * cutoff / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i, v in enumerate(x):  # ponytail: plain loop, fine for a 40 s mix
        acc = (1 - a) * v + a * acc
        y[i] = acc
    return y


def tone(f, dur, harmonics=((1, 1.0),), a=0.01, d=0.3, sustain=0.0, curve=6.0, detune=0.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    s = sum(w * np.sin(2 * np.pi * f * k * (1 + detune) * t) for k, w in harmonics)
    return s * env(n, a, d, sustain, curve)


# ---------- harmony ----------
C, G, Am, F, Em = [48, 52, 55, 60], [43, 50, 55, 59], [45, 52, 57, 60], [41, 48, 53, 57], [40, 47, 52, 55]
bars = [Am, F, C, G, Am, F, C, G, Am, F, C, G, Am, F, C, G, F, G, C, C]  # 20 bars x 2 s = 40 s
BAR = 4 * BEAT
groove_from, hats_from, claps_from, outro = TL["scenes"]["snap"], TL["scenes"]["share"], TL["scenes"]["live"], TL["scenes"]["outro"]

for b, chord in enumerate(bars):
    t0 = b * BAR
    last = b == len(bars) - 1
    # pad: soft detuned stack, long attack
    for m in chord[1:]:
        for det, pan in ((-0.002, -0.4), (0.002, 0.4)):
            add(tone(hz(m + 12), BAR + (2.5 if last else 0.15), ((1, 1), (2, .25), (3, .08)), a=.35, d=BAR, sustain=.75, curve=1.5, detune=det),
                t0, .045, pan)
    if t0 >= groove_from and t0 < outro + BAR:
        # bass: root on 1 and the "and" of 2, 3
        for off, ln in ((0, .45), (1.5 * BEAT, .2), (2 * BEAT, .45), (3.5 * BEAT, .2)):
            add(tone(hz(chord[0] - 12 + 12), ln, ((1, 1), (2, .3)), a=.005, d=ln, curve=4), t0 + off, .16)
        # pluck arpeggio in 8ths
        arp = [chord[1] + 24, chord[2] + 24, chord[3] + 24, chord[2] + 24] * 2
        for k, m in enumerate(arp):
            add(tone(hz(m), .35, ((1, 1), (2, .4), (3, .15)), a=.002, d=.25, curve=7), t0 + k * BEAT / 2, .035, -.3 + .6 * (k % 2))

# ---------- drums ----------
kick_n = int(.35 * SR)
kt = np.arange(kick_n) / SR
kick = np.sin(2 * np.pi * (45 * kt + 75 / 18 * (1 - np.exp(-18 * kt)))) * np.exp(-9 * kt)
hat = lowpass(rng.standard_normal(int(.05 * SR)), 9000) * env(int(.05 * SR), .001, .03, curve=8)
hat = hat - lowpass(hat, 6000)
clap = lowpass(rng.standard_normal(int(.18 * SR)), 3500) * env(int(.18 * SR), .002, .12, curve=7)
kick_times = []
for i in range(int(DUR / BEAT)):
    t = i * BEAT
    if groove_from <= t < outro + BAR * 1.0:
        add(kick, t, .5)
        kick_times.append(t)
        if t >= hats_from:
            add(hat, t + BEAT / 2, .16, .3)
        if t >= claps_from and i % 2 == 1:
            add(clap, t, .14, -.1)

# sidechain-style duck on everything so far (pads breathe with the kick)
duck = np.ones(N)
for t in kick_times:
    i = int(t * SR)
    n = min(int(.3 * SR), N - i)
    duck[i:i + n] = np.minimum(duck[i:i + n], 1 - .45 * np.exp(-np.arange(n) / SR / .09))
L *= duck
R *= duck
L = L.copy()
R = R.copy()

# ---------- sound effects, in key, under the music ----------
for _, phone, t, *_ in TL["taps"]:  # soft tick on each tap (C6 + G6)
    add(tone(hz(84), .09, ((1, 1), (1.5, .3)), a=.001, d=.05, curve=9), t, .06, (phone - 1) * .4)
for t in TL["updates"]:  # live update: two-note blip E6 -> G6
    add(tone(hz(88), .12, ((1, 1),), a=.003, d=.1, curve=6), t, .05)
    add(tone(hz(91), .18, ((1, 1),), a=.003, d=.15, curve=6), t + BEAT / 4, .05)
for t in TL["chimes"]:  # payment: bell arpeggio C6 E6 G6 C7
    for k, m in enumerate((84, 88, 91, 96)):
        add(tone(hz(m), 1.2, ((1, 1), (2.76, .25), (5.4, .08)), a=.002, d=1.0, curve=5), t + k * BEAT / 8, .05 - k * .006, -.2 + .15 * k)
cuts = [v for k, v in TL["scenes"].items() if v > 0]
for t in cuts:  # whoosh into each cut: rising filtered noise
    n = int(.5 * SR)
    noise = rng.standard_normal(n)
    sw = lowpass(noise, 2500) * np.linspace(0, 1, n) ** 2.5
    add(sw, t - .5, .05)
# shutter on the snap
sh = lowpass(rng.standard_normal(int(.06 * SR)), 6000) * env(int(.06 * SR), .001, .03, curve=10)
add(sh, 4.95, .18)
# stock ticking down 12 -> 9
for t in (34.0, 34.5, 35.0):
    add(tone(hz(79), .1, ((1, 1),), a=.002, d=.07, curve=8), t, .045, .3)

# ---------- master ----------
mix = np.stack([L, R], axis=1)
fade = np.ones(N)
fade[: int(.03 * SR)] = np.linspace(0, 1, int(.03 * SR))
tail = int(1.8 * SR)
fade[-tail:] = np.linspace(1, 0, tail) ** 1.5
mix *= fade[:, None]
mix = np.tanh(mix * 1.6) / np.tanh(1.6)
mix *= 0.73 / np.max(np.abs(mix))  # about -14 LUFS
pcm = (mix * 32767).astype(np.int16)
out = HERE.parent / "work" / "music.wav"
with wave.open(str(out), "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(pcm.tobytes())
print("wrote", out, f"{DUR}s")
