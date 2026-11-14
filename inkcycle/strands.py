"""Loose ink: short worms of line that drift on currents until something eats them.

All strands live in numpy arrays so a few hundred of them stay cheap on a Pi.
Ink is measured in sheet pixels; a strand holds seg * (K - 1) of it.
"""

from __future__ import annotations

import math

import numpy as np
import pygame

from .forms import resample
from .render import draw_polyline


class StrandPool:
    def __init__(self, cfg, size, scale):
        self.cfg = cfg
        self.W, self.H = size
        self.scale = scale                     # screen px per ink px
        self.K = cfg.strand_points
        self.speed_unit = self.H / 1080.0
        cap = 256
        self.P = np.zeros((cap, self.K, 2), np.float32)
        self.seg = np.zeros(cap, np.float32)
        self.head = np.zeros(cap, np.float32)
        self.vmul = np.ones(cap, np.float32)
        self.boost = np.zeros(cap, np.float32)   # temporary extra speed (shockwaves)
        self.target = np.full(cap, -1, np.int32)
        self.color = np.full((cap, 3), 255, np.uint8)
        self.alive = np.zeros(cap, bool)
        self.rng = np.random.default_rng()

    # ------------------------------------------------------------ bookkeeping
    def _grow(self):
        cap = len(self.alive) * 2
        def g(a, fill=0):
            out = np.full((cap,) + a.shape[1:], fill, a.dtype)
            out[: len(a)] = a
            return out
        self.P = g(self.P); self.seg = g(self.seg); self.head = g(self.head)
        self.vmul = g(self.vmul, 1); self.boost = g(self.boost); self.target = g(self.target, -1)
        self.color = g(self.color, 255); self.alive = g(self.alive, False)

    def total_ink(self) -> float:
        return float(self.seg[self.alive].sum() * (self.K - 1))

    def count(self) -> int:
        return int(self.alive.sum())

    def add(self, screen_pts, ink, heading=None, target=-1, color=None, boost=0.0):
        """Add strands carrying `ink`, shaped like the polyline `screen_pts`.
        Long pieces are split so no strand is longer than cfg.strand_chunk."""
        n = max(1, math.ceil(ink / self.cfg.strand_chunk))
        pts = np.asarray(screen_pts, np.float32)
        pieces = resample(pts, n * (self.K - 1) + 1)
        for i in range(n):
            free = np.flatnonzero(~self.alive)
            if not len(free):
                self._grow()
                free = np.flatnonzero(~self.alive)
            j = free[0]
            body = pieces[i * (self.K - 1): (i + 1) * (self.K - 1) + 1][::-1]  # head first
            self.P[j] = body
            self.seg[j] = ink / n / (self.K - 1)
            d = body[0] - body[1]
            self.head[j] = heading if heading is not None else (
                math.atan2(d[1], d[0]) if np.any(d) else self.rng.uniform(0, 2 * math.pi))
            self.vmul[j] = self.rng.uniform(0.6, 1.4)
            self.boost[j] = boost
            self.target[j] = target
            self.color[j] = color if color is not None else (255, 255, 255)
            self.alive[j] = True

    # ------------------------------------------------------------ simulation
    def flow(self, x, y, t):
        """A slowly changing swirl, as an angle. It is the curl of a smooth
        potential, so it has no sinks: ink circulates instead of piling up."""
        sx, sy = x / self.H * 2.0, y / self.H * 2.0
        a = 1.7 * sx + t * 0.05
        b = 2.3 * sy - t * 0.04
        c = 1.1 * (sx + sy) + t * 0.03
        d = 2.9 * sx - 1.9 * sy + t * 0.02
        dpdx = 1.7 * np.cos(a) * np.cos(b) + 0.66 * np.cos(c) - 1.45 * np.sin(d)
        dpdy = -2.3 * np.sin(a) * np.sin(b) + 0.66 * np.cos(c) + 0.95 * np.sin(d)
        return np.arctan2(-dpdx, dpdy)

    def update(self, dt, t, energy, creatures_by_id, sink):
        """Move everything. `sink(id, ink)` credits a creature with swallowed ink."""
        idx = np.flatnonzero(self.alive)
        if not len(idx):
            return
        cfg = self.cfg
        P = self.P[idx]
        hx, hy = P[:, 0, 0], P[:, 0, 1]
        h = self.head[idx]
        tgt = self.target[idx]

        # drop targets that no longer exist
        ids = np.unique(tgt[tgt >= 0])
        tx = np.zeros(len(idx), np.float32); ty = np.zeros(len(idx), np.float32)
        tr = np.zeros(len(idx), np.float32)
        for cid in ids:
            m = tgt == cid
            c = creatures_by_id.get(int(cid))
            if c is None or not c.accepts_ink():
                tgt[m] = -1
            else:
                tx[m], ty[m] = c.pos
                tr[m] = c.capture_radius()
        seeking = tgt >= 0
        free = ~seeking

        # steering
        theta = self.flow(hx, hy, t)
        # near the edges, blend the current smoothly toward the middle of the screen
        m = 0.16 * self.H
        edge = np.minimum.reduce([hx, self.W - hx, hy, self.H - hy])
        wgt = np.clip((m - edge) / m, 0, 1) ** 2 * 3.0
        inward = np.arctan2(self.H / 2 - hy, self.W / 2 - hx)
        theta = np.arctan2(np.sin(theta) + wgt * np.sin(inward), np.cos(theta) + wgt * np.cos(inward))
        turn = 0.8 + 2.0 * np.minimum(wgt, 1.0)
        dtheta = (theta - h + np.pi) % (2 * np.pi) - np.pi
        h = h + np.where(free, dtheta * turn * dt, 0) + self.rng.normal(0, 1.4 * math.sqrt(dt), len(idx))
        st = np.arctan2(ty - hy, tx - hx)
        ds = (st - h + np.pi) % (2 * np.pi) - np.pi
        h = np.where(seeking, h + ds * min(1.0, 7.0 * dt), h)
        self.head[idx] = h

        boost = self.boost[idx]
        speed = np.where(seeking, cfg.strand_seek_speed, cfg.strand_speed * (0.55 + 0.9 * energy))
        speed = (speed * self.vmul[idx] + boost) * self.speed_unit
        self.boost[idx] = boost * max(0.0, 1 - 2.0 * dt)

        # arrivals: pin the head to the eater and swallow
        dist = np.hypot(tx - hx, ty - hy)
        arrived = seeking & (dist < np.maximum(tr, 6))
        step = np.where(arrived, 0, speed * dt)
        P[:, 0, 0] += np.cos(h) * step
        P[:, 0, 1] += np.sin(h) * step
        P[arrived, 0, 0] = tx[arrived]
        P[arrived, 0, 1] = ty[arrived]

        seg = self.seg[idx]
        if arrived.any():
            bite = np.minimum(seg, cfg.absorb_rate * dt / (self.K - 1)) * arrived
            seg = seg - bite
            for cid in np.unique(tgt[arrived]):
                sink(int(cid), float(bite[tgt == cid].sum() * (self.K - 1)))
        self.seg[idx] = seg

        # bodies follow their heads
        L = seg * self.scale
        for k in range(1, self.K):
            d = P[:, k - 1] - P[:, k]
            n = np.hypot(d[:, 0], d[:, 1])
            n[n == 0] = 1
            P[:, k] = P[:, k - 1] - d * (L / n)[:, None]
        self.P[idx] = P
        self.target[idx] = tgt

        # finished or tiny strands
        done = arrived & (seg <= 1e-3)
        if done.any():
            for j in idx[done]:
                rest = float(self.seg[j] * (self.K - 1))
                if rest > 0:
                    sink(int(self.target[j]), rest)
                self.alive[j] = False
        self._merge_tiny()

    def _merge_tiny(self):
        """Fold leftover scraps into a neighbouring free strand (ink is never lost)."""
        free = self.alive & (self.target < 0)
        tiny = np.flatnonzero(free & (self.seg * (self.K - 1) < self.cfg.strand_min))
        if not len(tiny):
            return
        others = np.flatnonzero(free & (self.seg * (self.K - 1) >= self.cfg.strand_min))
        for j in tiny:
            if not len(others):
                return
            heads = self.P[others, 0]
            k = others[np.argmin(((heads - self.P[j, 0]) ** 2).sum(axis=1))]
            self.seg[k] += self.seg[j]
            self.alive[j] = False

    # ------------------------------------------------------------ queries
    def nearest_free(self, pos, radius, n):
        free = np.flatnonzero(self.alive & (self.target < 0))
        if not len(free):
            return free
        d2 = ((self.P[free, 0] - np.asarray(pos, np.float32)) ** 2).sum(axis=1)
        close = d2 < radius * radius
        free, d2 = free[close], d2[close]
        return free[np.argsort(d2)[:n]]

    def claim(self, ids, creature_id):
        self.target[ids] = creature_id

    def in_transit(self, creature_id) -> int:
        return int(np.count_nonzero(self.alive & (self.target == creature_id)))

    def free_ink_near(self, pos, radius) -> float:
        free = self.alive & (self.target < 0)
        d2 = ((self.P[:, 0] - np.asarray(pos, np.float32)) ** 2).sum(axis=1)
        m = free & (d2 < radius * radius)
        return float(self.seg[m].sum() * (self.K - 1))

    def free_ink(self) -> float:
        m = self.alive & (self.target < 0)
        return float(self.seg[m].sum() * (self.K - 1))

    def random_free_head(self):
        free = np.flatnonzero(self.alive & (self.target < 0))
        if not len(free):
            return None
        return self.P[self.rng.choice(free), 0].copy()

    def shockwave(self, pos, radius, strength):
        idx = np.flatnonzero(self.alive & (self.target < 0))
        if not len(idx):
            return
        d = self.P[idx, 0] - np.asarray(pos, np.float32)
        r = np.hypot(d[:, 0], d[:, 1])
        m = r < radius
        self.head[idx[m]] = np.arctan2(d[m, 1], d[m, 0])
        self.boost[idx[m]] = strength * (1 - r[m] / radius)

    # ------------------------------------------------------------ drawing
    def draw(self, surf, width, aa, bright):
        idx = np.flatnonzero(self.alive)
        if not len(idx):
            return
        pts = self.P[idx].tolist()
        cols = (self.color[idx].astype(np.float32) * (0.82 * bright)).astype(int).tolist()
        for p, c in zip(pts, cols):
            draw_polyline(surf, c, p, width, aa)
