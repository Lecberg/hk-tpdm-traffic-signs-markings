"""Bounded geographic queries over the site's split-cell data."""

import hashlib
import json
import math
from collections import Counter
from functools import lru_cache
from pathlib import Path


def distance_km(lat1, lon1, lat2, lon2):
    a, b = math.radians(lat1), math.radians(lat2)
    da, db = b - a, math.radians(lon2 - lon1)
    h = math.sin(da / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(db / 2) ** 2
    return 6371.0088 * 2 * math.asin(min(1, math.sqrt(h)))


class MapData:
    def __init__(self, directory):
        self.directory = Path(directory)
        raw = (self.directory / "index.json").read_bytes()
        self.index = json.loads(raw)
        digest = hashlib.sha256()
        for path in sorted(self.directory.glob("*.json")):
            digest.update(path.name.encode("utf-8"))
            digest.update(path.read_bytes())
        self.revision = digest.hexdigest()[:12]

    @lru_cache(maxsize=12)
    def _read(self, key):
        rows = json.loads((self.directory / (key + ".json")).read_text(encoding="utf-8"))
        if not isinstance(rows, list) or any(
            not isinstance(row, list) or len(row) != 4 or
            not isinstance(row[0], str) or
            not all(isinstance(v, (int, float)) and math.isfinite(v) for v in row[1:3]) or
            (row[3] is not None and (not isinstance(row[3], (int, float)) or not math.isfinite(row[3])))
            for row in rows
        ):
            raise ValueError("malformed map cell")
        return rows

    def query(self, bounds, limit=200, code=None, center=None, radius_km=None):
        south, west, north, east = bounds
        cell = self.index["cell"]
        expected = []
        for x in range(math.floor(west / cell), math.floor(east / cell) + 1):
            for y in range(math.floor(south / cell), math.floor(north / cell) + 1):
                key = f"{x}_{y}"
                if key not in self.index["cells"]:
                    continue
                split = self.index.get("splits", {}).get(key)
                if not split:
                    expected.append(key)
                    continue
                width = cell / split["n"]
                for i in range(split["n"]):
                    for j in range(split["n"]):
                        part = f"{i}-{j}"
                        if part not in split["parts"]:
                            continue
                        sw, se = (x * cell + i * width, x * cell + (i + 1) * width)
                        ss, sn = (y * cell + j * width, y * cell + (j + 1) * width)
                        if se >= west and sw <= east and sn >= south and ss <= north:
                            expected.append(f"{key}_{part}")
        rows, missing = [], []
        for key in expected:
            try:
                part = self._read(key)
            except (OSError, ValueError, json.JSONDecodeError):
                missing.append(key)
                continue
            for row in part:
                item_code, lon, lat, angle = row
                if not (west <= lon <= east and south <= lat <= north):
                    continue
                if code and item_code.upper() != code.upper():
                    continue
                if center and distance_km(center[0], center[1], lat, lon) > radius_km:
                    continue
                rows.append({"code": item_code, "longitude": lon, "latitude": lat, "angle": angle})
        rows.sort(key=lambda item: (item["code"], item["latitude"], item["longitude"],
                                    -1 if item["angle"] is None else item["angle"]))
        counts = dict(sorted(Counter(row["code"] for row in rows).items()))
        return {"matched_total": len(rows), "code_counts": counts, "returned_records": rows[:limit],
                "truncated": len(rows) > limit, "data_complete": not missing,
                "missing_cells": missing[:20], "query_scope": {"bounds": bounds,
                "center": center, "radius_km": radius_km, "code": code},
                "dataset_revision": self.revision}
