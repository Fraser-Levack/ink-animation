"""The day clock. One play-through of the song is one day.

Works with or without sound: if the song (or an audio device) is missing the
day still runs on the song's loudness map, or on a gentle made-up curve.
"""

from __future__ import annotations

import json
import math
import time


class SongClock:
    def __init__(self, cfg):
        self.cfg = cfg
        self.duration = 180.0
        self.bpm = 120.0
        self.offset = 0.0
        self.hop = 0.05
        self.energy_map = None
        if cfg.song_map_path.exists():
            m = json.loads(cfg.song_map_path.read_text())
            self.duration, self.bpm = m["duration"], m["bpm"]
            self.offset, self.hop, self.energy_map = m["offset"], m["hop"], m["energy"]

        self.audio = False
        if cfg.music and cfg.song_path.exists():
            try:
                import pygame
                pygame.mixer.init()
                pygame.mixer.music.load(str(cfg.song_path))
                self.audio = True
            except Exception as e:  # no sound card, missing codec, ...
                print(f"[inkcycle] music off: {e}")

        self.now = time.monotonic   # swappable for fast-forward tests
        self.running = False
        self.start = 0.0
        self.day = 0
        self.t = 0.0
        self.energy = 0.35
        self.beat = 0
        self.beat_phase = 0.0
        self.beat_now = False
        self.boil_idx = 0
        self.night = False
        self.surge = False
        self._history = []
        self._last_surge = -99.0

    def begin_day(self):
        self.day += 1
        self.start = self.now()
        self.running = True
        self.beat = 0
        self._history.clear()
        self._last_surge = -99.0
        if self.audio:
            import pygame
            pygame.mixer.music.play()

    def update(self, wall_dt):
        self.beat_now = False
        self.surge = False
        if not self.running:
            # before the first day (the opening): calm, steady boil
            self.t += wall_dt
            self.boil_idx = int(self.t * 6) % 3
            return
        self.t = self.now() - self.start
        if self.t >= self.duration:
            self.begin_day()
            self.t = 0.0

        if self.energy_map:
            i = self.t / self.hop
            k = int(i)
            a = self.energy_map[min(k, len(self.energy_map) - 1)]
            b = self.energy_map[min(k + 1, len(self.energy_map) - 1)]
            e = a + (b - a) * (i - k)
        else:  # no map: a slow rise and fall across the day
            e = 0.25 + 0.6 * math.sin(math.pi * self.t / self.duration) ** 2
        self.energy = e

        period = 60.0 / self.bpm
        bt = (self.t - self.offset) / period
        b = int(math.floor(bt))
        if b != self.beat:
            self.beat = b
            self.beat_now = True
        self.beat_phase = bt - math.floor(bt)
        self.boil_idx = int(math.floor(bt * 2)) % 3      # wobble on eighth notes

        # night: the last stretch of the song
        self.night = self.t > self.duration * 0.86

        # surge: a sharp rise in loudness (a drop)
        self._history.append((self.t, e))
        while self._history and self._history[0][0] < self.t - 2.5:
            self._history.pop(0)
        low = min(h[1] for h in self._history)
        if e - low > 0.28 and self.t - self._last_surge > 20:
            self.surge = True
            self._last_surge = self.t

    def brightness(self):
        """Dim a little at night, brighten again at dawn."""
        if not self.running:
            return 1.0
        x = self.t / self.duration
        if x > 0.86:
            return 1.0 - 0.4 * min(1.0, (x - 0.86) / 0.1)
        if x < 0.04:
            return 0.6 + 0.4 * x / 0.04 if self.day > 1 else 1.0
        return 1.0
