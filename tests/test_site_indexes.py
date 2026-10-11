"""The browser indexes in site/ must match what scripts/build_site_indexes.py builds."""

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_site_indexes", ROOT / "scripts" / "build_site_indexes.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_published_places_match_data():
    assert read(ROOT / "site" / "places.json") == build.site_places(read(ROOT / "data" / "places.json"))


def test_published_sign_names_match_verified_metadata():
    published = read(ROOT / "site" / "sign-names.json")
    assert published == build.site_sign_names(read(ROOT / "data" / "sign-metadata.json"))
    # Reviewer details are internal and must never reach the public site.
    assert all(set(entry) == {"code", "name_en", "name_zh_hant", "aliases_en", "aliases_zh_hant", "source"}
               for entry in published)


def test_map_code_indexes_match_map_data():
    cells = build.map_code_cells(ROOT / "site" / "map-data")
    assert read(ROOT / "site" / "map-codes.json") == cells
    assert read(ROOT / "site" / "survey-counts.json") == build.survey_counts(cells)
    index = read(ROOT / "site" / "map-data" / "index.json")
    assert sum(sum(counts.values()) for counts in cells.values()) == index["total"]
