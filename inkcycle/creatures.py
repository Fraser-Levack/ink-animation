"""Creatures: drawings that own a quantity of ink and spend it on being drawn.

A creature is only as complete as the ink it holds. Starving ones visibly lose
their last strokes; well-fed ones redraw themselves as something bigger.
"""

from __future__ import annotations

import math
import random

import numpy as np

from .forms import Species, angle_diff
from .render import draw_form, transform

BASE_SPEED = {"sprite": 62, "mote": 70, "walker": 46, "beast": 58, "face": 24, "structure": 0}
SHED_PIECE = 40.0  # ink px peeled off at a time when fading


class Creature:
    _next_id = 0

    def __init__(self, world, species: Species, pos, ink=0.0, state="forming"):
        Creature._next_id += 1
        self.id = Creature._next_id
        self.world = world
        self.species = species
        self.form = species.frames[0]
        self.pos = np.asarray(pos, np.float32).copy()
        self.vel = np.zeros(2, np.float32)
        self.ink = ink
        self.frac = 0.0
        self.state = state
        self.age = 0.0
        cfg = world.cfg
        span = cfg.structure_life if species.role == "structure" else cfg.lifespan
        self.life = random.uniform(*span)
        self.elder = False
        self.flip = False
        self.angle = 0.0
        self.spin = 0.15 if species.kind == "cube" else 0.0
        self.wander = random.uniform(0, 2 * math.pi)
        self.phase = random.uniform(0, 10)
        self.shed_debt = 0.0
        self.eater = None
        self.prey = None
        self.next_species = None
        self.aim = None            # what it is trying to grow into
        self.feed_timer = random.uniform(0, 0.3)
        self.starve_timer = 0.0
        self.release_up = False
        self.shake = 0.0

    # ------------------------------------------------------------ properties
    @property
    def role(self):
        return self.species.role

    @property
    def is_structure(self):
        return self.species.role == "structure"

    def radius(self) -> float:
        return self.species.radius * self.world.scale

    def capture_radius(self) -> float:
        return self.radius() * 0.3

    def accepts_ink(self) -> bool:
        return self.state in ("forming", "alive", "morph_out")

    def wanted_ink(self) -> float:
        """How much ink this creature is trying to hold right now."""
        if self.state == "forming":
            return self.form.length
        if self.elder or self.state != "alive":
            return 0.0
        if self.is_structure:
            extra = 0.0
            if self.species.kind == "machine":
                extra = self.world.lib.tiers[min(2, len(self.world.lib.tiers) - 1)][0].length * 2
            return self.form.length + extra
        if self.aim is None:
            self.aim = self._choose_aim()
        if self.aim is not None and self.world.tier_has_room(self.aim.tier):
            return self.aim.length * 1.04
        return self.form.length

    # ------------------------------------------------------------ ink in / out
    def receive(self, amount: float):
        self.ink += amount
        self.starve_timer = 0.0

    def shed(self, amount, target=-1, heading=None, boost=0.0):
        amount = min(amount, self.ink)
        if amount <= 0:
            return
        L = self.form.length
        drawn = self.frac * L
        reserve = self.ink - drawn
        if reserve >= amount or L <= 0:
            a = random.uniform(0, max(0.0, L - amount))
            shape = self.form.segment(a, a + amount)
            col = self.form.stroke_color(a + amount)
        else:
            b = drawn
            shape = self.form.segment(b - amount, b)
            col = self.form.stroke_color(b)
            self.frac = max(0.0, min(self.frac, (self.ink - amount) / L))
        pts = transform(shape, self.draw_pos(), self.world.scale, self.flip, self.angle)
        self.ink -= amount
        self.world.strands.add(pts, amount, heading=heading, target=target, color=col, boost=boost)

    # ------------------------------------------------------------ life
    def update(self, dt):
        w = self.world
        cfg = w.cfg
        clock = w.clock
        self.age += dt
        self.shake = max(0.0, self.shake - dt * 4)
        L = max(1.0, self.form.length)

        if self.state == "eaten":
            self._being_eaten(dt)
            return
        if self.state == "dissolving":
            self._dissolve(dt)
            return

        # pen: the visible drawing catches up with the ink held
        target = min(1.0, self.ink / L)
        pen = cfg.pen_speed * (0.7 + 0.6 * clock.energy) / L
        if self.state == "morph_out":
            self.frac -= pen * 2.2 * dt
            if self.frac <= 0:
                self.frac = 0.0
                self.species = self.next_species
                self.form = self.species.frames[0]
                self.state = "alive"
        elif self.frac < target:
            self.frac = min(target, self.frac + pen * dt)
        else:
            self.frac = target

        if self.state == "forming":
            self.starve_timer += dt
            if self.ink >= L * 0.999 and self.frac >= 0.999:
                self.state = "alive"
            elif self.starve_timer > 25:
                self.dissolve()
                return

        if not self.elder and self.age > self.life:
            self.elder = True

        # feeding
        self.feed_timer -= dt
        if self.feed_timer <= 0:
            self.feed_timer = 0.3
            want = self.wanted_ink() - self.ink
            if want > 0:
                busy = w.strands.in_transit(self.id)
                limit = cfg.max_in_transit * (3 if self.is_structure or self.state == "forming" else 1)
                if busy < limit:
                    reach = cfg.feed_radius * w.H * (2.4 if self.is_structure else 1.0) + self.radius()
                    ids = w.strands.nearest_free(self.pos, reach, limit - busy)
                    w.strands.claim(ids, self.id)

        # fading: shed ink back into the world
        if self.state == "alive":
            rate = (cfg.elder_metabolism if self.elder else cfg.metabolism) * self.ink
            if self.is_structure and not self.elder:
                rate *= 0.3
            elif not self.is_structure:
                rate *= 1 + cfg.tier_burn * self.species.tier
            self.shed_debt += rate * (0.6 + 0.8 * clock.energy) * dt
            if self.shed_debt >= SHED_PIECE:
                self.shed(self.shed_debt)
                self.shed_debt = 0.0
            self._grow_or_shrink()

        self._move(dt)

    def _choose_aim(self):
        nxt = self.world.lib.next_tier(self.species)
        return random.choice(nxt) if nxt else None

    def _grow_or_shrink(self):
        lib = self.world.lib
        L = self.form.length
        if self.is_structure:
            if self.elder and self.ink < L * 0.5:
                self.dissolve()
            return
        cfg = self.world.cfg
        mature = self.age > cfg.maturity + 6 * self.species.tier
        aim = self.aim
        if (not self.elder and mature and self.frac >= 0.999 and aim is not None
                and self.ink >= aim.length and self.world.tier_has_room(aim.tier)):
            self.morph(aim)
            return
        if self.ink < L * 0.45:
            prev = [s for s in lib.prev_tier(self.species) if s.length <= self.ink * 1.1]
            if prev:
                self.morph(random.choice(prev))
            else:
                self.dissolve()

    def morph(self, species):
        self.next_species = species
        self.state = "morph_out"
        self.aim = None
        self.age = min(self.age, self.life * 0.5)  # a new form gets a fresh(ish) life

    def dissolve(self, upward=False):
        self.state = "dissolving"
        self.release_up = upward

    def _dissolve(self, dt):
        amount = max(SHED_PIECE, 900 * dt)
        heading = -math.pi / 2 + random.uniform(-0.4, 0.4) if self.release_up else None
        boost = 220 if self.release_up else 60
        if self.ink <= amount:
            self.shed(self.ink, heading=heading, boost=boost)
            self.world.remove(self)
        else:
            self.shed(amount, heading=heading, boost=boost)

    def _being_eaten(self, dt):
        eater = self.world.by_id.get(self.eater)
        self.shake = 1.0
        if eater is None or not eater.accepts_ink():
            self.eater = None
            self.dissolve()
            return
        self.pos += (eater.pos - self.pos) * min(1.0, 0.6 * dt)
        amount = max(SHED_PIECE, self.world.cfg.eat_rate * dt)
        if self.ink <= amount:
            self.shed(self.ink, target=eater.id)
            self.world.remove(self)
        else:
            self.shed(amount, target=eater.id)

    # ------------------------------------------------------------ movement
    def _move(self, dt):
        w = self.world
        clock = w.clock
        unit = w.H / 1080.0
        speed = BASE_SPEED.get(self.role, 40) * unit * (0.5 + 0.9 * clock.energy)
        if clock.night:
            speed *= 0.45

        if self.is_structure:
            if self.species.kind == "cube":
                self.angle += self.spin * dt
                self.spin += (0.15 - self.spin) * min(1.0, 0.5 * dt)
                self.vel = np.array([math.cos(self.phase + self.age * 0.05),
                                     math.sin(self.phase * 1.3 + self.age * 0.04)], np.float32) * 6 * unit
                self.pos += self.vel * dt
                r = self.radius() * 0.75
                self.pos[0] = min(max(self.pos[0], r), w.W - r)
                self.pos[1] = min(max(self.pos[1], r), w.H - r)
            return

        self.wander += random.gauss(0, 1.6 * math.sqrt(dt))
        desired = np.array([math.cos(self.wander), math.sin(self.wander)], np.float32) * speed

        if self.role == "sprite":       # loose flocking
            mates = [c.pos for c in w.living if c.role == "sprite" and c is not self
                     and np.sum((c.pos - self.pos) ** 2) < (0.3 * w.H) ** 2]
            if mates:
                desired += (np.mean(mates, axis=0) - self.pos) * 0.25

        if self.species.predator and self.state == "alive" and not self.elder:
            self._hunt(desired, speed)

        if self.elder and w.church is not None:
            to = w.church.pos - self.pos
            d = float(np.hypot(*to))
            desired = to / max(d, 1) * speed * 1.2
            if d < w.church.radius() * 0.7 and self.state == "alive":
                self.dissolve(upward=True)
                w.church.shake = 1.0
        elif clock.night and w.sign is not None:
            to = w.sign.pos - self.pos
            d = float(np.hypot(*to))
            if d > w.sign.radius() * 1.6:
                desired += to / max(d, 1) * speed * 0.8

        if self.prey is not None:
            prey = w.by_id.get(self.prey)
            if prey is not None and prey.state == "eaten":
                desired *= 0.1  # pause while eating
            else:
                self.prey = None

        # personal space
        for c in w.creatures:
            if c is self:
                continue
            d = self.pos - c.pos
            dist = float(np.hypot(*d))
            gap = (self.radius() + c.radius()) * 0.55
            if 0 < dist < gap:
                desired += d / dist * speed * 1.5 * (1 - dist / gap) * (3 if c.is_structure else 1)

        # stay on screen
        r = self.radius()
        m = r + 0.04 * w.H
        if self.pos[0] < m: desired[0] += speed * 1.5
        if self.pos[0] > w.W - m: desired[0] -= speed * 1.5
        if self.pos[1] < m: desired[1] += speed * 1.5
        if self.pos[1] > w.H - m: desired[1] -= speed * 1.5

        if clock.beat_now and self.role == "mote":
            self.vel += np.random.normal(0, 1, 2).astype(np.float32) * speed * 0.9

        self.vel += (desired - self.vel) * min(1.0, 2.0 * dt)
        self.pos += self.vel * dt
        if abs(self.vel[0]) > 6 * unit:
            self.flip = self.vel[0] < 0
        if self.species.directional or self.species.cycling:
            vx = float(self.vel[0]) / max(speed, 1e-3)
            self.form = self.species.frame_for(vx * 1.4, clock.beat + self.id)

    def _hunt(self, desired, speed):
        w = self.world
        if self.ink >= self.wanted_ink():
            return
        best, bd = None, (0.5 * w.H) ** 2
        for c in w.living:
            if c is self or c.is_structure or c.state not in ("alive", "forming"):
                continue
            if c.species.tier >= self.species.tier:
                continue
            d = float(np.sum((c.pos - self.pos) ** 2))
            if d < bd:
                best, bd = c, d
        if best is None:
            return
        to = best.pos - self.pos
        d = math.sqrt(bd)
        desired[:] = to / max(d, 1) * speed * 1.7
        if d < (self.radius() + best.radius()) * 0.45:
            best.state = "eaten"
            best.eater = self.id
            self.prey = best.id
            self.shake = 1.0

    # ------------------------------------------------------------ drawing
    def draw_pos(self):
        p = self.pos
        clock = self.world.clock
        dy = 0.0
        if self.role == "walker":
            dy = -abs(math.sin(clock.beat_phase * math.pi)) * 5 * self.world.H / 1080
        elif self.role in ("mote", "sprite"):
            dy = math.sin(self.age * 3 + self.phase) * 3 * self.world.H / 1080
        if self.shake:
            return (p[0] + random.uniform(-3, 3) * self.shake, p[1] + dy + random.uniform(-3, 3) * self.shake)
        if self.species.kind == "machine" and clock.beat_phase < 0.15:
            dy -= 2
        return (float(p[0]), float(p[1] + dy))

    def draw(self, surf, bright):
        w = self.world
        flip = self.flip and not (self.species.directional or self.is_structure)
        draw_form(surf, self.form, self.frac, self.draw_pos(), w.scale,
                  flip=flip, angle=self.angle, boil_idx=w.clock.boil_idx,
                  boil=w.cfg.boil * (0.6 + 0.9 * w.clock.energy), bright=bright,
                  width=w.line_width, aa=w.cfg.antialias,
                  tip=self.frac < 0.999 and self.state in ("forming", "alive"))
