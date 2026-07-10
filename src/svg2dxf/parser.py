"""Parse an SVG file into flat, transform-applied polygon/polyline records.

Every shape is reduced to lists of (x, y) points in a single absolute
coordinate space, with curves adaptively flattened, y-axis flipped to CAD
orientation, and the computed fill/stroke colors attached.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from svgelements import (
    SVG,
    Arc,
    Close,
    CubicBezier,
    Line,
    Move,
    Path,
    QuadraticBezier,
    Shape,
    SVGText,
)

RGB = Tuple[int, int, int]
Ring = List[Tuple[float, float]]


@dataclass
class ShapeRecord:
    """One SVG shape, flattened. ``subpaths`` preserves each subpath as
    (points, explicitly_closed)."""

    subpaths: List[Tuple[Ring, bool]]
    fill: Optional[RGB]
    stroke: Optional[RGB]
    stroke_width: float
    fill_rule: str = "nonzero"


@dataclass
class ParseResult:
    records: List[ShapeRecord] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    paths_read: int = 0


def _flatten_segment(seg, tol: float) -> Ring:
    """Adaptively flatten one curve segment to points (excluding its start)."""
    out: Ring = []

    def recurse(t0: float, t1: float, p0, p1, depth: int) -> None:
        # deviation of the curve from the chord, probed at 3 interior points
        dx, dy = p1.x - p0.x, p1.y - p0.y
        chord = math.hypot(dx, dy)
        max_dev = 0.0
        probes = []
        for f in (0.25, 0.5, 0.75):
            t = t0 + (t1 - t0) * f
            pm = seg.point(t)
            probes.append((t, pm))
            if chord < 1e-12:
                dev = math.hypot(pm.x - p0.x, pm.y - p0.y)
            else:
                dev = abs(dy * (pm.x - p0.x) - dx * (pm.y - p0.y)) / chord
            max_dev = max(max_dev, dev)
        if max_dev <= tol or depth >= 16:
            out.append((p1.x, p1.y))
            return
        tm, pm = probes[1]
        recurse(t0, tm, p0, pm, depth + 1)
        recurse(tm, t1, pm, p1, depth + 1)

    recurse(0.0, 1.0, seg.point(0.0), seg.point(1.0), 0)
    return out


def _path_to_subpaths(path: Path, tol: float) -> List[Tuple[Ring, bool]]:
    subpaths: List[Tuple[Ring, bool]] = []
    current: Optional[Ring] = None
    for seg in path:
        if isinstance(seg, Move):
            if current is not None and len(current) >= 2:
                subpaths.append((current, False))
            current = [(seg.end.x, seg.end.y)]
        elif isinstance(seg, Close):
            if current is not None:
                if seg.end is not None:
                    current.append((seg.end.x, seg.end.y))
                if len(current) >= 3:
                    subpaths.append((current, True))
                current = None
        elif current is None:
            continue  # malformed path: segment before any Move
        elif isinstance(seg, Line):
            current.append((seg.end.x, seg.end.y))
        elif isinstance(seg, (CubicBezier, QuadraticBezier, Arc)):
            current.extend(_flatten_segment(seg, tol))
    if current is not None and len(current) >= 2:
        subpaths.append((current, False))
    return subpaths


def _color_rgb(color) -> Optional[RGB]:
    """svgelements Color -> (r, g, b), or None for none/transparent."""
    if color is None or color.value is None:
        return None
    if color.alpha == 0:
        return None
    return (color.red, color.green, color.blue)


def _is_hidden(element) -> bool:
    v = element.values
    if v.get("display") == "none" or v.get("visibility") in ("hidden", "collapse"):
        return True
    try:
        if float(v.get("opacity", 1)) == 0:
            return True
    except (TypeError, ValueError):
        pass
    return False


def parse_svg(source: str, curve_tol: float = 0.05, scale: float = 1.0) -> ParseResult:
    """Parse SVG file into flattened shape records in CAD (y-up) coordinates."""
    result = ParseResult()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        svg = SVG.parse(source, reify=True)

    for element in svg.elements():
        if isinstance(element, SVGText):
            result.warnings.append(
                "text element skipped (convert text to outlines in the SVG editor)"
            )
            continue
        if not isinstance(element, Shape):
            continue
        if _is_hidden(element):
            continue

        fill = _color_rgb(getattr(element, "fill", None))
        stroke = _color_rgb(getattr(element, "stroke", None))
        try:
            if float(element.values.get("fill-opacity", 1)) == 0:
                fill = None
        except (TypeError, ValueError):
            pass
        if fill is None and stroke is None:
            continue

        path = Path(element)
        path.reify()
        subpaths = _path_to_subpaths(path, curve_tol)
        if not subpaths:
            continue

        sw = getattr(element, "stroke_width", None)
        result.records.append(
            ShapeRecord(
                subpaths=subpaths,
                fill=fill,
                stroke=stroke,
                stroke_width=float(sw) if sw else 1.0,
                fill_rule=element.values.get("fill-rule", "nonzero"),
            )
        )
        result.paths_read += 1

    _to_cad_coords(result.records, scale)
    return result


def _to_cad_coords(records: List[ShapeRecord], scale: float) -> None:
    """Flip y (SVG is y-down, DXF is y-up) about the drawing bbox and scale."""
    ys = [y for rec in records for ring, _ in rec.subpaths for _, y in ring]
    if not ys:
        return
    y_ref = max(ys) + min(ys)
    for rec in records:
        rec.subpaths = [
            ([(x * scale, (y_ref - y) * scale) for x, y in ring], closed)
            for ring, closed in rec.subpaths
        ]
        rec.stroke_width *= scale
