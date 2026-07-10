"""Region reconstruction: turn overlapping z-ordered SVG shapes into a clean,
non-overlapping planar map of colored regions.

This is where duplicate/overlapping lines are eliminated:
- vertices are snapped to a precision grid so near-coincident edges become
  exactly coincident and micro-gaps close,
- shapes are overlaid painter's-algorithm style so hidden geometry vanishes
  and adjacent regions share identical boundaries,
- redundant strokes around filled shapes are dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from shapely import set_precision
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiPolygon,
    Polygon,
)
from shapely.ops import unary_union
from shapely.validation import make_valid

from .parser import RGB, Ring, ShapeRecord


@dataclass
class RegionSet:
    """Result of the overlay: non-overlapping fill regions plus standalone
    stroke centerlines."""

    fills: List[Tuple[RGB, MultiPolygon]] = field(default_factory=list)
    strokes: List[Tuple[RGB, List[Tuple[Ring, bool]]]] = field(default_factory=list)
    # every painted shape in document (z) order, BEFORE occlusion differencing:
    # (fill_rgb, geometry, outline_rgb). Used to stack solid hatches like the
    # original SVG paints, which keeps large background fills continuous (no
    # glyph-shaped holes) so drawings stay crisp at far zoom. outline_rgb is
    # usually the fill color, but a large white shape painted over a colored
    # area borrows that color for its outline (sign convention: the white/red
    # boundary is a red line); small white shapes (characters) keep white.
    stack: List[Tuple[RGB, object, RGB]] = field(default_factory=list)
    dropped: int = 0  # shapes fully occluded or degenerate


def _is_whiteish(rgb: RGB) -> bool:
    return all(c >= 240 for c in rgb)


def _signed_area(ring: Ring) -> float:
    area = 0.0
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return area / 2.0


def _polygonal(geom):
    """Keep only the polygonal part of a geometry."""
    if geom.is_empty:
        return None
    if isinstance(geom, Polygon):
        return geom
    if isinstance(geom, MultiPolygon):
        return geom
    if isinstance(geom, GeometryCollection):
        polys = [g for g in geom.geoms if isinstance(g, Polygon) and not g.is_empty]
        if not polys:
            return None
        return unary_union(polys)
    return None


def rings_to_polygon(rings: List[Ring], fill_rule: str):
    """Build a polygon (with holes) from a shape's subpath rings, honoring the
    SVG fill rule. SVG fills open subpaths as if closed, so every ring with
    >= 3 points participates."""
    items = []  # (polygon, orientation sign, |area|)
    for ring in rings:
        if len(ring) < 3:
            continue
        area = _signed_area(ring)
        if area == 0:
            continue
        poly = _polygonal(make_valid(Polygon(ring)))
        if poly is None or poly.is_empty:
            continue
        items.append((poly, 1 if area > 0 else -1, abs(area)))
    if not items:
        return None

    if len(items) == 1:
        return items[0][0]

    if fill_rule == "evenodd":
        result = items[0][0]
        for poly, _, _ in items[1:]:
            result = result.symmetric_difference(poly)
    else:
        # nonzero: rings wound like the outermost ring add, opposite-wound
        # rings cut holes (the overwhelmingly common authoring convention)
        outer_sign = max(items, key=lambda it: it[2])[1]
        pos = unary_union([p for p, s, _ in items if s == outer_sign])
        neg = [p for p, s, _ in items if s != outer_sign]
        result = pos.difference(unary_union(neg)) if neg else pos
        if result.is_empty:  # degenerate winding; fall back to even-odd
            result = items[0][0]
            for poly, _, _ in items[1:]:
                result = result.symmetric_difference(poly)

    return _polygonal(make_valid(result))


def _snap(geom, snap_tol: float):
    if geom is None or snap_tol <= 0:
        return geom
    return _polygonal(make_valid(set_precision(geom, snap_tol)))


def build_regions(
    records: List[ShapeRecord],
    snap_tol: float = 0.01,
    stroke_as_outline: bool = False,
) -> RegionSet:
    """Painter's-algorithm overlay of all shapes in document (z) order."""
    result = RegionSet()
    min_area = max(snap_tol * snap_tol, 1e-12)
    painted: List[List] = []  # mutable [rgb, geom] in paint order

    # size threshold separating "characters/small glyphs" from real white
    # areas: 5% of the drawing's bounding box
    pts = [p for rec in records for ring, _ in rec.subpaths for p in ring]
    if pts:
        xs, ys = [x for x, _ in pts], [y for _, y in pts]
        bbox_area = (max(xs) - min(xs)) * (max(ys) - min(ys))
    else:
        bbox_area = 0.0
    char_area_limit = 0.05 * bbox_area

    def outline_color(rgb: RGB, poly) -> RGB:
        """A large white shape borrows the color it is painted onto for its
        outline; characters (small white shapes) and colored shapes keep
        their own color."""
        if not _is_whiteish(rgb) or poly.area < char_area_limit:
            return rgb
        for prev_rgb, prev_geom in reversed(painted):  # topmost underneath first
            if _is_whiteish(prev_rgb):
                continue
            if prev_geom.intersection(poly).area >= poly.area * 0.5:
                return prev_rgb
        return rgb

    def paint(rgb: RGB, poly) -> None:
        poly = _snap(poly, snap_tol)
        if poly is None or poly.is_empty or poly.area < min_area:
            result.dropped += 1
            return
        result.stack.append((rgb, poly, outline_color(rgb, poly)))
        for entry in painted:
            entry[1] = entry[1].difference(poly)
        painted.append([rgb, poly])

    for rec in records:
        if rec.fill is not None:
            poly = rings_to_polygon([ring for ring, _ in rec.subpaths], rec.fill_rule)
            if poly is None:
                result.dropped += 1
            else:
                paint(rec.fill, poly)

        if rec.stroke is not None:
            if stroke_as_outline:
                # render the stroke as a real filled band painted on top
                lines = [
                    LineString(ring + ([ring[0]] if closed else []))
                    for ring, closed in rec.subpaths
                    if len(ring) >= 2
                ]
                if lines:
                    band = unary_union(lines).buffer(
                        rec.stroke_width / 2.0, cap_style="round", join_style="round"
                    )
                    paint(rec.stroke, band)
            elif rec.fill is None:
                # genuine standalone linework (e.g. road-marking centerline)
                result.strokes.append((rec.stroke, rec.subpaths))
            # else: stroke merely outlines the fill boundary -> drop (this is
            # the classic double-line source)

    # drop shapes that ended up fully hidden under later shapes: their stack
    # entry would add invisible geometry to the DXF
    result.stack = [
        s for s, entry in zip(result.stack, painted) if entry[1].area >= min_area
    ]

    # merge same-color visible regions and clean up slivers
    by_color: Dict[RGB, List] = {}
    for rgb, geom in painted:
        by_color.setdefault(rgb, []).append(geom)
    for rgb, geoms in by_color.items():
        merged = _snap(unary_union(geoms), snap_tol)
        if merged is None:
            continue
        polys = [
            p
            for p in (merged.geoms if isinstance(merged, MultiPolygon) else [merged])
            if p.area >= min_area
        ]
        if polys:
            result.fills.append((rgb, MultiPolygon(polys)))
    return result


