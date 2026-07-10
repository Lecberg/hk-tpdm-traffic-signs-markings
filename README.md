# svg2dxf — clean SVG → DXF for traffic signs & road markings

Converts SVG traffic signs / road markings into DXF that arrives **already
colored** — every shape is a solid fill with a clean outline, with **no
doubled or overlapping lines**, correct at any zoom level in AutoCAD.

Instead of translating SVG paths one-by-one (the cause of doubled lines in
generic converters), it repaints the drawing the way the SVG renders:

1. **Parse & flatten** — all transforms applied, curves adaptively flattened.
2. **Snap** — vertices snapped to a grid, closing micro-gaps and making
   near-coincident edges exactly coincident.
3. **Painter's-algorithm overlay** — shapes stack in z-order; fully hidden
   geometry is removed, and strokes that merely outline a filled shape (the
   classic double line) are dropped.
4. **Write DXF** — per shape, a solid HATCH plus its closed LWPOLYLINE
   outline in the same color, hairline weight, stacked in drawing order on
   true-color layers (`FILL_RED_C1121F` etc.). Entities carry their own
   colors, so moving them to your own layers never changes how they look.
   Large white areas painted on a color take that color for their outline;
   small white shapes (characters) keep white outlines so text stays legible
   when zoomed far out.

## Install

```
pip install -e .
```

## Web interface (easiest)

Double-click **`start_converter.bat`** — a local server starts and your
browser opens at `http://127.0.0.1:8517`. Drop an SVG, click
**Convert & Download**, and the DXF downloads. Advanced options (tolerances,
scale) are in the collapsible panel. Everything runs locally;
files never leave your PC. (Equivalent command: `python -m svg2dxf.webapp`.)

## Command line

```
svg2dxf sign.svg                    # -> sign.dxf next to the input
svg2dxf signs_folder/ -o out/       # batch convert every .svg in a folder
```

Options:

| Option | Default | Meaning |
|---|---|---|
| `--curve-tol` | 0.05 | max curve-flattening error (SVG units); smaller = smoother |
| `--snap-tol` | 0.01 | vertex snap grid; raise it if your SVGs have sloppier gaps |
| `--scale` | 1.0 | multiply coordinates (e.g. px → mm) |
| `--stroke-as-outline` | off | turn strokes into filled bands (buffered by stroke width) |
| `-v` | off | print per-file warnings (skipped text elements, etc.) |

Standalone stroked lines (no fill — e.g. road-marking centerlines) are kept
as open polylines on `STROKE_<color>` layers.

Need DWG? Batch-convert the DXF output with the free
[ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter).

## Tests

```
python -m pytest tests/
```

Each test SVG in `tests/data/` reproduces one real failure mode: stroke+fill
double outlines, shared edges between adjacent regions, fully hidden stacked
shapes, and filled paths with micro-gaps.

## Download site (`site/`)

A static gallery of all TPDM signs (`svgs/`) with direct SVG / DXF downloads
— searchable by code, filterable by traffic signs vs road markings. No
server logic; deployable to any static host (GitHub Pages, Cloudflare Pages).

Regenerate after changing `svgs/` or the converter:

```
python scripts/build_site.py          # converts only new/changed files
python scripts/build_site.py --force  # reconvert everything
```

Preview locally: `python -m http.server 8618 --directory site`
