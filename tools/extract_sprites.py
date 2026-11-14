"""Cut the drawing sheet into sprites and trace each one into pen strokes.

Run on a desktop machine (needs numpy, scipy, Pillow). The output files are
all the Raspberry Pi needs, so it never has to run this.

    python tools/extract_sprites.py [sheet.png]

Writes:
    assets/sprites/<name>.png   one transparent PNG per drawing
    assets/forms.json           every drawing as a list of polyline strokes
    assets/sheet_map.png        the sheet with every cut labelled (for checking)
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

INK_THRESHOLD = 100      # brightest channel above this counts as ink
DILATE = 5               # px; strokes closer than ~2x this belong together
MERGE_OVERLAP = 0.25     # merge pieces whose boxes overlap this much
MIN_PIECE_AREA = 40      # ignore specks
SIMPLIFY_EPS = 1.1       # Douglas-Peucker tolerance in sheet px
MIN_STROKE_LEN = 5.0
JOIN_DIST = 3.0
JOIN_ANGLE = math.radians(65)


# ----------------------------------------------------------------- segmenting

def segment(ink: np.ndarray):
    """Group ink pixels into drawings. Returns (label image, list of groups)."""
    lab, n = ndi.label(ndi.binary_dilation(ink, iterations=DILATE))
    slices = ndi.find_objects(lab)
    boxes = [[s[1].start, s[0].start, s[1].stop, s[0].stop] for s in slices]
    groups = [[i + 1] for i in range(n)]

    def area(b):
        return max(0, b[2] - b[0]) * max(0, b[3] - b[1])

    merged = True
    while merged:
        merged = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                inter = [max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])]
                if area(inter) > MERGE_OVERLAP * min(area(a), area(b)):
                    boxes[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                    groups[i] += groups[j]
                    del boxes[j], groups[j]
                    merged = True
                    break
            if merged:
                break
    return lab, list(zip(boxes, groups))


# ----------------------------------------------------------------- thinning

def zhang_suen(img: np.ndarray) -> np.ndarray:
    """Thin a boolean image to 1px wide lines."""
    im = np.pad(img.astype(np.uint8), 1)
    while True:
        changed = False
        for step in (0, 1):
            p2 = im[:-2, 1:-1]; p3 = im[:-2, 2:]; p4 = im[1:-1, 2:]; p5 = im[2:, 2:]
            p6 = im[2:, 1:-1]; p7 = im[2:, :-2]; p8 = im[1:-1, :-2]; p9 = im[:-2, :-2]
            c = im[1:-1, 1:-1]
            seq = [p2, p3, p4, p5, p6, p7, p8, p9, p2]
            b = sum(seq[:8])
            a = sum(((seq[k] == 0) & (seq[k + 1] == 1)).astype(np.uint8) for k in range(8))
            if step == 0:
                m = (p2 * p4 * p6 == 0) & (p4 * p6 * p8 == 0)
            else:
                m = (p2 * p4 * p8 == 0) & (p2 * p6 * p8 == 0)
            kill = (c == 1) & (b >= 2) & (b <= 6) & (a == 1) & m
            if kill.any():
                c[kill] = 0
                changed = True
        if not changed:
            return im[1:-1, 1:-1].astype(bool)


NB = [(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)]  # clockwise from N


def crossings(n) -> int:
    """Number of separate line branches touching a pixel (0->1 transitions)."""
    return sum((not n[k]) and n[(k + 1) % 8] for k in range(8))


def trace(sk: np.ndarray) -> list[list[tuple[int, int]]]:
    """Turn a 1px skeleton into polylines of (x, y) pixel coordinates."""
    pix = set(zip(*np.nonzero(sk)))

    def ring(p):
        y, x = p
        return [(y + dy, x + dx) in pix for dy, dx in NB]

    def nbrs(p):
        y, x = p
        return [(y + dy, x + dx) for dy, dx in NB if (y + dy, x + dx) in pix]

    branch = {}
    for p in pix:
        r = ring(p)
        branch[p] = 1 if sum(r) == 1 else crossings(r) if sum(r) else 0
    nodes = {p for p, b in branch.items() if b != 2}
    seen = set()   # regular pixels already on a path
    paths = []

    def step(prev, cur, path):
        while True:
            cand = [q for q in nbrs(cur) if q != prev and q not in seen and q not in path[-3:]]
            if not cand:
                return path
            hit = [q for q in cand if q in nodes]
            if hit and len(path) > 1:
                path.append(hit[0])
                return path
            # prefer orthogonal moves (staircases), then whatever is straightest
            d = (cur[0] - prev[0], cur[1] - prev[1]) if prev else (0, 0)
            cand.sort(key=lambda q: (abs(q[0] - cur[0]) + abs(q[1] - cur[1]),
                                     -((q[0] - cur[0]) * d[0] + (q[1] - cur[1]) * d[1])))
            nxt = cand[0]
            if nxt in nodes:
                path.append(nxt)
                return path
            seen.add(nxt)
            path.append(nxt)
            prev, cur = cur, nxt

    for n in nodes:
        if branch[n] == 0:
            paths.append([n, n])
            continue
        for q in nbrs(n):
            if q in seen:
                continue
            if q in nodes:
                if n < q:
                    paths.append([n, q])
                continue
            seen.add(q)
            paths.append(step(n, q, [n, q]))
    for p in pix:                      # closed loops with no junctions
        if p not in seen and p not in nodes:
            seen.add(p)
            path = step(None, p, [p])
            path.append(p)
            paths.append(path)
    return [[(x, y) for (y, x) in path] for path in paths]


def plen(pts) -> float:
    a = np.asarray(pts, float)
    return float(np.hypot(*np.diff(a, axis=0).T).sum()) if len(a) > 1 else 0.0


def end_dir(pts, at_end: bool):
    """Unit direction pointing *out* of the stroke at one end."""
    a = np.asarray(pts, float)
    k = min(len(a) - 1, 6)
    v = a[-1] - a[-1 - k] if at_end else a[0] - a[k]
    n = np.hypot(*v)
    return v / n if n else v


def join(paths):
    """Glue strokes whose ends meet and continue in roughly the same direction."""
    from scipy.spatial import cKDTree
    paths = [list(p) for p in paths if len(p) > 1]
    if len(paths) < 2:
        return paths
    ends = [(i, e) for i in range(len(paths)) for e in (0, 1)]
    pts = np.array([paths[i][-1] if e else paths[i][0] for i, e in ends], float)
    dirs = [end_dir(paths[i], bool(e)) for i, e in ends]
    cands = []
    for a, b in cKDTree(pts).query_pairs(JOIN_DIST):
        if ends[a][0] == ends[b][0]:
            continue
        ang = math.acos(max(-1.0, min(1.0, -float(dirs[a] @ dirs[b]))))
        if ang < JOIN_ANGLE:
            cands.append((ang, a, b))
    link = {}
    for _, a, b in sorted(cands):
        if a not in link and b not in link:
            link[a] = b
            link[b] = a
    # walk chains: end index k = 2*i + e
    done = set()
    out = []
    def chain_from(k):
        line = []
        while True:
            i, e = divmod(k, 2)
            if i in done:
                break
            done.add(i)
            seg = paths[i] if e == 0 else paths[i][::-1]
            line += seg if not line else seg[1:]
            far = 2 * i + (1 - e)
            if far not in link:
                break
            k = link[far]
        return line
    for i in range(len(paths)):        # start at free ends first
        for e in (0, 1):
            if i not in done and 2 * i + e not in link:
                out.append(chain_from(2 * i + e))
    for i in range(len(paths)):        # what's left are closed chains
        if i not in done:
            out.append(chain_from(2 * i))
    return out


def rdp(pts, eps):
    a = np.asarray(pts, float)
    if len(a) < 3:
        return a
    keep = np.zeros(len(a), bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(a) - 1)]
    while stack:
        s, e = stack.pop()
        if e <= s + 1:
            continue
        seg = a[e] - a[s]
        n = np.hypot(*seg)
        rel = a[s + 1:e] - a[s]
        d = np.abs(seg[0] * rel[:, 1] - seg[1] * rel[:, 0]) / n if n else np.hypot(*rel.T)
        k = int(np.argmax(d))
        if d[k] > eps:
            m = s + 1 + k
            keep[m] = True
            stack += [(s, m), (m, e)]
    return a[keep]


def order_strokes(strokes):
    """Draw like a person: longest line first, then always the nearest next."""
    if not strokes:
        return strokes
    rest = sorted(strokes, key=lambda s: -plen(s))
    out = [rest.pop(0)]
    while rest:
        tail = out[-1][-1]
        best_i, best_rev, best_d = 0, False, float("inf")
        for i, s in enumerate(rest):
            for rev, p in ((False, s[0]), (True, s[-1])):
                d = math.dist(tail, p)
                if d < best_d:
                    best_i, best_rev, best_d = i, rev, d
        s = rest.pop(best_i)
        out.append(s[::-1] if best_rev else s)
    return out


# ----------------------------------------------------------------- main

def main():
    sheet_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "Untitled.png"
    catalog = json.loads((ASSETS / "catalog.json").read_text())
    img = Image.open(sheet_path).convert("RGB")
    rgb = np.asarray(img).astype(np.int16)
    ink = rgb.max(axis=2) > INK_THRESHOLD
    H, W = ink.shape

    lab, groups = segment(ink)
    for r in catalog.get("merge_rects", []):
        inside = [g for g in groups
                  if r[0] <= (g[0][0] + g[0][2]) / 2 <= r[2] and r[1] <= (g[0][1] + g[0][3]) / 2 <= r[3]]
        if len(inside) > 1:
            groups = [g for g in groups if g not in inside]
            box = [min(g[0][0] for g in inside), min(g[0][1] for g in inside),
                   max(g[0][2] for g in inside), max(g[0][3] for g in inside)]
            groups.append((box, sum((g[1] for g in inside), [])))
    sprite_dir = ASSETS / "sprites"
    sprite_dir.mkdir(parents=True, exist_ok=True)
    for old in sprite_dir.glob("*.png"):
        old.unlink()

    taken = set()
    forms = []
    unnamed = 0
    for (x0, y0, x1, y1), labels in groups:
        mask_full = np.isin(lab[y0:y1, x0:x1], labels) & ink[y0:y1, x0:x1]
        if mask_full.sum() < MIN_PIECE_AREA:
            continue
        ys, xs = np.nonzero(mask_full)
        x0, x1, y0, y1 = x0 + xs.min(), x0 + xs.max() + 1, y0 + ys.min(), y0 + ys.max() + 1
        mask = np.isin(lab[y0:y1, x0:x1], labels) & ink[y0:y1, x0:x1]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

        # name & role
        meta = None
        if any(r[0] <= cx <= r[2] and r[1] <= cy <= r[3] for r in catalog["decor_rects"]):
            meta = {"name": f"mark_{len([f for f in forms if f['role'] == 'decor']):02d}", "role": "decor"}
        else:
            best = None
            for name, m in catalog["forms"].items():
                d = math.dist((cx, cy), m["near"])
                if d < catalog["match_radius"] and name not in taken and (best is None or d < best[0]):
                    best = (d, name, m)
            if best:
                taken.add(best[1])
                meta = {"name": best[1], **{k: v for k, v in best[2].items() if k != "near"}}
            else:
                size = max(x1 - x0, y1 - y0)
                role = "mote" if size < 230 else "beast" if size < 380 else "face"
                meta = {"name": f"new_{unnamed:02d}", "role": role}
                unnamed += 1

        # sprite png
        crop = rgb[y0:y1, x0:x1].astype(np.uint8)
        alpha = (mask * 255).astype(np.uint8)
        Image.fromarray(np.dstack([crop, alpha]), "RGBA").save(sprite_dir / f"{meta['name']}.png")

        # strokes: solid filled areas (the chef's hat) become their outline,
        # otherwise thinning turns them into a scribble
        solid = ndi.distance_transform_edt(mask) > 5
        if solid.any():
            region = ndi.binary_dilation(solid, iterations=5) & mask
            mask = mask & ~ndi.binary_erosion(region, iterations=3)
        sk = zhang_suen(mask)
        paths = [p for p in join(trace(sk)) if plen(p) >= MIN_STROKE_LEN]
        paths = order_strokes(paths)
        strokes = []
        for p in paths:
            pts = rdp(p, SIMPLIFY_EPS)
            # stroke colour: keep it only if clearly coloured (e.g. the red badge)
            ip = np.asarray(p)
            cols = crop[ip[:, 1], ip[:, 0]].astype(float)
            mean = cols.mean(axis=0)
            stroke = {"p": [[round(float(x) + x0 - cx, 1), round(float(y) + y0 - cy, 1)] for x, y in pts]}
            if mean.max() - mean.min() > 60:
                stroke["c"] = [int(v) for v in mean]
            strokes.append(stroke)
        length = sum(plen(s["p"]) for s in strokes)
        forms.append({
            **meta,
            "center": [round(cx, 1), round(cy, 1)],
            "size": [int(x1 - x0), int(y1 - y0)],
            "length": round(length, 1),
            "strokes": strokes,
        })
        print(f"{meta['name']:<12} {meta['role']:<10} strokes={len(strokes):<4} ink={length:8.0f}px")

    forms.sort(key=lambda f: (f["center"][1] // 150, f["center"][0]))
    missing = sorted(set(catalog["forms"]) - taken)
    if missing:
        print("WARNING: catalog entries with no matching drawing:", ", ".join(missing))
    total = sum(f["length"] for f in forms)
    out = {"sheet": [W, H], "total_ink": round(total, 1), "forms": forms}
    (ASSETS / "forms.json").write_text(json.dumps(out, separators=(",", ":")))
    print(f"\n{len(forms)} drawings, {total:,.0f}px of ink -> assets/forms.json")

    # labelled map for checking the cuts
    preview = img.copy()
    d = ImageDraw.Draw(preview)
    for f in forms:
        cx, cy = f["center"]; w, h = f["size"]
        col = (90, 90, 90) if f["role"] == "decor" else (255, 60, 60)
        d.rectangle([cx - w / 2 - 3, cy - h / 2 - 3, cx + w / 2 + 3, cy + h / 2 + 3], outline=col, width=3)
        if f["role"] != "decor":
            d.text((cx - w / 2, cy - h / 2 - 14), f"{f['name']} ({f['role']})", fill=(80, 255, 120))
    preview.save(ASSETS / "sheet_map.png")


if __name__ == "__main__":
    main()
