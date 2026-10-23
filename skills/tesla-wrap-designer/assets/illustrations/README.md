# Illustration library

Twelve original, transparent-background vector components, hand-built for the skill's pure-Python
renderer (`scripts/wrapkit/minisvg.py`). Each is shaded (base, shadow, highlight, rim/glow), drawn upright
and readable at ~150 px. Each file opens with a header comment mapping every hex colour to a role;
recolour by find/replace of those hex values (keep the case). Gradient stop colours use the same hexes.

| File | Aspect | Recolour roles (hex) | Best placement | Suggested panel_fill |
|---|---|---|---|---|
| ringed_planet | 1:1 | PLANET_LIGHT #ffd9a8, PLANET #ee8a4c, PLANET_DARK #5c2447, BAND #b8452f, RING_LIGHT #fff1d6, RING #e0a868, RING_DARK #8c5a42, GLOW #ffb98a | hood, rear quarter | deep navy / near-black (#0b0f1a) |
| starfighter | 1:1 | HULL_LIGHT #e8eef7, HULL #aab6c8, HULL_DARK #4a566e, ACCENT #ff4d3d, ACCENT_DARK #a3201a, CANOPY #59d4ff, ENGINE_GLOW #7fe8ff, OUTLINE #1c2336 | hood (nose forward), roof | dark slate / space black |
| energy_blade | 1:2 | BEAM_CORE #ffffff, BEAM #38e8ff, BEAM_GLOW #0a8bff, METAL_LIGHT #e6ebf2, METAL #8a94a8, METAL_DARK #2a3144, GRIP #1a1f2e, TRIM #ffb020 | door / side panel (tall) | dark; glow needs a dark ground |
| sparkle_burst | 1:1 | STAR_LIGHT #ffffff, STAR #ffe27a, STAR_DARK #ff9f1c, GLOW #ffd34d | accent on any panel, behind or beside a hero piece | dark or saturated mid-tone |
| crest_badge | 1:1 | METAL_LIGHT #fff0b3, METAL #e4a82c, METAL_DARK #7a4a0c, FIELD #1b2a5c, FIELD_LIGHT #3a56a8, FIELD_DARK #0a1233, RIBBON #c62d3a, RIBBON_DARK #7d141f | door, trunk (put a number/initials over the empty field, about x160-352 y130-350) | any; works on white or black |
| racing_roundel | 1:1 | RIM_LIGHT #ffffff, RIM #d7dde8, RIM_DARK #6c778c, PRIMARY #e11d2e, PRIMARY_DARK #8a0f1c, STRIPE #ffffff, NUMBER #101522, TICK #101522 | door, hood, rear quarter; change the `<text>` content for another number | white, black, or a contrasting solid |
| balloon_cluster | 1:1 | BALLOON_A #ee2c5a (light #ff8aa6, dark #8a0f33), BALLOON_B #1e90e8 (#8fd7ff, #0b3f8a), BALLOON_C #ffb400 (#ffe58a, #a06000), BALLOON_D #1fb860 (#a8f0b4, #0a6030), STRING #e8e4dc | rear quarter, door | white / pastel / dark (string colour is pale, so avoid white) |
| birthday_cake | 1:1 | SPONGE_LIGHT #ffd9a6, SPONGE #e79a52, SPONGE_DARK #8e4a1e, ICING #ff7fb2 (shade #c42c75), CREAM #fff4e0, CANDLE #4fc3ff, FLAME #ffb400, PLATE #c9d3e6 | hood, trunk | dark teal / navy or deep purple |
| gift_box | 1:1 | BOX_LIGHT #ff8fa3, BOX #e8284f, BOX_DARK #8c0f2c, RIBBON_LIGHT #fff3b0, RIBBON #ffc928, RIBBON_DARK #b87500 (also #a8123a, #ee3a5e, #ffd84a, #e19800 shade steps) | hood, rear quarter | pale or dark neutral |
| cartoon_sun_cloud | 1:1 | SUN_LIGHT #fff1a0, SUN #ffc61a, SUN_DARK #ff8a00, CLOUD_LIGHT #ffffff, CLOUD_SHADE #b8d6f5, OUTLINE #25305e | door, rear quarter | sky blue (#58b6f0) or mint |
| lightning_bolt | 1:1 | BOLT_LIGHT #fffbd0, BOLT #ffe03a, BOLT_DARK #ff8f00, GLOW #38c8ff, OUTLINE #1c1f4a | door, side, rear quarter | dark navy / black |
| heart_burst | 1:1 | HEART_LIGHT #ff9db8, HEART #f0214f, HEART_DARK #7d0a2a, SPARKLE #ffd84a, SPARKLE_DARK #ff9a1a | hood, trunk | pink, cream, or deep plum |

Recolouring tips: a find/replace must also cover the shade steps listed in each file's gradient defs;
swap each family (LIGHT / base / DARK) together so the shading stays coherent.

## Using one in a spec

Use an svg layer with `"src": "lib:<name>"` (resolves to this folder on any install; a full
`<SKILL_DIR>/assets/illustrations/<name>.svg` path also works). The engine rotates the art upright for each
panel. Recolour without editing the file via `"recolor": {"old hex": "new hex"}` (it warns if a hex is not
found; use the exact hexes in the table, lowercase), or paste the file inline after find/replace.

```json
{"type": "svg", "src": "lib:ringed_planet", "panel": "hood", "panel_fill": 0.8,
 "recolor": {"#ee8a4c": "#4aa3ff", "#ffd9a8": "#d6ecff", "#5c2447": "#14275c"}}
```

Place on specific panels with `"panel": "hood"` / `"side"` / panel ids, or in a free box with
`"box": ["x", "y", "w", "h"]` plus `"rotate"`. Recolour a whole family (light / base / dark) together so
the shading stays coherent.

## Renderer notes

All files render with minisvg (`TESLA_WRAP_SVG=mini`) with no warnings and use only supported features
(gradients, clipPath with circles/paths, groups, feGaussianBlur). IDs are prefixed per file
(`rp_`, `sf_`, ...) so several can be inlined in one wrap without collisions. Glows rely on blur, so keep
a dark or saturated panel_fill behind energy_blade, lightning_bolt and sparkle_burst.
