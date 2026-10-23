# Design spec reference

`python3 scripts/render_wrap.py spec.json [--model ID] [--out-dir ./wraps] [--name X] [--preview] [--debug]`
turns a JSON spec into a validated Tesla wrap PNG. Layers are painted bottom to top onto an opaque
`base_color` floor on the model's template canvas (1024x1024; Cybertruck 1024x768).
Unknown keys produce a WARNING (listed in the `RESULT` line); unknown layer types, kinds or blend modes are errors.

```json
{ "name": "Birthday_Bash", "model": "model3-2024-base", "seed": 42, "base_color": "#101020",
  "layers": [ {"type": "gradient", ...}, {"type": "pattern", "kind": "confetti"} ] }
```
Top level: `name` (default filename, sanitised: A-Z a-z 0-9 _ - space, max 26 chars + .png), `model`
(see models.json), `seed` (int, default 0; same spec + seed = identical output), `base_color` (default `#101010`;
also the flatten colour), `layers`. Optional: `size: [w,h]` instead of `model` (testing only).

## Conventions

- **Colours**: `#rgb`, `#rrggbb`, `#rrggbbaa`, `rgb()/rgba()`, CSS names (`"tomato"`), or `[r,g,b(,a)]`.
- **Coordinates**: pixels on the template canvas, or a `"50%"` string. `%` is of canvas width for x / w / radius / size,
  of height for y / h. Boxes are `[x, y, w, h]`, points `[x, y]`.
- **Common layer keys** (all optional): `opacity` 0-1 (1); `blend` `normal|multiply|screen|overlay|add|soft_light` (normal);
  `clip` `"all"` (default) | `"panels"` (car surface only) | `{"panels": [3,7]}` (only those panel ids, grown by
  `clip_bleed` px, default 6); `enabled` false to skip; `name` / `comment` (ignored notes).
- **Dark backgrounds**: for glowing things (nebula, stars, streaks, bokeh, sparkles) use `blend: "screen"` or `"add"`.
- **Panels**: ids come from `.cache/templates/<model>/panels.json` and `panels_overlay.png` (view it to choose).
  Each panel has `bbox`, `centroid`, `region` (front|rear|side|pillar) and `upright_rotate` (CCW degrees that make
  content read upright when the car is seen from its natural side: hood/front 180, left-column sides +90,
  right-column sides -90, rear 0). The atlas is cut into pieces: anything crossing a panel edge is cropped, so put
  key art/text inside panels (use `clip`, `panel`, or `span`).

### Panel placement (text, image, svg)
`"panel": 6` or `"panel": [6, 7]` centres the layer on each listed panel (one copy per panel) and, unless `rotate` is
given, rotates it by that panel's `upright_rotate` so it reads upright on the car (left and right sides come out
mirrored in orientation, both upright). `"span": true` merges the listed panels into one virtual panel
(union bbox), e.g. `"panel": [6, 10], "span": true` for front door + rear door of one side (model3-2024-base). `panel_fill` (text 0.8,
image/svg 1.0) is the fraction of the panel extent used. Text auto-shrinks until >=94% of it lies inside the panel shape.
Explicit `rotate` always wins. On model3-2024-base the biggest side areas are 6+10 (left column) and 7+9 (right
column); 1 and 5 are the front and rear bumpers; 2 the hood. Per-model ids: `references/panel-guide.md`.

**Region selectors (portable across models).** Instead of ids, `panel` accepts `"hood"`, `"trunk"`,
`"largest"`, `"front"`, `"rear"`, `"side"`, `"side_all"`, `"pillar"` (or a list of them). `"side_all"` is every
side panel, merged into one group per side of the car, for panoramic art. `"hood"` / `"trunk"` pick the
hood / trunk-or-liftgate (the front / rear panel nearest the canvas centre) — use these for emblems and words.
`"front"` / `"rear"` pick the largest front / rear panel, which is usually the **bumper** (curved: patterns, not
text). `"side"` yields one panel per car side (mirrored, both upright). With `"span": true` a selector merges all
similar-sized panels of the group. Prefer selectors in reusable specs; absolute `position`/`center`/`box`
coordinates are model-specific and must be re-placed when the spec is rendered for another model (check `panels_overlay.png`).

## Layer types

### solid
`color`.

