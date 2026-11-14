"""Every tunable number in one place. Change these to change the world's temperament."""

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    # files
    forms_path: Path = ROOT / "assets" / "forms.json"
    song_path: Path = ROOT / "unknown.mp3"
    song_map_path: Path = ROOT / "assets" / "song.json"

    # display
    fullscreen: bool = True
    window: tuple = (1280, 720)
    fps: int = 30
    line_width: float = 3.0      # in sheet px; scaled with everything else
    antialias: bool = True       # smoother 1px lines (only used when width rounds to 1)
    hud: bool = False
    music: bool = True
    skip_intro: bool = False

    # world scale: drawings are this many sheet px per screen height
    sheet_px_per_screen: float = 1650.0

    # opening: the sheet draws itself, holds, then comes apart
    intro_pen_speed: float = 650.0    # ink px / second per drawing
    intro_stagger: float = 0.42       # seconds between drawings starting
    intro_hold: float = 4.0

    # strands (loose ink)
    strand_points: int = 8
    strand_chunk: float = 110.0       # longest strand, ink px
    strand_min: float = 14.0          # smaller strands merge into others
    strand_speed: float = 55.0        # screen px/s at 1080p, free drifting
    strand_seek_speed: float = 260.0  # when flying toward an eater
    absorb_rate: float = 420.0        # ink px / second swallowed per strand

    # creatures
    max_creatures: int = 26
    max_structures: int = 3
    pen_speed: float = 700.0          # how fast drawings draw themselves, ink px/s
    metabolism: float = 0.004         # fraction of own ink shed per second
    elder_metabolism: float = 0.03    # once past their lifespan
    feed_radius: float = 0.22         # fraction of screen height
    max_in_transit: int = 6           # strands flying toward one creature
    birth_interval: float = 1.6       # seconds between attempts to seed a creature
    lifespan: tuple = (70.0, 190.0)   # seconds before a creature starts fading
    structure_life: tuple = (200.0, 520.0)
    eat_rate: float = 1600.0          # ink px/s pulled out of prey
    tier_caps: tuple = (8, 6, 6, 4, 3)  # most at once: seeds, motes, walkers, beasts, faces
    tier_burn: float = 0.6            # each tier up burns ink this much faster
    maturity: float = 10.0            # seconds (+6 per tier) before a creature can grow

    # line boil (hand-drawn wobble), in sheet px
    boil: float = 1.3
