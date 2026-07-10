"""Build the static download site: convert svgs/ -> site/dxfs/, copy SVGs,
and write site/index.json for the gallery.

Rerunnable: DXFs newer than their source SVG are skipped (use --force to
reconvert everything).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from svg2dxf.cli import convert_file  # noqa: E402

SVG_SRC = ROOT / "svgs"
SITE = ROOT / "site"
SITE_SVGS = SITE / "svgs"
SITE_DXFS = SITE / "dxfs"

_DIM_RE = re.compile(
    r'viewBox="[\d.eE+-]+\s+[\d.eE+-]+\s+([\d.eE+-]+)\s+([\d.eE+-]+)"'
)


def svg_dimensions(svg_path: Path) -> tuple[float, float]:
    head = svg_path.read_text(encoding="utf-8", errors="replace")[:2000]
    m = _DIM_RE.search(head)
    if m:
        return float(m.group(1)), float(m.group(2))
    return 0.0, 0.0


def _convert(args: tuple[str, str]) -> tuple[str, str]:
    """Worker: convert one file. Returns (svg_name, error_or_empty)."""
    svg, dxf = Path(args[0]), Path(args[1])
    try:
        convert_file(svg, dxf)
        return svg.name, ""
    except Exception as exc:
        return svg.name, f"{type(exc).__name__}: {exc}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="reconvert all DXFs")
    ap.add_argument("--jobs", type=int, default=None, help="parallel workers")
    args = ap.parse_args(argv)

    svg_files = sorted(SVG_SRC.glob("*.svg"))
    if not svg_files:
        print(f"no .svg files in {SVG_SRC}", file=sys.stderr)
        return 1

    SITE_SVGS.mkdir(parents=True, exist_ok=True)
    SITE_DXFS.mkdir(parents=True, exist_ok=True)

    todo = []
    for svg in svg_files:
        dxf = SITE_DXFS / svg.with_suffix(".dxf").name
        if args.force or not dxf.exists() or dxf.stat().st_mtime < svg.stat().st_mtime:
            todo.append((str(svg), str(dxf)))

    print(f"{len(svg_files)} SVGs, {len(todo)} to convert")
    failures: dict[str, str] = {}
    if todo:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            done = 0
            for fut in as_completed(pool.submit(_convert, t) for t in todo):
                name, err = fut.result()
                done += 1
                if err:
                    failures[name] = err
                    print(f"FAIL  {name}: {err}", file=sys.stderr)
                if done % 100 == 0:
                    print(f"  ... {done}/{len(todo)}")

    entries = []
    for svg in svg_files:
        dxf = SITE_DXFS / svg.with_suffix(".dxf").name
        if not dxf.exists():
            continue  # failed conversion -> leave out of the gallery
        dest = SITE_SVGS / svg.name
        if not dest.exists() or dest.stat().st_mtime < svg.stat().st_mtime:
            shutil.copy2(svg, dest)
        code = svg.stem
        w, h = svg_dimensions(svg)
        entries.append(
            {
                "code": code,
                "cat": code.split("_", 1)[0],
                "svg": f"svgs/{svg.name}",
                "dxf": f"dxfs/{dxf.name}",
                "w": w,
                "h": h,
                "svgSize": svg.stat().st_size,
                "dxfSize": dxf.stat().st_size,
            }
        )

    (SITE / "index.json").write_text(
        json.dumps(entries, separators=(",", ":")), encoding="utf-8"
    )
    print(
        f"index.json: {len(entries)} entries "
        f"({sum(1 for e in entries if e['cat'] == 'TS')} TS, "
        f"{sum(1 for e in entries if e['cat'] == 'RM')} RM), "
        f"{len(failures)} failures"
    )
    if failures:
        for name, err in sorted(failures.items()):
            print(f"  FAILED: {name}: {err}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
