"""Window, main loop and keyboard."""

from __future__ import annotations

import argparse
import os
import sys

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame

from .clock import SongClock
from .config import Config
from .world import World

HELP = "esc/q quit · h info · m mute · space skip intro · s screenshot"


def parse_args(argv):
    p = argparse.ArgumentParser(prog="inkcycle", description="Conserved Ink: a drawing that eats itself.")
    p.add_argument("--windowed", action="store_true", help="run in a window instead of fullscreen")
    p.add_argument("--size", default="1280x720", help="window size, e.g. 800x480")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--no-music", action="store_true", help="silent (the day still follows the song)")
    p.add_argument("--skip-intro", action="store_true", help="start with the sheet already torn apart")
    p.add_argument("--hud", action="store_true", help="show day, fps and the ink ledger")
    p.add_argument("--frames", type=int, default=0, help="quit after N frames (testing)")
    p.add_argument("--fast", type=float, default=1.0, help="simulation speed multiplier (testing)")
    p.add_argument("--screenshot", default="", help="save a screenshot to this path when quitting")
    return p.parse_args(argv)


def main(argv=None):
    a = parse_args(sys.argv[1:] if argv is None else argv)
    cfg = Config()
    cfg.fullscreen = not a.windowed
    cfg.window = tuple(int(v) for v in a.size.lower().split("x"))
    cfg.fps = a.fps
    cfg.music = not a.no_music
    cfg.skip_intro = a.skip_intro
    cfg.hud = a.hud

    pygame.init()
    pygame.display.set_caption("inkcycle")
    if cfg.fullscreen:
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        pygame.mouse.set_visible(False)
    else:
        screen = pygame.display.set_mode(cfg.window)
    size = screen.get_size()

    clock = SongClock(cfg)
    world = World(cfg, size, clock)
    font = pygame.font.Font(None, max(16, size[1] // 40))
    small = pygame.font.Font(None, max(14, size[1] // 55))
    timer = pygame.time.Clock()
    frames = 0
    day_shown = 0
    day_label_t = 0.0
    muted = False

    running = True
    while running:
        dt = min(timer.tick(cfg.fps) / 1000.0, 0.05)
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN:
                if ev.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False
                elif ev.key == pygame.K_h:
                    cfg.hud = not cfg.hud
                elif ev.key == pygame.K_m and clock.audio:
                    muted = not muted
                    pygame.mixer.music.set_volume(0 if muted else 1)
                elif ev.key == pygame.K_SPACE and not world.opening.released:
                    world.opening.t = world.opening.release_at
                elif ev.key == pygame.K_s:
                    pygame.image.save(screen, f"inkcycle_{pygame.time.get_ticks()}.png")

        clock.update(dt)
        world.update(dt * a.fast)

        screen.fill((0, 0, 0))
        world.draw(screen)

        # a quiet "day N" at each dawn
        if clock.day != day_shown and clock.running:
            day_shown, day_label_t = clock.day, 0.0
        day_label_t += dt
        if clock.running and day_label_t < 6:
            k = min(1.0, day_label_t / 1.5) * min(1.0, (6 - day_label_t) / 1.5)
            img = small.render(f"day {clock.day}", True, (int(150 * k),) * 3)
            screen.blit(img, (size[0] - img.get_width() - 16, size[1] - img.get_height() - 12))

        if cfg.hud:
            ledger = world.ink_accounted()
            lines = [
                f"day {clock.day}  t={clock.t:5.1f}s  energy={clock.energy:.2f}  "
                f"{'night' if clock.night else ''}  fps={timer.get_fps():.0f}",
                f"creatures {len(world.living)}  structures {len(world.creatures) - len(world.living)}  "
                f"strands {world.strands.count()}",
                f"ink {ledger:,.0f} / {world.total_ink:,.0f}  (free {world.strands.free_ink():,.0f})",
                HELP,
            ]
            for i, line in enumerate(lines):
                screen.blit(font.render(line, True, (120, 255, 140)), (12, 12 + i * font.get_linesize()))

        pygame.display.flip()
        frames += 1
        if a.frames and frames >= a.frames:
            running = False

    if a.screenshot:
        pygame.image.save(screen, a.screenshot)
    pygame.quit()


if __name__ == "__main__":
    main()
