"""Map a song's loudness and beat so the world can follow it.

    python tools/analyse_song.py [song.mp3] [--bpm 140]

Writes assets/song.json:
    duration   seconds
    bpm        tempo (from the file's tag if present, else --bpm, else 140)
    offset     seconds until the first beat
    hop        seconds per energy sample
    energy     loudness curve, 0..1 (smoothed)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import numpy as np
import pygame

ROOT = Path(__file__).resolve().parent.parent
HOP = 0.05


def read_bpm_tag(path: Path) -> float | None:
    """Read an ID3v2 TBPM frame if present (FL Studio writes one)."""
    data = path.read_bytes()[:65536]
    i = data.find(b"TBPM")
    if i < 0:
        return None
    size = int.from_bytes(data[i + 4:i + 8], "big")
    txt = data[i + 10:i + 10 + size].lstrip(b"\x00\x01\x03").decode("latin-1", "ignore").strip("\x00 ")
    try:
        return float(txt)
    except ValueError:
        return None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    song = Path(args[0]) if args else ROOT / "unknown.mp3"
    bpm = read_bpm_tag(song)
    if "--bpm" in sys.argv:
        bpm = float(sys.argv[sys.argv.index("--bpm") + 1])
    bpm = bpm or 140.0

    pygame.mixer.init(frequency=44100, size=-16, channels=2)
    freq, _, chans = pygame.mixer.get_init()
    samples = pygame.sndarray.array(pygame.mixer.Sound(str(song))).astype(np.float32)
    mono = samples.mean(axis=1) if samples.ndim == 2 else samples
    mono /= 32768.0
    duration = len(mono) / freq

    # loudness curve
    hop = int(freq * HOP)
    n = len(mono) // hop
    rms = np.sqrt((mono[: n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    lo, hi = np.percentile(db, 5), np.percentile(db, 98)
    energy = np.clip((db - lo) / (hi - lo), 0, 1)
    k = 9  # ~0.45 s smoothing
    energy = np.convolve(energy, np.ones(k) / k, mode="same")

    # beat phase: fold onset strength onto the beat period, take the peak
    fh = int(freq * 0.01)
    m = len(mono) // fh
    env = np.sqrt((mono[: m * fh].reshape(m, fh) ** 2).mean(axis=1))
    onset = np.maximum(0, np.diff(env, prepend=env[0]))
    period = 60.0 / bpm
    t = np.arange(m) * 0.01
    bins = 48
    hist = np.bincount(((t % period) / period * bins).astype(int) % bins, weights=onset, minlength=bins)
    offset = float(np.argmax(hist) / bins * period)

    out = {
        "file": song.name,
        "duration": round(duration, 3),
        "bpm": bpm,
        "offset": round(offset, 4),
        "hop": HOP,
        "energy": [round(float(e), 3) for e in energy],
    }
    (ROOT / "assets" / "song.json").write_text(json.dumps(out, separators=(",", ":")))
    print(f"{song.name}: {duration:.1f}s, {bpm:g} bpm, first beat at {offset:.3f}s -> assets/song.json")
    # rough shape, one character per 5 seconds
    step = int(5 / HOP)
    print("energy:", "".join(" .:-=+*#%@"[min(9, int(e * 10))] for e in energy[::step]))


if __name__ == "__main__":
    main()