### gradient
`kind`: `linear` (default) | `radial` | `conic`; `stops: [[color, pos0..1], ...]` (or `colors: [...]` evenly spaced);
`angle` deg (linear: 0 = left to right, 90 = top to bottom; conic: start angle); `center` (default canvas centre);
`radius` (radial, default reaches the farthest corner). Stops may carry alpha (`"#0000"` to `"#000a"` = vignette).

### noise (opaque fractal fields; colours may carry alpha)
Common: `colors` (ramp), `scale` px feature size, `octaves`, `contrast`, `seed`, `bg`.
| kind | defaults |
|---|---|
| `clouds` | colors `[#3b6fb6, #fff]`, scale 220, octaves 5, contrast 1.6. Use `["#ffffff00","#ffffff"]` for white clouds over anything |
| `nebula` | colors `[#05010f dark floor, #3b1a8c, #c2307f, #ff8a3d, #4cd0ff]`, scale 280, octaves 6, contrast 1.0 (intensity). Best on dark, use `screen` |
| `marble` | colors `[#f6f3ee, #9a9aa6, #23232b]`, scale 320, `turbulence` 5, `angle` 35, contrast 1 (vein sharpness) |
| `camo` | colors `[#4b5320, #8a8d5b, #2e3319, #c2b280]` (hard-edged blotches, equal share), scale 120, octaves 3 |

### pattern (transparent unless `bg`; every kind looks good with just `kind`)
Common keys: `colors`, `density` (1 = default amount, scales item count), `count` (exact item count), `size` (px, per
kind), `angle`, `seed`, `bg` (fill colour under the pattern).
| kind | specifics (default) |
|---|---|
| `stars` | flat star polygons. `size` 26 (outer radius), `points` 5, `inner_ratio` 0.45; colours gold/white/pink |
| `starfield` | thousands of pin stars + glowing medium stars + a few spiked bright stars. `size` 5 (bright-star scale); white-ish tints; put on dark, normal blend |
| `dots` | random circles, `size` 14, party palette |
| `polka` | staggered dot lattice, `spacing` 56, `radius` 0.3*spacing, `angle` 20, colours alternate |
| `halftone` | dot grid whose dots grow along a fade. `spacing` 18, `angle` 45 (screen), `fade` `linear`\|`radial`, `fade_angle` 90, `center`, `invert`, `max_radius` 1; 2+ colours become a colour ramp along the fade |
| `stripes` | `width` 40, `angle` 45, `offset`, colours cycle (default pink/white) |
| `checker` | `size` 64, `angle` 0, 2 colours |
| `hex` | honeycomb: `size` 44 (cell radius), `line` 2.5, `line_color` `#7fd1ff`, `angle`; cells random from `colors` (blue shades) |
| `confetti` | rects, discs, squiggles, triangles. `size` 20, party palette |
| `bokeh` | soft translucent light discs with brighter rims. `size` 70 (max radius); use `screen` |
| `balloons` | shaded balloons with knots, highlights, wavy strings. `size` 80 (radius), `string_length` 2.6, `string_color` |
| `hearts` | glossy hearts, `size` 34, pinks/reds |
| `sparkles` | 4-point glowing twinkles, `size` 22, white/gold/pink/ice; use `screen` |
| `rays` | sunburst wedges. `rays` 24, `center`, `angle` offset, `fade` 0-1 (alpha falloff to the edge); colours cycle, a single colour alternates with transparent. Use alpha colours like `"#ffffff30"` |
| `carbon` | carbon-fibre twill. `size` 12 (weave cell), `angle`, `sheen` 0.3; colours `[dark, highlight]` |
| `grid` | `spacing` 64, `line` 2, `major` 0 (every Nth line thicker, drawn in the 2nd colour), `angle`; colours `[line, major]` |
| `waves` | layered filled sine bands. `bands` = number of colours, `amplitude` 36, `wavelength` 340, `start` 0.25 (where the first band begins, 0-1), `angle` |
| `lightspeed` | hyperspace streaks from `center`. `density`, `width` 1.3, `length` 0.55, `clear_center` px, `glow` 0.35 (centre bloom); use `screen` |
| `clouds_cartoon` | flat puffy clouds with soft outline and shade. `size` 300 (typical width), `outline` 7; colours `[fill, shade, outline]` |

