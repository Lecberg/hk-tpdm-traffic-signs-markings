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

Sign density is wildly uneven - Kowloon holds 26k signs in one cell against a
median of ~600 - so any cell whose file would exceed TARGET_BYTES is split
into an n x n grid of parts written as "<x>_<y>_<i>-<j>.json". index.json
records the factor and the non-empty parts under "splits", letting the map
fetch only the parts actually in view instead of one huge file.
"""
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

CELL = 0.05  # degrees; HK spans ~1 deg x ~0.6 deg -> a few hundred cells max

# Uncompressed ceiling for one file. GitHub Pages gzips JSON at roughly 4.5:1,
# so 200 KB here is about 45 KB on the wire.
TARGET_BYTES = 200_000
MAX_SPLIT = 8  # cap on the n of the n x n split

SIGN_RE = re.compile(r"Sign ID</td>\s*<td>([^<]+)</td>", re.S)
ANGLE_RE = re.compile(r"Angle</td>\s*<td>([^<]+)</td>", re.S)
COORD_RE = re.compile(r"<coordinates>\s*([0-9.\-]+),([0-9.\-]+)")


def cell_key(lon: float, lat: float) -> str:
    return f"{math.floor(lon / CELL)}_{math.floor(lat / CELL)}"


def encode(rows: list) -> str:
    return json.dumps(rows, separators=(",", ":"), ensure_ascii=False)


def partition(rows: list, n: int) -> dict:
    """Bucket one cell's rows into its n x n parts, keyed "<i>-<j>".

    The client repeats this arithmetic to decide which parts to fetch, so the
    two must agree; clamping keeps a point that lands exactly on the cell's
    upper edge inside the last part.
    """
    sub = CELL / n
    parts = defaultdict(list)
    for row in rows:
        lon, lat = row[1], row[2]
        x, y = math.floor(lon / CELL), math.floor(lat / CELL)
        i = min(n - 1, max(0, int((lon - x * CELL) / sub)))
        j = min(n - 1, max(0, int((lat - y * CELL) / sub)))
        parts[f"{i}-{j}"].append(row)
    return parts


def split_factor(rows: list) -> int:
    """Smallest n whose largest part fits TARGET_BYTES (1 = no split).

    Density within a cell is itself uneven, so this measures the actual parts
    rather than assuming an even spread.
    """
    if len(encode(rows)) <= TARGET_BYTES:
        return 1
    for n in range(2, MAX_SPLIT + 1):
        parts = partition(rows, n)
        if max(len(encode(p)) for p in parts.values()) <= TARGET_BYTES:
            return n
    return MAX_SPLIT


def write_cells(cells: dict, out_dir: Path) -> tuple:
    """Write every cell (splitting the dense ones) and return (index, splits)."""
    index, splits = {}, {}
    for key, rows in sorted(cells.items()):
        rows.sort(key=lambda r: (r[0], r[1], r[2]))
        index[key] = len(rows)
        n = split_factor(rows)
        if n == 1:
            write_json(out_dir / f"{key}.json", rows)
            continue
        parts = partition(rows, n)
        for part_id, part_rows in sorted(parts.items()):
            write_json(out_dir / f"{key}_{part_id}.json", part_rows)
        splits[key] = {"n": n, "parts": {p: len(r) for p, r in sorted(parts.items())}}
        print(f"  split {key}: {len(rows)} signs -> {n}x{n}, "
              f"{len(parts)} parts, largest "
              f"{max(len(encode(r)) for r in parts.values()) // 1024} KB", flush=True)
    return index, splits


def write_json(path: Path, data) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, separators=(",", ":"), ensure_ascii=False)


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

    index, splits = write_cells(cells, out_dir)

    write_json(out_dir / "index.json",
               {"cell": CELL, "total": total, "cells": index, "splits": splits})
    print(f"{total} signs -> {len(index)} cells "
          f"({len(splits)} split) in {out_dir}")


if __name__ == "__main__":
    main()
