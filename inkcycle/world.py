"""The world: a fixed amount of ink, shared between creatures and loose strands.

Nothing here ever creates or destroys ink. The total is set by the sheet you
drew; the opening draws that sheet, then takes it apart.
"""

from __future__ import annotations

import math
import random

import numpy as np

from .creatures import Creature
from .forms import Library
from .render import draw_form
from .strands import StrandPool


class Opening:
    """The sheet draws itself stroke by stroke, holds, then comes apart."""

    def __init__(self, world):
        self.world = world
        lib = world.lib
        W, H = world.W, world.H
        sw, sh = lib.sheet
        self.scale = min(W / sw, H / sh) * 0.94
        self.origin = ((W - sw * self.scale) / 2, (H - sh * self.scale) / 2)
        cfg = world.cfg
        order = sorted(lib.forms, key=lambda f: (f.center[1] // 260, f.center[0]))
        self.items = []
        t = 0.0
        for f in order:
            self.items.append([f, t, 0.0])  # form, start time, frac
            t += cfg.intro_stagger
        self.draw_end = max(s + f.length / cfg.intro_pen_speed for f, s, _ in self.items)
        self.release_at = self.draw_end + cfg.intro_hold
        self.t = 0.0
        self.released = False

    def screen_pos(self, f):
        return (self.origin[0] + f.center[0] * self.scale, self.origin[1] + f.center[1] * self.scale)

    def ink(self) -> float:
        if self.released:
            return 0.0
        sig = self.world.lib.signature
        return sum(f.length for f, _, _ in self.items if f not in sig)

    def update(self, dt):
        self.t += dt
        speed = self.world.cfg.intro_pen_speed
        for item in self.items:
            f, start, _ = item
            item[2] = min(1.0, max(0.0, (self.t - start) * speed / max(f.length, 1)))
        if not self.released and self.t >= self.release_at:
            self.release()

    def release(self):
        """Every stroke breaks loose as a strand, flung gently outward."""
        w = self.world
        self.released = True
        cx, cy = w.W / 2, w.H / 2
        for f, _, _ in self.items:
            if f in w.lib.signature:
                continue
            pos = self.screen_pos(f)
            out = math.atan2(pos[1] - cy, pos[0] - cx)
            for k, (s, e, c0, c1) in enumerate(f.slices):
                pts = f.pts[s:e] * self.scale + np.asarray(pos, np.float32)
                w.strands.add(pts, c1 - c0, heading=out + random.uniform(-0.8, 0.8),
                              color=f.colors[k], boost=random.uniform(40, 160))
        self.items = [it for it in self.items if it[0] in w.lib.signature]

    def draw(self, surf, width, aa, boil_idx):
        fade = 1.0
        if self.released:
            fade = 0.35
        for f, _, frac in self.items:
            draw_form(surf, f, frac, self.screen_pos(f), self.scale, boil_idx=boil_idx,
                      boil=self.world.cfg.boil * 0.7, bright=fade, width=width, aa=aa,
                      tip=0 < frac < 1)


class World:
    def __init__(self, cfg, size, clock):
        self.cfg = cfg
        self.W, self.H = size
        self.clock = clock
        self.lib = Library(cfg.forms_path)
        self.scale = self.H / cfg.sheet_px_per_screen
        self.line_width = max(1, round(cfg.line_width * self.scale))
        self.strands = StrandPool(cfg, size, self.scale)
        self.creatures: list[Creature] = []
        self.by_id: dict[int, Creature] = {}
        self.opening = Opening(self)
        self.birth_timer = 0.0
        self.structure_timer = 8.0
        # the signature is the artist's mark, not part of the ink economy
        self.total_ink = self.lib.total_ink - sum(f.length for f in self.lib.signature)
        if cfg.skip_intro:
            self.opening.t = self.opening.release_at
            self.opening.update(0)

    # ------------------------------------------------------------ registry
    @property
    def living(self):
        return [c for c in self.creatures if not c.is_structure]

    def structure(self, kind):
        for c in self.creatures:
            if c.is_structure and c.species.kind == kind and c.state != "dissolving":
                return c
        return None

    @property
    def church(self):
        c = self.structure("church")
        return c if c and c.state == "alive" else None

    @property
    def sign(self):
        c = self.structure("sign")
        return c if c and c.state == "alive" else None

    def tier_count(self, tier) -> int:
        n = 0
        for c in self.creatures:
            if c.is_structure:
                continue
            sp = c.next_species if c.state == "morph_out" else c.species
            n += sp.tier == tier
        return n

    def tier_has_room(self, tier) -> bool:
        caps = self.cfg.tier_caps
        return self.tier_count(tier) < (caps[tier] if tier < len(caps) else caps[-1])

    def add(self, c: Creature):
        self.creatures.append(c)
        self.by_id[c.id] = c
        return c

    def remove(self, c: Creature):
        if c.ink > 1e-6:  # never lose ink: hand any crumb to the strands
            self.strands.add([c.pos, c.pos + 1], c.ink)
            c.ink = 0.0
        if c in self.creatures:
            self.creatures.remove(c)
        self.by_id.pop(c.id, None)

    def sink(self, cid, amount):
        c = self.by_id.get(cid)
        if c is not None:
            c.receive(amount)
        else:  # eater vanished mid-swallow: the ink drops back into the world
            p = self.strands.random_free_head()
            p = p if p is not None else np.array([self.W / 2, self.H / 2], np.float32)
            self.strands.add([p, p + 1], amount)

    def ink_accounted(self) -> float:
        return self.strands.total_ink() + sum(c.ink for c in self.creatures) + self.opening.ink()

    # ------------------------------------------------------------ simulation
    def update(self, dt):
        clock = self.clock
        if not self.opening.released:
            self.opening.update(dt)
            if self.opening.released and not clock.running:
                clock.begin_day()
            return
        self.opening.update(dt)
        if not clock.running:
            clock.begin_day()

        self.strands.update(dt, clock.t if clock.running else 0.0, clock.energy, self.by_id, self.sink)
        for c in list(self.creatures):
            if c in self.creatures:
                c.update(dt)

        self.birth_timer -= dt
        if self.birth_timer <= 0:
            self.birth_timer = self.cfg.birth_interval / (0.5 + clock.energy)
            self._try_birth()
        self.structure_timer -= dt
        if self.structure_timer <= 0:
            self.structure_timer = 6.0
            self._try_structure()

        if clock.beat_now:
            self._machine_beat()
        if clock.surge:
            self._surge()

    def _try_birth(self):
        if len(self.living) >= self.cfg.max_creatures:
            return
        p = self.strands.random_free_head()
        if p is None:
            return
        seed = self.lib.seed_species()
        if not self.tier_has_room(seed.tier):
            return
        crowded = self.strands.free_ink() > 0.55 * self.total_ink
        if crowded or self.strands.free_ink_near(p, 0.2 * self.H) > seed.length * 0.5:
            self.add(Creature(self, seed, p))

    def _try_structure(self):
        built = [c for c in self.creatures if c.is_structure]
        if len(built) >= self.cfg.max_structures:
            return
        if self.strands.free_ink() < 0.3 * self.total_ink or random.random() > 0.35:
            return
        have = {c.species.kind for c in built}
        options = [s for k, s in self.lib.structures.items() if k not in have]
        if not options:
            return
        sp = random.choice(options)
        r = sp.radius * self.scale
        for _ in range(30):
            p = np.array([random.uniform(r + 20, self.W - r - 20), random.uniform(r + 20, self.H - r - 20)],
                         np.float32)
            if all(np.hypot(*(p - c.pos)) > r + c.radius() for c in built):
                self.add(Creature(self, sp, p))
                return

    def _machine_beat(self):
        """The machine turns stored ink into a new walker, on the beat."""
        m = self.structure("machine")
        if m is None or m.state != "alive" or len(self.living) >= self.cfg.max_creatures:
            return
        walkers = [s for s in self.lib.tiers[min(2, len(self.lib.tiers) - 1)]]
        sp = random.choice(walkers)
        if not self.tier_has_room(sp.tier):
            return
        if m.ink - m.form.length >= sp.length and self.clock.beat % 4 == 0:
            m.ink -= sp.length
            out = m.pos + np.array([m.radius() * 0.8, m.radius() * 0.2], np.float32)
            baby = self.add(Creature(self, sp, out, ink=sp.length))
            baby.vel = np.array([60.0, 0.0], np.float32) * self.H / 1080
            m.shake = 0.6

    def _surge(self):
        """A drop in the song: the cube turns and everything near it is redrawn."""
        cube = self.structure("cube")
        for m in [self.structure("machine")]:
            if m is not None:
                m.shake = 1.0
        if cube is None or cube.state != "alive":
            for c in self.living:   # without the cube, the surge just scatters ink
                c.shake = 0.5
            self.strands.shockwave((self.W / 2, self.H / 2), self.H * 0.6, 300)
            return
        cube.spin = 5.0
        cube.shake = 1.0
        reach = self.H * 0.55
        self.strands.shockwave(cube.pos, reach, 420)
        for c in self.living:
            if c.state == "alive" and np.hypot(*(c.pos - cube.pos)) < reach:
                same = [s for s in self.lib.tiers[c.species.tier] if s is not c.species]
                if same:
                    c.morph(random.choice(same))

    # ------------------------------------------------------------ drawing
    def draw(self, surf):
        clock = self.clock
        bright = clock.brightness()
        aa = self.cfg.antialias
        self.opening.draw(surf, max(1, round(self.cfg.line_width * self.opening.scale)), aa, clock.boil_idx)
        if not self.opening.released:
            return
        self.strands.draw(surf, self.line_width, aa, bright)
        for c in sorted(self.creatures, key=lambda c: (not c.is_structure, c.species.tier)):
            c.draw(surf, bright)