### shape
`kind`: `rect` (`box`, `corner` radius) | `ellipse` (`box` or `center`+`radius` number/[rx,ry]) | `polygon` (`points`) |
`star` (`center`, `radius`, `points_n` 5, `inner_ratio` 0.45) | `line` (`points` polyline or `from`/`to`, `width` 6,
round caps) | `ring` (`center`, `radius` outer, `width` thickness). Style: `fill` (also `color`), `stroke: {color, width}`,
`rotate` deg CCW about the shape centre, `blur` px (soften edges), `glow: {color, radius 20, strength 1}` (soft halo,
colour defaults to fill). A glowing beam = coloured wide line with `blur` + narrow white line on top.

### text
`text` (`\n` for lines), `font` alias `sans|sans-bold|serif|serif-bold|mono|display|rounded` or a TTF/TTC path
(default `sans-bold`), `color` (or `gradient: [top, bottom, ...]`), `stroke {color, width}`,
`shadow {color, offset [dx,dy], blur}`, `glow {color, radius, strength}`, `letter_spacing` px, `line_spacing` 1.05,
`align` `left|center|right`. Size/placement, first match wins:
1. `panel` (+ optional `span`, `panel_fill`, `rotate`) - auto-fit, see Panel placement;
2. `fit_box: [x,y,w,h]` - largest size that fits, centred, then `rotate`;
3. `position: [x,y]` + `anchor` (two letters: l|m|r then t|m|b, default `mm`) + `size` px (default 120) + `rotate` deg CCW.
Stroke/shadow/glow sizes are absolute px. Effects offset in the text's own orientation.

### image
`src` (relative to the spec file or absolute), `fit` `cover|contain|stretch|tile|none` (cover), `box` or
`panel`/`span`/`panel_fill`, `rotate`, `mask` `none|circle|rounded|ellipse` (applies to the fitted tile; `corner` px for
rounded), `feather` px edge softening, `remove_bg` (flood-fill from the border, drops the near-uniform background
colour; `tolerance` 28), `tint` colour (+ `tint_strength` 0-1, default 1: recolours via luminance, ideal for white logos).
Do not use copyrighted logos or characters.

**Panel-filling art (image/svg)**: `"fill_panel": true` covers the whole panel (group) and cuts the art
along its outline instead of fitting it inside. `"image_front": "left"|"right"` declares which way the art
faces; it is mirrored on panels where the car's front is the other way (never use it on art containing
lettering). For `fit: "cover"`, `"focus": [fx, fy]` (0-1) moves the crop window. Used by AI image mode
(`references/ai-image-mode.md`).

### svg
`src` file (or `"lib:<name>"` for a bundled component from `assets/illustrations/`, e.g.
`"lib:ringed_planet"`; see that folder's README for names and recolour roles) or `inline` markup, `box` (default full canvas) or `panel`/`span`, and `recolor`: a map of
hex colours to replace, e.g. `{"#3a7bd5": "#ff2a6d"}` (the library README lists each component's
colour roles). Rendered by the built-in renderer (cairosvg or Chrome are used if present).

## Tips
- The file must end < 1 MB: `finalize` first drops low bits of RGB (smooth), and only quantises to a palette for very
  noisy art. If you see banding, lower noise contrast/density instead.
- Keep contrast high; the car is seen small. Always read `review/<stem>_check.png` (seams in red, panel ids, F/R =
  front/rear region).
- Front/hood art looks **upside-down on the flat PNG** — that is correct (it reads upright on the car). Tell the user
  so they don't think it's a bug.
- **Text on the sides.** `"panel": "side"` puts one copy on each side. `"span": true` with ids of the front + rear
  door of one side (e.g. `[6, 10]` and `[7, 9]` on model3-2024-base) runs one phrase across both doors: they are
  neighbours on the car, so letters simply cross the door gap. Never span panels that are not adjacent on the car.
- **Unreadable text is never drawn.** A text copy that ends up < 18 px tall or cut by a seam is skipped with a
  `SKIPPED TEXT` warning — fix it with a line break (`"SUNNY\nTOON TOWN"`), shorter text or a bigger panel.
- **Orientation is verified automatically** for every text/image/svg element (see `review/<stem>_orientation.png`);
  place text with `panel:` and leave `rotate` unset.
- The long rear-quarter panels (see `references/panel-guide.md`) are the best single-panel spots for a full phrase.
- Panel text auto-fits with a 6 px seam margin; `panel_fill` 0.8 (default) is the sensible maximum on curved panels.
- Examples: `assets/examples/birthday_bash.json`, `galactic_saga.json`, `sunny_toon_town.json` (tuned on
  model3-2024-base; layers using absolute coordinates — e.g. the galactic planet — need re-placing on other models).
