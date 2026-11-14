# inkcycle — Conserved Ink

A drawing that eats itself, one song at a time.

The world holds a fixed amount of white line: exactly the ink on the sheet
(`Untitled.png`, about 70,000 px of it). Nothing creates or destroys ink; it
only gets redrawn.

1. **Opening.** The sheet draws itself stroke by stroke, holds, then every
   line breaks loose as a drifting strand.
2. **Birth.** Where loose ink gathers, a cone-head gnome starts drawing itself
   in, as the ink arrives.
3. **Growth.** Creatures pull in strands. With enough ink a creature unweaves
   and redraws itself one tier up:
   gnome → fuzzball → egg-head → beast → face.
4. **Hunger.** The shark-man, the toothfish and the smirking man hunt smaller
   drawings and pull them apart stroke by stroke.
5. **Fading.** Everything slowly sheds ink. A starving creature visibly loses
   its last-drawn strokes, shrinks back down the tiers, and finally unravels.
6. **Places.** These are built from ink as well, and they come and go:
   - **Machine:** collects loose ink and builds egg-heads on the beat.
   - **Church:** the elderly walk to it and are released upward as strands.
   - **Niederbipp sign:** everyone gathers there at night.
   - **Cube:** turns on a drop in the song and redraws everything near it
     as something else.

**One play-through of the song is one day.** Its loudness drives how fast
everything lives. The beat drives the line wobble, the egg-heads' steps and
the machine. The last part of the song is night, when the world dims and
slows down. Then the song loops and a new day starts.

## Credits

- Drawings: Fraser Levack
- Music: [Chilly Borgor on Newgrounds](https://chillyborger.newgrounds.com/)

## Run it

```bash
pip install -r requirements.txt
python -m inkcycle                 # fullscreen; Esc to quit
python -m inkcycle --windowed      # in a window
```

Options: `--windowed --size 800x480 --fps 24 --no-music --skip-intro --hud`

Keys: `Esc`/`q` quit · `h` info (shows the ink ledger) · `m` mute ·
`space` skip the opening · `s` screenshot

## On a Raspberry Pi display

Copy the whole folder to the Pi (for example `~/inkcycle`), then:

```bash
sudo apt install python3-pygame python3-numpy   # or: pip install pygame-ce numpy
cd ~/inkcycle
python3 -m inkcycle
```

To start it at boot on Raspberry Pi OS with the desktop:

```bash
chmod +x pi/run.sh
mkdir -p ~/.config/autostart
cp pi/inkcycle.desktop ~/.config/autostart/
# edit the Exec= path in that file if the folder isn't ~/inkcycle
```

Performance: a frame takes about 5 ms on a desktop PC. A Pi 5 should hold
30 fps easily. On a Pi 4 use `--fps 24`, and if it struggles, lower
`max_creatures` in `inkcycle/config.py`. If there are no speakers, the day
still follows the song's loudness map, just silently.

## Changing things

- **Behaviour:** every number is in `inkcycle/config.py`, with comments.
- **New drawings:** draw on the sheet (white on black), then run the tools on
  a desktop (`pip install -r requirements-tools.txt`):
  ```bash
  python tools/extract_sprites.py      # re-cuts the sheet -> assets/forms.json, assets/sprites/
  ```
  New drawings get a role from their size automatically. To name one or
  give it a role, add it to `assets/catalog.json` with its approximate centre
  in sheet pixels. Check `assets/sheet_map.png` to see how the sheet was cut.
- **A different song:** `python tools/analyse_song.py path/to/song.mp3`,
  then point `song_path` in the config at it.
- **Testing without waiting:** `python tools/fastforward.py 600` simulates 10
  minutes in about 30 seconds and checks that no ink was created or lost.

## Layout

```
Untitled.png, unknown.mp3   your originals (untouched)
assets/catalog.json         names & roles for each drawing
assets/forms.json           every drawing as pen strokes (generated)
assets/song.json            the song's loudness + beat map (generated)
assets/sprites/             each drawing cut out as a PNG (generated)
assets/sheet_map.png        how the sheet was cut (generated)
inkcycle/                   the program
tools/                      sheet cutter, song mapper, fast-forward test
pi/                         Raspberry Pi launcher + autostart entry
```
