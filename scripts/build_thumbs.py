"""Build site/thumbs/: small WebP rasters of every gallery SVG.

The gallery cards used to render the production SVGs directly. Those are
CAD-derived and carry the full drawing - TS_2714 is 175 KB across 772 paths -
which is far more than a 130 px card can show, and every one of those paths
still costs parse and raster time on the main thread while scrolling.

Each thumb is fitted into THUMB_BOX, which is twice the card's CSS size so the
image stays sharp on a 2x display. Alpha is preserved: the card supplies its
own backdrop (checkerboard for signs, asphalt for road markings), and the RM
drawings are white paint that would vanish on a flattened white canvas.

A thumb is only kept when it is actually smaller than the SVG it replaces.
GitHub Pages gzips SVG but not WebP, so the honest comparison is WebP against
*gzipped* SVG, and by that measure the simple drawings lose badly: RM_1126 is
1.2 KB of gzipped SVG and 16 KB as a raster, because it is a few white lines
spread over a large area. Those keep their SVG, and the codes that do have a
thumb are listed in thumbs/index.json for the gallery to read.

Rerunnable: thumbs newer than their source SVG are skipped (use --force to
rebuild everything).
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import resvg_py
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
SITE_SVGS = SITE / "svgs"
SITE_THUMBS = SITE / "thumbs"

# Card thumb is 182x130 CSS px and the image is capped at 92% of it, so ~167x120.
# Doubled for 2x displays.
THUMB_BOX = (340, 240)

# Lossless, not quality-82 lossy. These are flat-colour drawings with hard
# edges, which is the case lossy WebP handles worst and lossless handles best:
# on the sample it came out 2-3x smaller than lossy at q82 (TS_2714 6.6 KB vs
# 10.4 KB) with no edge artefacts. Quantizing to a 64-colour palette saves a
# further ~12%, which is not worth banding the antialiased edges of drawings
# people consult as a reference.
WEBP_OPTS = {"lossless": True, "method": 6}


def _render(args: tuple[str, str]) -> tuple[str, int, int, str]:
    """Worker: rasterize one SVG, keeping it only if it beats the gzipped SVG.

    Returns (name, svg_wire_bytes, thumb_bytes, error); thumb_bytes is 0 when
    the raster lost and no file was written.
    """
    svg, out = Path(args[0]), Path(args[1])
    try:
        # Only the width is passed: resvg derives the height from the viewBox,
        # so the drawing keeps its aspect ratio rather than being stretched.
        png = resvg_py.svg_to_bytes(svg_path=str(svg), width=THUMB_BOX[0])
        im = Image.open(io.BytesIO(bytes(png)))
        if im.mode != "RGBA":
            im = im.convert("RGBA")
        # Passing width alone can overshoot the box on tall drawings.
        if im.height > THUMB_BOX[1]:
            im = im.resize(
                (max(1, round(im.width * THUMB_BOX[1] / im.height)), THUMB_BOX[1]),
                Image.LANCZOS,
            )
        buf = io.BytesIO()
        im.save(buf, "WEBP", **WEBP_OPTS)
        thumb = buf.getvalue()

        # What the browser would actually pull down for the SVG instead.
        svg_wire = len(gzip.compress(svg.read_bytes(), 9))
        if len(thumb) >= svg_wire:
            out.unlink(missing_ok=True)
            return svg.name, svg_wire, 0, ""

        out.write_bytes(thumb)
        return svg.name, svg_wire, len(thumb), ""
    except Exception as exc:
        return svg.name, 0, 0, f"{type(exc).__name__}: {exc}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="rebuild all thumbs")
    ap.add_argument("--jobs", type=int, default=None, help="parallel workers")
    args = ap.parse_args(argv)

    svg_files = sorted(SITE_SVGS.glob("*.svg"))
    if not svg_files:
        print(f"no .svg files in {SITE_SVGS}", file=sys.stderr)
        return 1

    SITE_THUMBS.mkdir(parents=True, exist_ok=True)

    todo = []
    for svg in svg_files:
        thumb = SITE_THUMBS / (svg.stem + ".webp")
        if (
            args.force
            or not thumb.exists()
            or thumb.stat().st_mtime < svg.stat().st_mtime
        ):
            todo.append((str(svg), str(thumb)))

    print(f"{len(svg_files)} SVGs, {len(todo)} to render")
    failures: dict[str, str] = {}
    kept = rejected = 0
    svg_wire = thumb_wire = 0
    if todo:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            done = 0
            for fut in as_completed(pool.submit(_render, t) for t in todo):
                name, src, out, err = fut.result()
                done += 1
                if err:
                    failures[name] = err
                    print(f"FAIL  {name}: {err}", file=sys.stderr)
                elif out:
                    kept += 1
                    svg_wire += src
                    thumb_wire += out
                else:
                    rejected += 1
                if done % 200 == 0:
                    print(f"  ... {done}/{len(todo)}")

    # Rebuilt from the directory, not from this run, so an incremental build
    # still writes a manifest covering every thumb on disk.
    codes = sorted(p.stem for p in SITE_THUMBS.glob("*.webp"))
    (SITE_THUMBS / "index.json").write_text(
        json.dumps(codes, separators=(",", ":")), encoding="utf-8"
    )

    print(
        f"thumbs: {len(codes)} kept, {rejected} rejected as bigger than "
        f"their gzipped SVG, {len(failures)} failures"
    )
    if kept:
        print(
            f"those {kept} cards: {svg_wire / 1048576:.2f} MB of gzipped SVG "
            f"-> {thumb_wire / 1048576:.2f} MB of WebP "
            f"({svg_wire / max(thumb_wire, 1):.1f}x smaller)"
        )
    if failures:
        for name, err in sorted(failures.items()):
            print(f"  FAILED: {name}: {err}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
