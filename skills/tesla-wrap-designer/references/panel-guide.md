# Panel guide

Panel ids come from `panels.json` (connected components of the pinned Tesla template, sorted
by area). They are stable as long as `models.json → source_ref` is unchanged; if Tesla updates
a template, regenerate with `fetch_templates.py --model ID --refresh` and re-check this table
against `panels_overlay.png`.

Semantic names below were identified visually from the overlays — treat them as strong hints
and always confirm on `panels_overlay.png`. Pairs are written `left-column | right-column` in
UV space (which physical side of the car each column maps to has not been verified in a car —
design symmetrically so it does not matter).

## Layout (all 1024×1024 templates)

Front of car at the **top** of the canvas: front bumper → hood in the centre column, then the
glass roof gap (not mapped), then liftgate/trunk → rear bumper at the bottom. Each side of the
car is unrolled into the left and right columns: front fender at top, front door, rear door,
rear quarter / rocker at the bottom. Thin centre strips are A-pillars/roof rails; small
islands near the hood are mirror caps.

## Orientation (`upright_rotate` in panels.json)

Learned from Tesla's own example wraps: hood/front panels **180°**, left-column side panels
**+90°**, right-column side panels **−90°**, rear panels **0°**. Cybertruck: top side band
**180°**, bottom side band **0°**, front (left) **−90°**, rear (right) **+90°**. Layers placed
with `panel:` use this automatically; set `rotate` yourself only when placing by `position`.

## Hero panels per model

| Model id | Hood | Front bumper | Front doors | Rear doors | Rear quarters | Front fenders | Trunk / liftgate | Rear bumper | Mirrors |
|---|---|---|---|---|---|---|---|---|---|
| `model3` | 2 | 1 | 7 \| 8 | 9 \| 10 | 5 \| 6 | 11 \| 12 | 4 | 3 | 15 \| 16 |
| `model3-2024-base` | 2 | 1 | 6 \| 7 | 10 \| 9 | 3 \| 4 | 12 \| 11 | 8 | 5 | 16 \| 17 |
| `model3-2024-performance` | 1 | 3 | 6 \| 7 | 10 \| 9 | 5 \| 4 | 12 \| 11 | 8 | 2 | 16 \| 17 |
| `modely` | 1 | 2 | 5 \| 4 | 6 \| 7 | 12 \| 11 | 10 \| 9 | 3 | 8 | 16 \| 15 |
| `modely-2025-base` | 1 | 4 | 3 \| 2 | 6 \| 5 | 12 \| 11 | 9 \| 10 | 7 | 8 | 17 \| 18 |
| `modely-2025-premium` | 1 | 2 | 3 \| 4 | 5 \| 6 | 11 \| 10 | 9 \| 8 | 12 | 7 | 19 \| 20 |
| `modely-2025-performance` | 1 | 2 | 4 \| 3 | 6 \| 5 | 11 \| 10 | 8 \| 9 | 12 | 7 | 21 \| 22 |
| `modely-l` | 1 | 2 | 4 \| 3 | 5 \| 6 | 7 \| 8 | 10 \| 11 | 16 | 9 | 20 \| 19 |
| `models-2021` | 1 | 2 | 4 \| 5 | 9 \| 10 | 7 \| 8 | 11 \| 12 | 6 | 3 | 19 \| 18 |
| `models-2025-plaid` | 1 | 3 | 4 \| 5 | 9 \| 10 | 7 \| 8 | 12 \| 11 | 6 | 2 | 18 \| 19 |
| `modelx-2021` | 1 | 2 | 4 \| 3 | 6 \| 5 | 9 \| 8 | 12 \| 13 | 10 | 7 | 19 \| 18 |

**Cybertruck** (`cybertruck`, 1024×768): 1 = side band (top of canvas, art rotated 180°),
2 = other side band (bottom, upright), 3 = hood / frunk, 5 = front fascia strip,
4 = tailgate. The side bands are huge and continuous — ideal for long text and panoramas.

## Placement tips

- Best text real estate: the long rear-quarter strips and the door pairs. A front door + rear
  door are separated by a seam — split words across them only deliberately (e.g. one word per
  door).
- Hoods are wide and shallow after the 180° rotation; good for emblems and short words.
- Bumpers are heavily curved on the car; use patterns, not text.
