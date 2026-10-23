#!/usr/bin/env python3
"""Package skills/tesla-wrap-designer as a portable Agent Skill zip (dist/tesla-wrap-designer.zip).

The zip holds the skill folder at its root (tesla-wrap-designer/SKILL.md), the layout
Claude.ai, the Claude API (/v1/skills) and Agent Skills-compatible tools accept. Tesla's
templates are bundled in assets/templates/, so the skill works without network access.
"""
import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "tesla-wrap-designer"
EXCLUDE_DIRS = {".cache", "__pycache__", ".pytest_cache"}
EXCLUDE_FILES = {".DS_Store"}
MAX_DESC_CLAUDE_AI = 200  # Claude.ai upload limit (open standard allows 1024)
MAX_ZIP_BYTES = 30 * 1024 * 1024


def frontmatter(text: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        sys.exit("SKILL.md has no YAML frontmatter")
    out = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip()
    return out


def check_skill() -> None:
    fm = frontmatter((SKILL / "SKILL.md").read_text(encoding="utf-8"))
    name, desc = fm.get("name", ""), fm.get("description", "")
    problems = []
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) or len(name) > 64:
        problems.append(f"name {name!r} must be lowercase-hyphenated, <= 64 chars")
    if name != SKILL.name:
        problems.append(f"name {name!r} must match folder {SKILL.name!r}")
    if any(w in name for w in ("claude", "anthropic")):
        problems.append("name must not contain reserved words")
    if not desc or len(desc) > MAX_DESC_CLAUDE_AI or "<" in desc:
        problems.append(f"description must be 1-{MAX_DESC_CLAUDE_AI} chars without XML (is {len(desc)})")
    lines = (SKILL / "SKILL.md").read_text(encoding="utf-8").count("\n")
    if lines > 500:
        problems.append(f"SKILL.md is {lines} lines (keep < 500)")
    if problems:
        sys.exit("SKILL.md frontmatter problems:\n  " + "\n  ".join(problems))


def skill_files():
    for p in sorted(SKILL.rglob("*")):
        rel = p.relative_to(SKILL)
        if p.is_file() and not (set(rel.parts) & EXCLUDE_DIRS) and p.name not in EXCLUDE_FILES \
                and p.suffix != ".pyc":
            yield p, rel


FIXED_TIME = (2020, 1, 1, 0, 0, 0)  # constant timestamps keep the zip byte-stable between builds


def write_zip(out: Path, entries) -> None:
    """Deterministic zip: sorted entries, fixed timestamps and permissions."""
    with zipfile.ZipFile(out, "w") as z:
        for src, rel in sorted(entries, key=lambda e: e[1].as_posix()):
            info = zipfile.ZipInfo(f"{SKILL.name}/{rel.as_posix()}", FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, src.read_bytes(), compresslevel=9)


def check_zip(out: Path, entries) -> int:
    """Compare the committed zip's file list and contents with the sources."""
    if not out.exists():
        print(f"{out} is missing - run: python3 tools/build_skill.py")
        return 1
    want = {f"{SKILL.name}/{rel.as_posix()}": src.read_bytes() for src, rel in entries}
    with zipfile.ZipFile(out) as z:
        have = {n: z.read(n) for n in z.namelist()}
    stale = sorted(n for n in want.keys() | have.keys() if want.get(n) != have.get(n))
    if stale:
        print(f"{out} is out of date ({len(stale)} files differ, e.g. {stale[:5]}).\n"
              "Run: python3 tools/build_skill.py  and commit dist/tesla-wrap-designer.zip")
        return 1
    print(f"{out} matches the skill sources ({len(want)} files)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", type=Path, default=ROOT / "dist")
    ap.add_argument("--check", action="store_true",
                    help="verify the committed zip matches the skill sources (used by CI); no build")
    a = ap.parse_args()

    check_skill()
    a.out_dir.mkdir(parents=True, exist_ok=True)
    out = a.out_dir / f"{SKILL.name}.zip"
    entries = list(skill_files())
    missing = [m for m in json.loads((SKILL / "references" / "models.json").read_text())["models"]
               if not (SKILL / "assets" / "templates" / m["id"] / "template.png").exists()]
    if missing:
        sys.exit("missing bundled templates (run tools/update_templates.py): "
                 + ", ".join(m["id"] for m in missing))
    if a.check:
        return check_zip(out, entries)
    write_zip(out, entries)
    size = out.stat().st_size
    if size > MAX_ZIP_BYTES:
        sys.exit(f"{out} is {size:,} bytes; limit is {MAX_ZIP_BYTES:,}")
    print(f"{out}  ({len(entries)} files, {size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
