"""Generate tightly-cropped copies of the traffic sign SVGs for map markers.

The gallery SVGs in site/svgs/ share a TPDM drawing-sheet canvas (mostly
567 x 269), with the sign artwork floating in whitespace, so rendering them
directly as map icons letterboxes the sign to a fraction of the marker.
This script computes each sign's real content bounding box (reusing the
svg2dxf parser) and writes a copy with a cropped viewBox to
site/map-icons/, plus an index.json of {code: width/height aspect ratio}.

Usage:
  python scripts/build_map_icons.py [--force]
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from svg2dxf.parser import parse_svg  # noqa: E402

SVG_DIR = Path("site/svgs")
OUT_DIR = Path("site/map-icons")
ROOT_TAG_RE = re.compile(r"<svg\b[^>]*>", re.S)

def content_bbox(svg_path: Path):
    """(minx, miny, w, h) of the drawn content, with a stroke-aware margin.

    parse_svg flips y about the drawing's own bbox, which leaves the overall
    extents identical to SVG coordinates, so the box can be used directly
    as a viewBox.
    """
    result = parse_svg(str(svg_path), curve_tol=0.5)
    xs, ys, max_sw = [], [], 0.0
    for rec in result.records:
        if rec.stroke is not None:
            max_sw = max(max_sw, rec.stroke_width)
        for ring, _ in rec.subpaths:
            for x, y in ring:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    margin = max_sw / 2 + 0.01 * max(max(xs) - min(xs), max(ys) - min(ys))
    minx, miny = min(xs) - margin, min(ys) - margin
    w = max(xs) - min(xs) + 2 * margin
    h = max(ys) - min(ys) + 2 * margin
    return minx, miny, w, h


def crop_svg(text: str, box) -> str:
    """Replace the root <svg> tag's width/height/viewBox with the crop box."""
    minx, miny, w, h = box
    def rewrite(m):
        tag = m.group(0)
        tag = re.sub(r'\s(width|height|viewBox)="[^"]*"', "", tag)
        return tag[:4] + ' width="%.2f" height="%.2f" viewBox="%.2f %.2f %.2f %.2f"' % (
            w, h, minx, miny, w, h) + tag[4:]
    return ROOT_TAG_RE.sub(rewrite, text, count=1)


def main():
    force = "--force" in sys.argv
    OUT_DIR.mkdir(exist_ok=True)
    aspects = {}
    done = skipped = failed = 0
    for svg_path in sorted(SVG_DIR.glob("TS_*.svg")):
        out_path = OUT_DIR / svg_path.name
        try:
            box = content_bbox(svg_path)
        except Exception as exc:
            print(f"  {svg_path.name}: parse failed ({exc})")
            failed += 1
            continue
        if box is None:
            print(f"  {svg_path.name}: no drawable content")
            failed += 1
            continue
        aspects[svg_path.stem] = round(box[2] / box[3], 3)
        if not force and out_path.exists() and \
                out_path.stat().st_mtime >= svg_path.stat().st_mtime:
            skipped += 1
            continue
        text = svg_path.read_text(encoding="utf-8")
        out_path.write_text(crop_svg(text, box), encoding="utf-8", newline="\n")
        done += 1

    with open(OUT_DIR / "index.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(aspects, f, separators=(",", ":"), sort_keys=True)
    print(f"{done} written, {skipped} up to date, {failed} failed -> {OUT_DIR}")


if __name__ == "__main__":
    main()
