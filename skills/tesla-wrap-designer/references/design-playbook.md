# Design playbook

How to turn a theme idea into a wrap that looks intentional on a 3D car, not like a
wallpaper stretched over seams.

## Composition principles

1. **Three tiers.** Every good wrap has (a) a full-canvas *field* (gradient / noise / pattern)
   that hides seams, (b) *accents* that follow panels (stripes, bursts, sparkles), and (c) one
   or two *hero* elements (text, emblem, user photo) placed inside single large panels.
2. **Field first, edge to edge.** The first layers must cover 100 % of the canvas. Never rely
   on `base_color` alone for a large panel unless a flat colour is the intent.
3. **Heroes on the biggest panels.** Run `fetch_templates.py --model ID` and *look at*
   `.cache/templates/<id>/panels_overlay.png`. The largest panels (ids 1–6 in `panels.json`,
   sorted by area) are usually the two sides, hood, roof/trunk. Put text on side panels
   (most visible in the Paint Shop 3D view), emblems on the hood.
4. **Symmetry.** Cars are viewed from both sides. When placing a hero on one side panel,
   place a matching one on its mirror panel (similar area, mirrored centroid).
5. **Rotate to the panel.** Panel-placed text auto-rotates to the panel long axis; when using
   `position`, set `rotate` from the panel's `angle_deg`. Check orientation in the viewer
   "On template" tab: letters should run along the car body.
6. **Contrast.** Text needs a stroke (≥ 4 px) or shadow; the car render is small and shaded.
7. **Avoid seams for faces/text.** ≥ 12 px inside the panel outline.
8. **Budget for 1 MB.** Prefer smooth gradients + crisp vector shapes; limit high-frequency
   noise to one layer with moderate contrast.

## Turning ideas into art

- **Procedural layers** (`gradient`, `noise`, `pattern`, `shape`, `text`) cover most themes.
- **SVG layers** are the tool for illustrative content: write original vector art inline
  (emblems, mascots, silhouettes, badges, typography lockups, cartoon elements). Draw at the
  layer `box` size; use bold shapes and outlines — they survive the downscale in the car UI.
- **User images** (`image` layer): photos on a panel with `mask: rounded` + `feather`, or
  logos with `remove_bg: true`. Never place a photo across seams.
- **Variants:** after the first render, offer a colourway or layout variant by copying the
  spec and changing palette/seed — cheap and users love choice.

## Theme recipes (starting points — adapt to the brief)

| Theme | Field | Accents | Hero ideas | Palette |
|---|---|---|---|---|
| Space opera ("Star Wars"-style) | deep-space linear gradient + `nebula` noise (screen) | `starfield`, `lightspeed` streaks from hood centre, glowing beam shapes (laser-sword-like, blurred glow under a white core) | original starfighter / planet silhouette in SVG, crawl-style slanted gold text with *original* wording | `#05060f #1b1446 #3b1c6e #ffd84a #49c6ff #ff3b3b` |
| Cartoon sitcom ("Simpsons"-style) | sky-blue vertical gradient | `clouds_cartoon`, `polka` / `dots` | thick-outlined donut / house / sunburst SVG, bubbly text with heavy stroke | `#5fb7f5 #ffd90f #ff7fbf #ffffff #2b2b2b` |
| Happy birthday | warm diagonal gradient | `confetti`, `balloons`, `bokeh`, `sparkles` | "HAPPY BIRTHDAY" on both sides, name on hood, cake/gift SVG | `#ff4f8b #ffb000 #7b4dff #22d3ee #ffffff` |
| Racing livery | solid paint colour | `stripes` (2–3 wide), `carbon` on lower panels | number roundel SVG on doors | team colours |
| Holiday / winter | night-blue gradient | `sparkles`, snow `dots`, `string lights` (dots along curve) | reindeer / tree SVG | `#0b1d3a #e63946 #2a9d8f #f1faee #ffd166` |
| Camo / tactical | `camo` noise | `hex` or `grid` at low opacity | stencil text | olive / sand / stealth |
| Floral (Sakura) | soft pink gradient | `bokeh`, petal shapes | branch SVG | `#ffd6e0 #ff8fab #fb6f92 #ffffff #5c3d2e` |

## Intellectual property

Franchise themes ("Star Wars", "Simpsons", sports teams, brands) are fine as **inspiration**:
evoke them with palette, motifs, mood and typography style, using *original* artwork. Do
**not** recreate copyrighted characters, logos, title treatments or trademarked names in the
art. Say this briefly once, offer the homage approach, and move on. If the user supplies
their own images (photos, licensed art they own), they can be placed — remind them it's their
responsibility to have rights; it's for their personal car display.
