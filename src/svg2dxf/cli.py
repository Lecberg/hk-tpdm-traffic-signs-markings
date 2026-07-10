"""Command-line interface: convert one SVG or a folder of SVGs to DXF."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from .dxf_writer import write_dxf
from .geometry import build_regions
from .parser import parse_svg


def convert_file(
    svg_path: Path,
    dxf_path: Path,
    curve_tol: float = 0.05,
    snap_tol: float = 0.01,
    scale: float = 1.0,
    stroke_as_outline: bool = False,
) -> dict:
    """Convert a single SVG file. Returns combined stats dict."""
    parsed = parse_svg(str(svg_path), curve_tol=curve_tol, scale=scale)
    regions = build_regions(
        parsed.records, snap_tol=snap_tol, stroke_as_outline=stroke_as_outline
    )
    stats = write_dxf(str(dxf_path), regions, snap_tol=snap_tol)
    stats.update(
        paths_read=parsed.paths_read,
        regions=sum(len(mp.geoms) for _, mp in regions.fills),
        dropped=regions.dropped,
        warnings=parsed.warnings,
    )
    return stats


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="svg2dxf",
        description="Convert SVG traffic signs / road markings to clean, "
        "fill-ready DXF (deduplicated, closed boundary polylines per colored "
        "region, one layer per color).",
    )
    ap.add_argument("input", type=Path, help="SVG file or folder of SVGs")
    ap.add_argument(
        "-o", "--output", type=Path, default=None,
        help="output DXF file (single input) or folder (batch); defaults next to input",
    )
    ap.add_argument("--curve-tol", type=float, default=0.05,
                    help="max curve-flattening chord error in SVG units (default 0.05)")
    ap.add_argument("--snap-tol", type=float, default=0.01,
                    help="vertex snap grid; closes micro-gaps and makes shared "
                         "edges coincident (default 0.01)")
    ap.add_argument("--scale", type=float, default=1.0,
                    help="multiply all coordinates (e.g. SVG px -> mm)")
    ap.add_argument("--stroke-as-outline", action="store_true",
                    help="convert strokes to filled bands (buffered by stroke width) "
                         "instead of centerlines")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    if args.input.is_dir():
        svg_files = sorted(args.input.glob("*.svg"))
        if not svg_files:
            print(f"no .svg files found in {args.input}", file=sys.stderr)
            return 1
        out_dir = args.output or args.input
        out_dir.mkdir(parents=True, exist_ok=True)
        targets = [(f, out_dir / f.with_suffix(".dxf").name) for f in svg_files]
    elif args.input.is_file():
        out = args.output or args.input.with_suffix(".dxf")
        if out.is_dir() or (args.output and not out.suffix):
            out.mkdir(parents=True, exist_ok=True)
            out = out / args.input.with_suffix(".dxf").name
        targets = [(args.input, out)]
    else:
        print(f"input not found: {args.input}", file=sys.stderr)
        return 1

    failures = 0
    for svg_path, dxf_path in targets:
        try:
            stats = convert_file(
                svg_path, dxf_path,
                curve_tol=args.curve_tol, snap_tol=args.snap_tol, scale=args.scale,
                stroke_as_outline=args.stroke_as_outline,
            )
        except Exception as exc:  # keep the batch going
            failures += 1
            print(f"FAIL  {svg_path.name}: {exc}", file=sys.stderr)
            continue
        print(
            f"OK    {svg_path.name} -> {dxf_path.name}: "
            f"{stats['paths_read']} paths -> {stats['regions']} regions, "
            f"{stats['hatches']} solid fills, {stats['fill_loops']} closed loops"
            + (f", {stats['stroke_lines']} stroke lines" if stats["stroke_lines"] else "")
            + (f", {stats['dropped']} hidden/degenerate shapes removed" if stats["dropped"] else "")
        )
        if args.verbose:
            for w in stats["warnings"]:
                print(f"      warning: {w}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
