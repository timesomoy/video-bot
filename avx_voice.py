"""
avx_voice.py - make the narrator sound deeper.

Why the old voice was not deep: `voice-lab` picked the voice whose pitch was CLOSEST to the reference video's speaker
(median ~176 Hz, a fairly high voice), which selected en-US-GuyNeural with +9 Hz (~180 Hz). A deep narrator sits around
100-125 Hz. This module does two things:

  1. picks a naturally deep base voice and lowers its pitch a little in the TTS request, and
  2. post-processes each scene with ffmpeg: a small pitch/formant drop (asetrate + atempo, so duration is unchanged and the
     subtitle timings stay exact), chest-warmth EQ, de-harshing and gentle compression.

Depth levels:  0 natural | 1 warm | 2 deep (default) | 3 very deep
Measure the result on any file:   python avx_voice.py measure voice.mp3
"""
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_DEPTH = 2
# measured with analyze_voice(): median f0 of each voice speaking the same sentence at +0Hz
DEEP_VOICES = ["en-US-EricNeural", "en-US-ChristopherNeural", "en-US-AndrewNeural", "en-US-BrianNeural", "en-US-SteffanNeural"]
# level: (tts pitch Hz offset, post pitch ratio, low boost dB, 220Hz body dB, presence cut dB, treble cut dB, makeup dB)
LEVELS = {
    0: (0, 1.00, 0.0, 0.0, 0.0, 0.0, 0.0),
    1: (-6, 0.97, 2.5, 1.0, -1.0, -1.5, 2.0),
    2: (-12, 0.93, 4.0, 2.0, -2.0, -3.0, 3.0),
    3: (-20, 0.88, 5.5, 2.5, -3.0, -4.5, 4.0),
}
LEVEL_NAMES = {0: "natural", 1: "warm", 2: "deep", 3: "very deep"}


def clamp_depth(v):
    try:
        return max(0, min(3, int(v)))
    except (TypeError, ValueError):
        return DEFAULT_DEPTH


def tts_pitch(level):
    """edge-tts pitch string for this depth level, e.g. '-12Hz'."""
    return f"{LEVELS[clamp_depth(level)][0]:+d}Hz"


def filter_chain(level, sr=24000):
    lvl = LEVELS[clamp_depth(level)]
    _, ratio, low, body, pres, treb, makeup = lvl
    parts = []
    if ratio != 1.0:
        parts += [f"asetrate={int(sr * ratio)}", f"aresample={sr}", f"atempo={1 / ratio:.5f}"]   # lower pitch+formants, same length
    parts.append("highpass=f=55")
    if low:
        parts.append(f"equalizer=f=110:t=q:w=1.0:g={low}")
    if body:
        parts.append(f"equalizer=f=230:t=q:w=1.2:g={body}")
    if pres:
        parts.append(f"equalizer=f=3400:t=q:w=1.4:g={pres}")
    if treb:
        parts.append(f"treble=g={treb}:f=7000")
    if makeup:
        parts.append(f"acompressor=threshold=-21dB:ratio=3:attack=12:release=140:makeup={makeup}")
    parts.append("alimiter=limit=0.95")
    return ",".join(parts)


def deepen(src, dst, level=DEFAULT_DEPTH, sr=24000):
    """src (mp3/wav) -> dst (wav, mono). Same duration as src (within a few ms). Level 0 only converts."""
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-ac", "1", "-ar", str(sr), "-af", filter_chain(level, sr), str(dst)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("voice processing failed: " + r.stderr[-400:])
    return Path(dst)


def f0_yin(path, sr=16000, fmin=60.0, fmax=330.0, thresh=0.12):
    """Median fundamental frequency (Hz) with a YIN-style estimator (cumulative-mean-normalised difference function).
    Much less prone to octave errors than plain autocorrelation. Returns (median, p25, p75, voiced_frames)."""
    import numpy as np
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"], capture_output=True)
    x = np.frombuffer(r.stdout, np.float32).astype(np.float64)
    if len(x) < sr:
        return 0.0, 0.0, 0.0, 0
    x = x / (np.percentile(np.abs(x), 99.5) + 1e-9)
    n, hop = int(0.045 * sr), int(0.010 * sr)
    tmin, tmax = int(sr / fmax), int(sr / fmin)
    out = []
    for i in range(0, len(x) - n - tmax, hop):
        fr = x[i:i + n + tmax]
        if np.sqrt(np.mean(fr[:n] ** 2)) < 0.06:
            continue
        d = np.empty(tmax + 1)
        d[0] = 0
        a = fr[:n]
        for t in range(1, tmax + 1):
            diff = a - fr[t:t + n]
            d[t] = np.dot(diff, diff)
        cm = np.cumsum(d[1:]) / np.arange(1, tmax + 1)
        dn = np.ones(tmax + 1)
        dn[1:] = d[1:] / (cm + 1e-12)
        t = tmin
        while t < tmax and dn[t] > thresh:
            t += 1
        if t >= tmax:
            continue
        while t + 1 < tmax and dn[t + 1] < dn[t]:
            t += 1
        if 0 < t < tmax:
            y0, y1, y2 = dn[t - 1], dn[t], dn[t + 1]
            den = (y0 - 2 * y1 + y2)
            t = t + (0.5 * (y0 - y2) / den if abs(den) > 1e-12 else 0)
        out.append(sr / t)
    if not out:
        return 0.0, 0.0, 0.0, 0
    o = np.array(out)
    return float(np.median(o)), float(np.percentile(o, 25)), float(np.percentile(o, 75)), len(o)


def spectral_stats(path, sr=16000):
    """(low_share, centroid_hz): share of energy below 250 Hz, and the spectral centroid of the speech."""
    import numpy as np
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"], capture_output=True)
    x = np.frombuffer(r.stdout, np.float32)
    n = 2048
    keep = [x[i:i + n] for i in range(0, len(x) - n, n // 2) if float(np.sqrt(np.mean(x[i:i + n] ** 2))) > 0.02 * (np.abs(x).max() + 1e-9) * 3]
    if not keep:
        return 0.0, 0.0
    P = np.mean([np.abs(np.fft.rfft(k * np.hanning(n))) ** 2 for k in keep], axis=0)
    f = np.fft.rfftfreq(n, 1 / sr)
    return float(P[(f >= 60) & (f < 250)].sum() / P[(f >= 60) & (f < 5000)].sum()), float((f[(f >= 60) & (f < 5000)] * P[(f >= 60) & (f < 5000)]).sum() / P[(f >= 60) & (f < 5000)].sum())


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "measure":
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import autovideo as av
        m, p25, p75, nv = f0_yin(sys.argv[2])
        lo, c = spectral_stats(sys.argv[2])
        print(f"median pitch {m:.1f} Hz (p25 {p25:.0f} / p75 {p75:.0f}, {nv} voiced frames) | low-band (60-250 Hz) share {lo * 100:.1f}% | spectral centroid {c:.0f} Hz")
    else:
        print(__doc__)
