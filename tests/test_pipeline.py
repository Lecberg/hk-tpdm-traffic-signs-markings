"""End-to-end tests: each synthetic SVG reproduces one real failure mode from
converting traffic-sign SVGs, and we assert the DXF read back with ezdxf is
clean (solid fills stacked in painter order, closed outlines, hidden geometry
removed)."""

import math
from pathlib import Path

import ezdxf
import pytest

from svg2dxf.cli import convert_file

DATA = Path(__file__).parent / "data"


def convert(tmp_path, name, **kwargs):
    dxf_path = tmp_path / f"{name}.dxf"
    stats = convert_file(DATA / f"{name}.svg", dxf_path, **kwargs)
    return ezdxf.readfile(dxf_path), stats


def polylines(doc, layer_prefix=""):
    return [
        e for e in doc.modelspace().query("LWPOLYLINE")
        if e.dxf.layer.startswith(layer_prefix)
    ]


def fill_layers(doc):
    return {l.dxf.name for l in doc.layers if l.dxf.name.startswith("FILL_")}


def canonical_segments(entity, digits=4):
    pts = [(round(x, digits), round(y, digits)) for x, y, *_ in entity.get_points()]
    if entity.closed:
        pts.append(pts[0])
    return {tuple(sorted((pts[i], pts[i + 1]))) for i in range(len(pts) - 1)}


def test_stroked_filled_circle_no_double_outline(tmp_path):
    doc, stats = convert(tmp_path, "stroked_filled_circle")
    # the stroke that merely outlines the fill must be dropped entirely
    assert not [l for l in doc.layers if l.dxf.name.startswith("STROKE_")]
    plines = polylines(doc)
    assert len(plines) == 1
    assert plines[0].closed
    assert stats["regions"] == 1
    assert stats["hatches"] == 1


def test_adjacent_regions_stacked_in_painter_order(tmp_path):
    doc, stats = convert(tmp_path, "adjacent_regions")
    assert len(fill_layers(doc)) == 2  # red + white
    hatches = list(doc.modelspace().query("HATCH"))
    # painter order like the SVG: full red disk first, white disk on top
    # (DXF order = draw order) — the background stays a continuous solid so
    # drawings degrade cleanly at far zoom
    assert len(hatches) == 2
    assert stats["hatches"] == 2
    assert [h.dxf.true_color for h in hatches] == [0xC1121F, 0xFFFFFF]
    for h in hatches:
        assert h.dxf.solid_fill == 1
        assert len(h.paths) == 1  # no adjacency holes punched
    # outlines: one per shape, closed, hairline. The white disk is a LARGE
    # white area painted on red, so its outline borrows the red (sign
    # convention: the white/colored boundary is drawn in the color)
    plines = polylines(doc, "FILL_")
    assert len(plines) == 2 and all(p.closed for p in plines)
    assert [p.dxf.true_color for p in plines] == [0xC1121F, 0xC1121F]
    assert all(p.dxf.lineweight == 0 for p in plines)


def test_stacked_hidden_shape_removed(tmp_path):
    doc, stats = convert(tmp_path, "stacked_shapes")
    layers = fill_layers(doc)
    assert len(layers) == 1  # blue background fully occluded -> gone
    assert all("C1121F" in l for l in layers)
    assert len(doc.modelspace().query("HATCH")) == 1
    plines = polylines(doc)
    assert len(plines) == 1 and plines[0].closed


def test_open_gap_path_closes(tmp_path):
    doc, stats = convert(tmp_path, "open_gap_path")
    plines = polylines(doc)
    assert len(plines) == 1
    assert plines[0].closed
    # no duplicated segment along the former gap edge
    segs = list(canonical_segments(plines[0]))
    assert len(segs) == len(set(segs))


def test_entity_colors_survive_layer_moves(tmp_path):
    # hatches and outlines carry their own true_color (not ByLayer), so
    # moving entities onto other layers keeps their colors
    doc, _ = convert(tmp_path, "adjacent_regions")
    hatches = list(doc.modelspace().query("HATCH"))
    assert hatches
    for h in hatches:
        layer_hex = h.dxf.layer.rsplit("_", 1)[1]
        assert h.dxf.true_color == int(layer_hex, 16)
    for p in polylines(doc, "FILL_"):
        assert p.dxf.hasattr("true_color"), f"{p.dxf.layer} entity is ByLayer"


def test_small_white_characters_keep_white_outline(tmp_path):
    # a small white glyph on a colored panel keeps its white outline; the
    # large white bar borrows the panel color
    svg = tmp_path / "glyph.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">'
        '<rect x="0" y="0" width="200" height="100" fill="#c1121f"/>'
        '<rect x="20" y="40" width="160" height="30" fill="#ffffff"/>'  # big bar
        '<rect x="30" y="10" width="8" height="12" fill="#ffffff"/>'    # glyph
        "</svg>"
    )
    dxf = tmp_path / "glyph.dxf"
    convert_file(svg, dxf)
    doc = ezdxf.readfile(dxf)
    plines = polylines(doc, "FILL_")
    outline_by_area = []
    for p in plines:
        pts = [(x, y) for x, y, *_ in p.get_points()]
        xs, ys = [x for x, _ in pts], [y for _, y in pts]
        outline_by_area.append(
            ((max(xs) - min(xs)) * (max(ys) - min(ys)), p.dxf.true_color)
        )
    outline_by_area.sort()
    glyph, bar, panel = outline_by_area
    assert glyph[1] == 0xFFFFFF  # character stays white
    assert bar[1] == 0xC1121F    # big white bar borrows the red
    assert panel[1] == 0xC1121F  # red panel keeps red


def test_hatch_keeps_intrinsic_holes(tmp_path):
    # a shape whose own fill rule cuts a hole (like a letter counter) must
    # keep that hole in its hatch — only adjacency holes are dropped
    ring = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<path d="M50 5 A45 45 0 1 0 50 95 A45 45 0 1 0 50 5 Z '
        'M50 25 A25 25 0 1 1 50 75 A25 25 0 1 1 50 25 Z" '
        'fill="#c1121f" fill-rule="evenodd"/></svg>'
    )
    svg = tmp_path / "ring.svg"
    svg.write_text(ring)
    dxf = tmp_path / "ring.dxf"
    convert_file(svg, dxf)
    doc = ezdxf.readfile(dxf)
    hatches = list(doc.modelspace().query("HATCH"))
    assert len(hatches) == 1
    assert len(hatches[0].paths) == 2  # exterior + intrinsic hole


def test_curves_are_smooth(tmp_path):
    doc, _ = convert(tmp_path, "stroked_filled_circle")
    pts = [(x, y) for x, y, *_ in polylines(doc)[0].get_points()]
    # circle r=40 flattened at 0.05 chord error needs plenty of vertices
    assert len(pts) > 40
    cx = sum(x for x, _ in pts) / len(pts)
    cy = sum(y for _, y in pts) / len(pts)
    radii = [math.hypot(x - cx, y - cy) for x, y in pts]
    assert max(radii) - min(radii) < 0.2
