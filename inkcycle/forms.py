"""Drawings as data: polylines with lengths, so they can be drawn partially and peeled apart."""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field

import numpy as np

SIGNATURE_RECT = (0, 0, 560, 220)   # sheet px: name, date and signature
ROLE_ORDER = ["sprite", "mote", "walker", "beast", "face"]  # fallback order


class Form:
    """One drawing. Points are relative to its centre, in sheet pixels."""

    def __init__(self, d: dict, rng: np.random.Generator):
        self.name = d["name"]
        self.role = d["role"]
        self.species = d.get("species", self.name)
        self.frame = d.get("frame", 0)
        self.predator = d.get("predator", False)
        self.kind = d.get("kind")
        self.center = tuple(d["center"])
        self.size = tuple(d["size"])
        self.radius = max(self.size) / 2

        pts, slices, colors, cum = [], [], [], []
        run = 0.0
        i = 0
        for s in d["strokes"]:
            p = np.asarray(s["p"], np.float32)
            if len(p) < 2:
                continue
            seg = np.hypot(*np.diff(p, axis=0).T)
            c = np.concatenate([[0.0], np.cumsum(seg)]) + run
            pts.append(p)
            cum.append(c)
            slices.append((i, i + len(p), float(c[0]), float(c[-1])))
            colors.append(tuple(s["c"]) if "c" in s else None)
            run = float(c[-1])
            i += len(p)
        self.pts = np.concatenate(pts) if pts else np.zeros((0, 2), np.float32)
        self.cum = np.concatenate(cum) if cum else np.zeros(0)
        self.slices = slices
        self.colors = colors
        self.length = run
        # three wobble variants for the hand-drawn "boil"
        self.jitter = rng.normal(0, 1, (3,) + self.pts.shape).astype(np.float32)

    def segment(self, a: float, b: float) -> np.ndarray:
        """Local points along the drawing between ink positions a..b (one stroke only)."""
        b = min(max(b, 0.0), self.length)
        for s, e, c0, c1 in self.slices:
            if c0 <= b <= c1 + 1e-6:
                a = max(a, c0)
                cum = self.cum[s:e]
                pts = self.pts[s:e]
                inside = (cum > a) & (cum < b)
                pa = _interp(cum, pts, a)
                pb = _interp(cum, pts, b)
                return np.vstack([pa, pts[inside], pb])
        return np.zeros((2, 2), np.float32)

    def stroke_color(self, ink_pos: float):
        for k, (s, e, c0, c1) in enumerate(self.slices):
            if c0 <= ink_pos <= c1 + 1e-6:
                return self.colors[k]
        return None


def _interp(cum, pts, x):
    k = int(np.clip(np.searchsorted(cum, x), 1, len(cum) - 1))
    span = cum[k] - cum[k - 1]
    t = 0.0 if span <= 0 else (x - cum[k - 1]) / span
    return pts[k - 1] + (pts[k] - pts[k - 1]) * t


@dataclass
class Species:
    """A creature type: one or more frames of the same thing."""
    name: str
    role: str
    frames: list
    predator: bool = False
    kind: str | None = None
    tier: int = 0
    length: float = 0.0
    radius: float = 0.0
    directional: bool = False   # frames are a left -> front -> right turnaround
    cycling: bool = False       # frames are poses to flip through on the beat

    def frame_for(self, vx: float, beat: int) -> Form:
        if self.directional:
            k = int(round((len(self.frames) - 1) / 2 * (1 + max(-1.0, min(1.0, vx)))))
            return self.frames[k]
        if self.cycling:
            return self.frames[beat % len(self.frames)]
        return self.frames[0]


class Library:
    def __init__(self, path, seed=None):
        rng = np.random.default_rng(seed)
        data = json.loads(path.read_text())
        self.sheet = tuple(data["sheet"])
        self.forms = [Form(d, rng) for d in data["forms"]]
        self.total_ink = sum(f.length for f in self.forms)

        x0, y0, x1, y1 = SIGNATURE_RECT
        self.signature = [f for f in self.forms if f.role == "decor"
                          and x0 <= f.center[0] <= x1 and y0 <= f.center[1] <= y1]

        groups: dict[str, list[Form]] = {}
        for f in self.forms:
            if f.role != "decor":
                groups.setdefault(f.species, []).append(f)
        self.species: dict[str, Species] = {}
        for name, frames in groups.items():
            frames.sort(key=lambda f: f.frame)
            f0 = frames[0]
            sp = Species(
                name=name, role=f0.role, frames=frames,
                predator=any(f.predator for f in frames), kind=f0.kind,
                length=sum(f.length for f in frames) / len(frames),
                radius=max(f.radius for f in frames),
                directional=len(frames) >= 3 and f0.role in ("sprite", "walker"),
                cycling=len(frames) >= 2 and f0.role not in ("sprite", "walker"),
            )
            self.species[name] = sp

        # tiers: living roles ordered by how much ink they need
        living = [s for s in self.species.values() if s.role != "structure"]
        role_len = {}
        for s in living:
            role_len.setdefault(s.role, []).append(s.length)
        order = sorted(role_len, key=lambda r: sum(role_len[r]) / len(role_len[r]))
        self.tiers: list[list[Species]] = []
        for t, role in enumerate(order):
            members = [s for s in living if s.role == role]
            for s in members:
                s.tier = t
            self.tiers.append(members)
        self.structures = {s.kind or s.name: s for s in self.species.values() if s.role == "structure"}

    def seed_species(self) -> Species:
        return random.choice(self.tiers[0])

    def next_tier(self, sp: Species) -> list[Species]:
        return self.tiers[sp.tier + 1] if sp.tier + 1 < len(self.tiers) else []

    def prev_tier(self, sp: Species) -> list[Species]:
        return self.tiers[sp.tier - 1] if sp.tier > 0 else []


def resample(points: np.ndarray, n: int) -> np.ndarray:
    """n points evenly spaced along a polyline."""
    p = np.asarray(points, np.float32)
    if len(p) < 2:
        return np.repeat(p[:1] if len(p) else np.zeros((1, 2), np.float32), n, axis=0)
    seg = np.hypot(*np.diff(p, axis=0).T)
    c = np.concatenate([[0.0], np.cumsum(seg)])
    if c[-1] <= 0:
        return np.repeat(p[:1], n, axis=0)
    t = np.linspace(0, c[-1], n)
    return np.stack([np.interp(t, c, p[:, 0]), np.interp(t, c, p[:, 1])], axis=1).astype(np.float32)


def angle_diff(a, b):
    return (a - b + math.pi) % (2 * math.pi) - math.pi
