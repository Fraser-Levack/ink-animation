"""Run the world headless and fast, check that no ink is created or lost.

    python tools/fastforward.py [seconds] [--shots DIR]
"""
import os, sys, time
from pathlib import Path
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pygame
from inkcycle.config import Config
from inkcycle.clock import SongClock
from inkcycle.world import World

secs = float(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else 400
shots = Path(sys.argv[sys.argv.index("--shots") + 1]) if "--shots" in sys.argv else None
cfg = Config(); cfg.music = False; cfg.skip_intro = True
pygame.init()
screen = pygame.display.set_mode((1280, 720))
clock = SongClock(cfg)
fake = [0.0]
clock.now = lambda: fake[0]
world = World(cfg, (1280, 720), clock)
dt = 1 / 30
worst = 0.0
wall = time.perf_counter()
n = int(secs / dt)
for i in range(n):
    fake[0] += dt
    clock.update(dt)
    world.update(dt)
    if i % 30 == 0:
        err = abs(world.ink_accounted() - world.total_ink)
        worst = max(worst, err)
    if i % int(15 / dt) == 0:
        roles = {}
        for c in world.creatures:
            key = c.species.name if c.is_structure else c.role
            roles[key] = roles.get(key, 0) + 1
        print(f"t={fake[0]:6.1f} day={clock.day} e={clock.energy:.2f} strands={world.strands.count():4d} "
              f"free={world.strands.free_ink()/world.total_ink:4.0%} {roles}")
    if shots and i % int(40 / dt) == 0 and i:
        screen.fill((0, 0, 0)); world.draw(screen)
        pygame.image.save(screen, str(shots / f"ff_{int(fake[0]):04d}.png"))
el = time.perf_counter() - wall
print(f"\nsimulated {secs:.0f}s in {el:.1f}s ({secs/el:.1f}x realtime, sim only, no drawing)")
print(f"worst ink ledger error: {worst:.3f} px of {world.total_ink:,.0f}")
