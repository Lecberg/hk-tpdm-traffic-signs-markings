"""Write the reconstructed region map to DXF R2010.

Layout:
- one layer per fill color (``FILL_<name>_<hex>``), true-colored, holding a
  closed LWPOLYLINE per boundary ring -> HATCH boundary pick works first try
- ``STROKE_<name>_<hex>`` layers for standalone linework
- optional ``LINEWORK`` layer with every unique edge exactly once
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

import ezdxf
from ezdxf.lldxf import const

from .geometry import RegionSet
from .parser import RGB, Ring

# small palette of CSS color names for readable layer names
_CSS_COLORS = {
    "BLACK": (0, 0, 0),
    "WHITE": (255, 255, 255),
    "RED": (255, 0, 0),
    "FIREBRICK": (178, 34, 34),
    "CRIMSON": (220, 20, 60),
    "DARKRED": (139, 0, 0),
    "GREEN": (0, 128, 0),
    "LIME": (0, 255, 0),
    "DARKGREEN": (0, 100, 0),
    "BLUE": (0, 0, 255),
    "NAVY": (0, 0, 128),
    "YELLOW": (255, 255, 0),
    "GOLD": (255, 215, 0),
    "ORANGE": (255, 165, 0),
    "BROWN": (165, 42, 42),
    "GRAY": (128, 128, 128),
    "SILVER": (192, 192, 192),
    "CYAN": (0, 255, 255),
    "TEAL": (0, 128, 128),
    "MAGENTA": (255, 0, 255),
    "PURPLE": (128, 0, 128),
    "PINK": (255, 192, 203),
}


def _color_name(rgb: RGB) -> str:
    r, g, b = rgb
    best = min(
        _CSS_COLORS.items(),
        key=lambda kv: (kv[1][0] - r) ** 2 + (kv[1][1] - g) ** 2 + (kv[1][2] - b) ** 2,
    )
    return best[0]


def _layer_name(prefix: str, rgb: RGB) -> str:
    hexcode = "%02X%02X%02X" % rgb
    name = f"{prefix}_{_color_name(rgb)}_{hexcode}"
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


def write_dxf(out_path: str, regions: RegionSet, snap_tol: float = 0.01) -> dict:
    """Write regions to ``out_path``. Returns entity-count stats.

    Output model: shapes are painted in document z-order exactly like the
    source SVG — each shape is a solid HATCH plus its outline, later shapes
    on top (DXF database order = AutoCAD draw order).
    """
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    stats = {"fill_loops": 0, "stroke_lines": 0, "hatches": 0, "layers": 0}

    def ensure_layer(name: str, rgb: Optional[RGB]) -> None:
        if name in doc.layers:
            return
        layer = doc.layers.add(name)
        if rgb is not None:
            layer.rgb = rgb
        stats["layers"] += 1

    def add_loop(points: Ring, layer: str, closed: bool, rgb: Optional[RGB] = None) -> None:
        pts = list(points)
        if closed and len(pts) > 1 and pts[0] == pts[-1]:
            pts = pts[:-1]
        if len(pts) < 2:
            return
        attribs = {"layer": layer, "lineweight": 0}  # hairline, never fattens on zoom
        if rgb is not None:
            # color on the entity itself, so it survives moving to other layers
            attribs["true_color"] = ezdxf.colors.rgb2int(rgb)
        msp.add_lwpolyline(pts, format="xy", close=closed, dxfattribs=attribs)

    def add_hatch(poly, layer: str, rgb: RGB) -> None:
        hatch = msp.add_hatch(dxfattribs={"layer": layer})
        # solid fill in the entity's own color; OUTERMOST style keeps holes open
        hatch.set_solid_fill(rgb=rgb, style=const.HATCH_STYLE_OUTERMOST)
        hatch.paths.add_polyline_path(
            list(poly.exterior.coords), is_closed=True,
            flags=const.BOUNDARY_PATH_EXTERNAL,
        )
        for hole in poly.interiors:
            hatch.paths.add_polyline_path(
                list(hole.coords), is_closed=True,
                flags=const.BOUNDARY_PATH_OUTERMOST,
            )
        stats["hatches"] += 1

    # No region-map hole rings: a white character never gets a contrasting
    # outline, so at far zoom glyphs stay legible instead of being eaten by
    # 1-pixel boundary lines.
    for rgb, geom, outline_rgb in regions.stack:
        lname = _layer_name("FILL", rgb)
        ensure_layer(lname, rgb)
        parts = geom.geoms if hasattr(geom, "geoms") else [geom]
        for poly in parts:
            add_hatch(poly, lname, rgb)
            add_loop(list(poly.exterior.coords), lname, closed=True, rgb=outline_rgb)
            stats["fill_loops"] += 1
            for hole in poly.interiors:
                add_loop(list(hole.coords), lname, closed=True, rgb=outline_rgb)
                stats["fill_loops"] += 1

    for rgb, subpaths in regions.strokes:
        lname = _layer_name("STROKE", rgb)
        ensure_layer(lname, rgb)
        for ring, closed in subpaths:
            add_loop(ring, lname, closed=closed, rgb=rgb)
            stats["stroke_lines"] += 1

    doc.saveas(out_path)
    return stats
