# Tesla Paint Shop wrap rules

Source: https://github.com/teslamotors/custom-wraps (pinned in `models.json → source_ref`).
Re-check the upstream README when Tesla adds models; update `models.json` if it changed.

## Tesla's published requirements

| Requirement | Tesla says | What this skill enforces |
|---|---|---|
| Format | PNG | Real PNG (signature checked), saved RGB / palette, never JPEG renamed |
| Resolution | 512×512 to 1024×1024, "use template size for best results" | **Exactly the template canvas**: 1024×1024 for all models, **1024×768 for Cybertruck**. Any other size shifts the UV mapping |
| File size | ≤ 1 MB | ≤ 1,000,000 bytes (conservative reading of "1 MB") |
| File name | Alphanumeric, `_`, `-`, space; max 30 chars | Same regex; 30 chars **including** `.png` (conservative) |
| Count | Up to 10 from the mobile app + 10 from USB | Warn when a batch exceeds 10 |
| USB | exFAT / FAT32 / MS-DOS FAT / ext3 / ext4 (not NTFS); folder `Wraps` at root; no map/firmware update files on the drive | Included in delivery instructions |
| Mobile app | Tesla app v4.59.0+: Creations → Wrap → Upload | Included in delivery instructions |
| Apply | Toybox → Paint Shop → Wraps tab | Included in delivery instructions |

## Rules learned from the templates

- `template.png` is RGBA. **Opaque pixels = car surface** (body panels in UV layout). Dark
  pixels inside the opaque area are panel outlines. Transparent pixels = not mapped.
- **Any transparent pixel that lands on the car renders black.** The skill therefore paints
  the entire canvas edge-to-edge and saves without an alpha channel. If the user *wants*
  black (e.g. glass-roof look), paint it black explicitly.
- Panels are cut by seams. Art crossing a seam continues on a different, often rotated or
  distant part of the car. Keep critical elements (faces, text, logos) **inside one panel**
  with ≥ 12 px margin from its outline; let backgrounds/patterns flow across seams.
- **Text orientation is verified on every render** (`wrapkit/orientation.py`): each text
  element's rotation must equal the `upright_rotate` of the panel it lands on (±15°), or the
  render fails as UPSIDE-DOWN / SIDEWAYS / OFF-CAR. `review/<stem>_orientation.png` shows each
  element as it appears on the car for a visual confirmation.
- Side panels are laid out rotated in UV space (long axis vertical on most 1024² templates).
  Text on a side panel must be rotated to that panel's `angle_deg` / `long_axis` from
  `panels.json`, or it will appear vertical on the car. Mirror-image left/right panels: text
  that reads correctly on one side may need 180° rotation on the other — verify in the viewer.
- Large pure-black regions look like missing textures in the car UI — the validator warns at
  > 15 % near-black panel area.
- Fine detail < 3 px disappears at the in-car render size; keep strokes ≥ 4 px, text ≥ 40 px
  cap height on large panels.

## Compression

Busy procedural art (noise, starfields) at 1024² RGB is often 1.5–3 MB as lossless PNG.
`finalize.py` walks a ladder that never changes dimensions: optimized RGB PNG → drop low bits (7→6→5-bit RGB, keeps gradients smooth) → 256-colour
quantize with dithering → fewer colours → light denoise + quantize. If the result still
exceeds 1 MB, simplify the design (reduce noise octaves / grain) rather than shrinking it.
