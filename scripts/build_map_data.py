"""Convert the Transport Department's Digitized Traffic Aids Drawings
"Traffic Sign Abbreviation point" KML layer (DTAD_TS_ABV_PT) into compact
JSON for the map page.

Source dataset (open data, updated monthly):
  https://static.data.gov.hk/td/traffic-aids-drawings-v2/DTAD_TS_ABV_PT.kmz

Usage:
  python scripts/build_map_data.py path/to/doc.kml site/map-data

Output: one JSON file per grid cell (0.05 deg), each an array of
[code, lon, lat, angle] rows, plus an index.json listing cells and counts.
Coordinates are rounded to 5 decimal places (~1 m).
"""
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

CELL = 0.05  # degrees; HK spans ~1 deg x ~0.6 deg -> a few hundred cells max

SIGN_RE = re.compile(r"Sign ID</td>\s*<td>([^<]+)</td>", re.S)
ANGLE_RE = re.compile(r"Angle</td>\s*<td>([^<]+)</td>", re.S)
COORD_RE = re.compile(r"<coordinates>\s*([0-9.\-]+),([0-9.\-]+)")


def cell_key(lon: float, lat: float) -> str:
    return f"{math.floor(lon / CELL)}_{math.floor(lat / CELL)}"


def parse(kml_path: Path):
    """Stream the KML, yielding (code, lon, lat, angle) per placemark."""
    buf = []
    in_pm = False
    with open(kml_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if "<Placemark" in line:
                in_pm = True
                buf = []
            if in_pm:
                buf.append(line)
            if "</Placemark>" in line and in_pm:
                in_pm = False
                text = "".join(buf)
                m_sign = SIGN_RE.search(text)
                m_coord = COORD_RE.search(text)
                if not (m_sign and m_coord):
                    continue
                code = m_sign.group(1).strip()
                # TSSEPA is a drawing separator annotation, not a sign;
                # <Null> entries carry no code at all.
                if code == "TSSEPA" or "Null" in code:
                    continue
                lon = float(m_coord.group(1))
                lat = float(m_coord.group(2))
                m_angle = ANGLE_RE.search(text)
                angle = None
                if m_angle:
                    raw = m_angle.group(1).strip()
                    if raw and "Null" not in raw:
                        try:
                            angle = round(float(raw), 1)
                        except ValueError:
                            pass
                yield code, round(lon, 5), round(lat, 5), angle


def main():
    kml_path = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    cells = defaultdict(list)
    total = 0
    for code, lon, lat, angle in parse(kml_path):
        cells[cell_key(lon, lat)].append([code, lon, lat, angle])
        total += 1
        if total % 20000 == 0:
            print(f"  parsed {total}...", flush=True)

    index = {}
    for key, rows in sorted(cells.items()):
        rows.sort(key=lambda r: (r[0], r[1], r[2]))
        with open(out_dir / f"{key}.json", "w", encoding="utf-8", newline="\n") as f:
            json.dump(rows, f, separators=(",", ":"), ensure_ascii=False)
        index[key] = len(rows)

    with open(out_dir / "index.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump({"cell": CELL, "total": total, "cells": index},
                  f, separators=(",", ":"))
    print(f"{total} signs -> {len(index)} cells in {out_dir}")


if __name__ == "__main__":
    main()
