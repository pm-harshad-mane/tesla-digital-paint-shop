# Art direction — the quality bar

Every wrap must look like the work of a professional livery designer: bold, intentional,
on-theme and genuinely impressive on the car, never a generic template with a theme name
typed on it. Spec compliance is the floor; **visual impact is the job.**

## 1. Concept before layers

Before writing any JSON, decide (and tell the user in 2–3 lines):

- **Big idea** — one sentence of story. Not "space theme" but *"the car is a starfighter
  breaking out of hyperspace: streaks race from the nose, a glowing planet rises over the
  hood."* Not "birthday" but *"a confetti cannon just went off: bursts explode from the
  doors, balloons float up the rear quarters."*
- **Mood words** (3): e.g. *cinematic, electric, nocturnal* / *joyful, bouncy, candy*.
- **Palette** — 1 dominant (≈60 %), 1–2 supporting (≈30 %), 1 accent (≈10 %, used for the
  focal point and text highlights). Write the hex codes down and stick to them.
- **Focal points** — exactly one hero per view: hood (front view), each side (side view),
  trunk (rear view). Everything else supports them.
- **Motion direction** — flows run nose → tail along the body (streaks, stripes, gradients
  lighten toward the front or rear), so the car looks fast even when parked.

For franchise themes, capture the *feeling* through original art (see
`design-playbook.md → Intellectual property`), so it still reads instantly as that theme.

## 2. Placement map — where impact comes from

Sizes are for 1024×1024 templates; read exact `bbox` sizes in `panels.json`.

| Area | Real estate | Best use |
|---|---|---|
| Hood (`"hood"`) | small (≈ 270–300 × 200–250 px) | ONE bold, simple emblem or short word; `panel_fill` 0.8–0.9. Detailed scenes get lost here |
| Doors (`"side"`, or door ids) | medium, both sides | the main wordmark (1–2 words), mirrored left/right |
| Rear quarters (long strips, see `panel-guide.md`) | tall & long | the side **illustration hero**: a tall emblem, a creature, a blade, a burst. They are the most visible art in the Paint Shop side view; never leave them as plain background |
| Front fenders | small, curved | badges, crests, numbers |
| Trunk / liftgate (`"trunk"`) | medium, sometimes thin | wordmark or badge |
| Bumpers, pillars, mirrors | curved, thin | accents only: colour blocks, stripe ends, glows |

Illustrations and images placed with `panel:` shrink automatically until they sit inside the
panel, so wheel arches and narrow fenders never cut them at a seam. Ask for `panel_fill` 1.0
and let the engine fit it.

**Directional art** (vehicles, arrows, streaks, creatures facing a way): draw the SVG upright as
the viewer should see it, facing right. The engine rotates it upright per panel, but it
does **not** mirror it, so on one side of the car it will face the rear. Check the
orientation sheet: every tile caption shows where the car's front is (`front >`, `< front`,
`front v`, `front ^`). If the art faces the wrong way, use a separate layer for that side with
the SVG mirrored: wrap its content in `<g transform="translate(W,0) scale(-1,1)">`, where W
is the viewBox width.

**Illustration library.** Start illustrated heroes from `assets/illustrations/` (reference a
component with `"src": "lib:<name>"`, or copy its markup into an `inline` layer to recolour it). These are
polished, original components (planet, starfighter, energy blade, crest, roundel, balloons,
cake, gift, sun and cloud, lightning, hearts, sparkle burst). Recolour them to the palette
and combine or extend them; don't place them unchanged on every design.

## 3. Craft rules

**Depth, not flatness.** Build 4–6 visual planes: base field → atmospheric texture (noise,
nebula, clouds at low opacity) → mid-ground motifs → accent shapes → heroes → highlights
(glows, sparkles, specular streaks). A single gradient plus one pattern is never enough.

**Light and glow.** On dark grounds use `blend: "screen"`/`"add"` glows behind heroes, rim
light on illustrations, and a soft vignette toward panel edges to give the body volume.
Glowing elements need a white-hot core + coloured halo (two layers).

