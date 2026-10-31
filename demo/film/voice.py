"""Narration for the demo film: Kokoro af_heart (same setup as django_web_agent's explainer), ducked music, SRT.
Needs a Python with kokoro-onnx, soundfile, numpy, and the model files in ~/.cache/hyperframes/tts:
  <voice-env>/bin/python -I demo/film/voice.py      -> demo/work/narrated.wav, demo/brag.srt
Each line starts at its scene cue and must end before the next cue; a line that runs long is re-spoken faster."""
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

D = Path(__file__).resolve().parent.parent  # demo/
RATE, LENGTH, SPEED = 24000, 40.0, 1.1
# (start s, must end by s, text): starts follow the scene cues in timeline.json
LINES = [
    (0.4, 3.9, "Eight friends. One bill. Who had the T-bone?"),
    (4.3, 9.8, "Snap the bill. Gemini reads every line, and checks it against the total."),
    (10.2, 13.9, "Share one link. No app, no sign-up."),
    (14.4, 19.0, "Everyone taps what they had, and every phone updates live."),
    (19.3, 21.9, "Shared plates split themselves."),
    (22.3, 27.8, "Each person pays their exact share. Mobile money, card, or USDC."),
    (28.2, 31.9, "Money only moves when the host approves."),
    (32.2, 35.9, "Same engine runs the shop counter. Stock updates itself."),
    (36.4, 39.6, "TrackSplit. Everyone pays for what they ate."),
]

cache = Path.home() / ".cache/hyperframes/tts"
k = Kokoro(str(cache / "models/kokoro-v1.0.onnx"), str(cache / "voices/voices-v1.0.bin"))


def say(text, speed):
    s, rate = k.create(text, voice="af_heart", speed=speed, lang="en-us")
    assert rate == RATE
    a = np.flatnonzero(np.abs(s) > 0.003)
    return s[max(0, a[0] - 600):a[-1] + 1200]


def ts(s):
    ms = round(s * 1000)
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


voice = np.zeros(int(RATE * LENGTH), np.float32)
srt = []
for i, (at, until, text) in enumerate(LINES, 1):
    s = say(text, SPEED)
    if len(s) / RATE > until - at:  # too long for its slot: speak faster, capped so it stays natural
        s = say(text, min(1.35, SPEED * len(s) / RATE / (until - at)))
    end = at + len(s) / RATE
    assert end <= until + 0.05, f"line {i} still too long: ends {end:.2f}, slot ends {until}"
    o = int(at * RATE)
    voice[o:o + len(s)] += s
    srt.append(f"{i}\n{ts(at)} --> {ts(end)}\n{text}\n")
    print(f"{i} {at:5.1f}-{end:5.2f}  {text}")

work = D / "work"
sf.write(work / "voice.wav", voice, RATE)
(D / "brag.srt").write_text("\n".join(srt))

# music bed lowered and ducked further while the voice speaks (smoothed so it breathes), then one loudness pass for the mix
duck = "[1:a]aformat=channel_layouts=stereo,asplit[v][sc];[0:a][sc]sidechaincompress=threshold=0.02:ratio=8:attack=40:release=350[m];[m][v]amix=inputs=2:weights=0.4 2.2:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(work / "music.wav"), "-i", str(work / "voice.wav"),
                "-filter_complex", duck, "-ar", "48000", "-c:a", "pcm_s16le", str(work / "narrated.wav")], check=True)
print("ok")
