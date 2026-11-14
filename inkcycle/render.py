"""Drawing forms (fully or partly) onto the screen."""

from __future__ import annotations

import math

import numpy as np
import pygame

from .forms import Form, _interp

WHITE = (255, 255, 255)


def shade(color, k):
    return (int(color[0] * k), int(color[1] * k), int(color[2] * k))


def draw_polyline(surf, color, pts, width, aa):
    if len(pts) < 2:
        return
    if width <= 1 and aa:
        pygame.draw.aalines(surf, color, False, pts)
    else:
        pygame.draw.lines(surf, color, False, pts, width)


def transform(form_pts: np.ndarray, pos, scale, flip=False, angle=0.0) -> np.ndarray:
    p = form_pts.astype(np.float32, copy=True)
    if flip:
        p[:, 0] *= -1
    if angle:
        c, s = math.cos(angle), math.sin(angle)
        p = p @ np.array([[c, s], [-s, c]], np.float32)
    p *= scale
    p[:, 0] += pos[0]
    p[:, 1] += pos[1]
    return p


def draw_form(surf, form: Form, frac: float, pos, scale: float, *, flip=False, angle=0.0,
              boil_idx=0, boil=0.0, bright=1.0, width=2, aa=True, tip=False):
    """Draw the first `frac` of a drawing's ink. Returns the pen-tip position or None."""
    if frac <= 0 or not form.slices:
        return None
    base = form.pts + form.jitter[boil_idx] * boil if boil else form.pts
    pts = transform(base, pos, scale, flip, angle)
    pl = pts.tolist()
    target = frac * form.length
    white = shade(WHITE, bright)
    tip_pos = None
    for k, (s, e, c0, c1) in enumerate(form.slices):
        if c0 >= target:
            break
        col = shade(form.colors[k], bright) if form.colors[k] else white
        if c1 <= target:
            draw_polyline(surf, col, pl[s:e], width, aa)
        else:
            cum = form.cum[s:e]
            j = int(np.searchsorted(cum, target))
            end = _interp(cum, pts[s:e], target).tolist()
            seg = pl[s:s + j] + [end]
            draw_polyline(surf, col, seg, width, aa)
            tip_pos = end
            break
    if tip and tip_pos:
        pygame.draw.circle(surf, white, (int(tip_pos[0]), int(tip_pos[1])), max(2, width + 1))
    return tip_pos
