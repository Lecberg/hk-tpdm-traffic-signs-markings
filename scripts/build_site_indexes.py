"""Publish the small indexes the browser needs, since the public site has no backend.

- site/places.json and site/sign-names.json: browser copies of data/places.json
  and the verified names in data/sign-metadata.json (data/ stays the source).
- site/map-codes.json: per drawing, how many surveyed signs fall in each map
  cell, so the map can show one drawing across Hong Kong without loading every
  cell. site/survey-counts.json: the per-drawing totals, for the gallery.

Rerun after editing data/places.json, approving a sign, or rebuilding
site/map-data (tests fail if these drift).
"""

import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLACE_FIELDS = ("name_en", "name_zh_hant", "aliases", "latitude", "longitude", "kind")


def site_places(places):
    published = []
    for place in places:
        item = {key: place[key] for key in PLACE_FIELDS if key in place}
        item["source"] = {"url": place["source"]["url"]}
        published.append(item)
    return published


def site_sign_names(metadata):
    # Only reviewed names are public facts; reviewer details stay in data/.
    return [{"code": entry["code"], "name_en": entry["name_en"],
             "name_zh_hant": entry["name_zh_hant"],
             "aliases_en": entry.get("aliases_en", []),
             "aliases_zh_hant": entry.get("aliases_zh_hant", []),
             "source": {"url": entry["source"]["url"]}}
            for entry in sorted(metadata, key=lambda item: item["code"])
            if entry.get("review_status") == "verified"]


def map_code_cells(map_dir):
    cells = defaultdict(Counter)
    for path in sorted(Path(map_dir).glob("*.json")):
        if path.name == "index.json":
            continue
        cell = "_".join(path.stem.split("_")[:2])   # split parts roll up to their cell
        for row in json.loads(path.read_text(encoding="utf-8")):
            cells[row[0].upper()][cell] += 1
    return {code: dict(sorted(counts.items())) for code, counts in sorted(cells.items())}


def survey_counts(code_cells):
    def site_code(code):
        return "TS_" + code[2:] if code.startswith("TS") else code
    return {site_code(code): sum(counts.values()) for code, counts in code_cells.items()}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def publish(root=ROOT):
    site = root / "site"
    write(site / "places.json", site_places(read(root / "data" / "places.json")))
    write(site / "sign-names.json", site_sign_names(read(root / "data" / "sign-metadata.json")))
    code_cells = map_code_cells(site / "map-data")
    write(site / "map-codes.json", code_cells)
    write(site / "survey-counts.json", survey_counts(code_cells))


if __name__ == "__main__":
    publish()
    print("Wrote site/places.json, sign-names.json, map-codes.json and survey-counts.json")