**Contrast and hierarchy.** Heroes must pop: value contrast ≥ 2 steps from the background
(dark-on-light or light-on-dark), saturation highest at the focal point, background
textures muted (opacity 0.2–0.5).

**Typography.** Display fonts (`display`, `sans-bold`, `rounded`) only; ALL CAPS or
deliberate title case; generous `letter_spacing` (3–8) for elegance; always a stroke
(4–8 px) or glow/shadow for legibility; optional `gradient` fill for premium feel. Keep
text short — 1–3 words per panel; split long messages across doors/hood/trunk.

**Illustrations (SVG) — drawn to a professional standard.**
- Bold silhouettes that read at thumbnail size; consistent stroke weight (6–12 px at panel
  scale) and rounded joins.
- Shading: at least base colour + shadow + highlight per shape (gradients or overlapping
  shapes), plus a rim light on dark backgrounds.
- A consistent style per design (flat vector, comic ink, neon line art, retro poster…) —
  never mix styles.
- Detail where the eye lands (faces, emblems), simplicity elsewhere.
- No clip-art defaults: no plain circles labelled as planets, no single-path hearts as the
  only motif. Compose illustrations from several shapes with overlap and depth.

**Pattern discipline.** Max 2 pattern families per design; vary scale (big + small) rather
than adding more kinds; keep patterns behind heroes, never competing with text.

**Use the whole car.** Bumpers, pillars, mirrors and fenders get coordinated accents (stripe
continuations, colour blocking, carbon or gradient fades): no forgotten flat panels.
Left/right sides mirror each other in balance (not necessarily identical).

**No boxes or blobs.** A glow clipped to a panel shows the panel's outline as a blob, and a
blur cut at a layer's edge shows a rectangle. Put a hero's glow *inside its SVG* (a radial
gradient that fades to fully transparent before the viewBox edge) so it travels and scales
with the hero. Keep atmospheric glows in full-canvas layers without a `clip`. Give SVGs no
background `<rect>`.

**Colour quality.** Avoid muddy mid-greys and pure #000/#fff fields; use rich darks
(`#0b0f1a`, `#1a0b2e`) and tinted whites (`#fff6e8`). Check that the palette also works when
the car UI renders it small and shaded.

## 4. Variety — no two wraps alike

- Never ship an example spec as-is; examples are scaffolding. Change the concept, palette,
  composition and illustrations to the user's brief and personal details (names, dates,
  favourite things).
- Pick a non-default `seed` per design.
- Offer **2 distinct directions** when the brief is open (e.g. *"cinematic poster"* vs
  *"clean racing livery"*), not two recolours of one layout.

## 5. Self-critique before showing anything

After each render, view the PNG, `review/<stem>_check.png` and
`review/<stem>_orientation.png`, then score honestly (1–5):

| Criterion | 5 looks like |
|---|---|
| Concept clarity | The theme reads in one second, from the side and front |
| Focal hierarchy | One clear hero per view; eye lands on it first |
| Depth & lighting | Layered planes, glows/shadows; nothing looks flat or pasted |
| Craft | Clean edges, consistent illustration style, nothing awkwardly cut at seams |
| Typography | Legible, well-spaced, styled, upright on the car |
| Palette | Harmonious, rich, deliberate accent use; no mud |
| Whole-car coverage | Every visible panel coordinated; no dead areas |
| Wow factor | Something the owner would proudly show off |

**Ship when every score is ≥ 4.** Otherwise name the two weakest criteria, change the spec
to fix them (the biggest wins are usually a stronger hero on the rear quarters, more depth
layers, and a simpler, bolder hood emblem), and re-render. Allow up to **5 render rounds**.
If the bar still isn't met, deliver the best round and say plainly which criteria are below
4 and what would lift them (e.g. the user's own artwork or photo, or a simpler concept).
Never present a draft that hasn't been critiqued, and never inflate the scores.

When delivering, include a 2–3 line design rationale (concept, palette, focal points) so the
user sees the intent, and offer one meaningfully different alternative direction.
