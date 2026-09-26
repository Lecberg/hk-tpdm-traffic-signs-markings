"""Freeze the current top 100 review queue and official district reference points.

Pass the downloaded Home Affairs boundary JSON as the first argument. The queue
is editorial data only; this script never verifies a sign name.
"""

import json
import sys
from collections import Counter
from pathlib import Path

from shapely.geometry import shape


ROOT = Path(__file__).resolve().parents[1]
SOURCE = "https://www.had.gov.hk/psi/hong-kong-administrative-boundaries/hksar_18_district_boundary.json"
TPDM = "https://www.td.gov.hk/filemanager/en/content_5055/V3_08_2026.pdf"
CHINESE = {
    "Central and Western District": "中西區", "Eastern District": "東區",
    "Southern District": "南區", "Wan Chai District": "灣仔區",
    "Kowloon City District": "九龍城區", "Kwun Tong District": "觀塘區",
    "Sham Shui Po District": "深水埗區", "Wong Tai Sin District": "黃大仙區",
    "Yau Tsim Mong District": "油尖旺區", "Islands District": "離島區",
    "Kwai Tsing District": "葵青區", "North District": "北區",
    "Sai Kung District": "西貢區", "Sha Tin District": "沙田區",
    "Tai Po District": "大埔區", "Tsuen Wan District": "荃灣區",
    "Tuen Mun District": "屯門區", "Yuen Long District": "元朗區",
}


def build_districts(boundary_file):
    boundaries = json.loads(Path(boundary_file).read_text(encoding="utf-8"))
    features = boundaries["features"]
    if len(features) != 18:
        raise ValueError("Expected all 18 districts")
    places_path = ROOT / "data" / "places.json"
    current = json.loads(places_path.read_text(encoding="utf-8"))
    places = [place for place in current if place.get("kind") != "district_center"]
    for feature in features:
        name = feature["properties"]["District"]
        point = shape(feature["geometry"]).representative_point()
        places.append({
            "name_en": name, "name_zh_hant": CHINESE[name],
            "aliases": [name.removesuffix(" District")],
            "latitude": round(point.y, 6), "longitude": round(point.x, 6),
            "kind": "district_center",
            "source": {"url": SOURCE,
                       "name_url": "https://www.had.gov.hk/tc/18_districts/my_map.htm",
                       "method": "point inside official district polygon; reference point, not a boundary"},
        })
    places_path.write_text(json.dumps(places, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_sign_queue():
    site = ROOT / "site"
    entries = {entry["code"]: entry for entry in json.loads((site / "index.json").read_text(encoding="utf-8"))}
    available = {code for code, entry in entries.items() if entry.get("svg") and entry.get("dxf") and
                 (site / entry["svg"]).is_file() and (site / entry["dxf"]).is_file()}
    counts = Counter()
    for path in (site / "map-data").glob("*.json"):
        if path.name != "index.json":
            counts.update("TS_" + row[0][2:] for row in json.loads(path.read_text(encoding="utf-8"))
                          if "TS_" + row[0][2:] in available)
    chosen = sorted(counts, key=lambda code: (-counts[code], code))[:100]
    if len(chosen) != 100:
        raise ValueError("Expected 100 downloadable survey codes")
    existing = {item["code"]: item for item in json.loads((ROOT / "data" / "sign-metadata.json").read_text(encoding="utf-8"))}
    queue_path = ROOT / "data" / "sign-review-queue.json"
    prior = {item["code"]: item for item in json.loads(queue_path.read_text(encoding="utf-8"))} if queue_path.is_file() else {}
    queue = []
    for rank, code in enumerate(chosen, 1):
        old = existing.get(code, {})
        proposal = prior.get(code, {})
        item = {"rank": rank, "code": code, "survey_count": counts[code],
                      "preview": entries[code]["svg"],
                      "downloads": {"svg": entries[code]["svg"], "dxf": entries[code]["dxf"]},
                      "name_en": proposal.get("name_en", old.get("name_en", "")),
                      "name_zh_hant": proposal.get("name_zh_hant", old.get("name_zh_hant", "")),
                      "aliases_en": proposal.get("aliases_en", old.get("aliases_en", [])),
                      "aliases_zh_hant": proposal.get("aliases_zh_hant", old.get("aliases_zh_hant", [])),
                      "source": old.get("source", {"url": TPDM}),
                      "review_status": "verified" if old.get("review_status") == "verified" else "pending_review"}
        if proposal.get("evidence"):
            item["evidence"] = proposal["evidence"]
        if proposal.get("proposal_method"):
            item["proposal_method"] = proposal["proposal_method"]
        queue.append(item)
    (ROOT / "data" / "sign-review-queue.json").write_text(
        json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    folder = ROOT / "docs" / "sign-review-batches"
    folder.mkdir(parents=True, exist_ok=True)
    for batch in range(5):
        subset = queue[batch * 20:(batch + 1) * 20]
        all_verified = all(item["review_status"] == "verified" for item in subset)
        lines = [f"# Sign review batch {batch + 1} of 5", "",
                 ("All 20 entries are verified in the public name index." if all_verified else
                  "Candidates need owner approval of their code, names, and aliases before verification."),
                 "The preview and source remain available for later review.", ""]
        for item in subset:
            code = item["code"]
            lines += [f"## {item['rank']}. {code} — {item['survey_count']} map records", "",
                      f"![{code}](../../site/{item['preview']})", "",
                      f"- English: {item['name_en'] or 'Needs source research'}",
                      f"- 繁體中文：{item['name_zh_hant'] or '待核對來源'}",
                      f"- Aliases: {', '.join(item['aliases_en'] + item['aliases_zh_hant']) or 'None proposed'}",
                      f"- Source: {item['source']['url']}",
                      f"- Review state: {item['review_status']}",
                      f"- [SVG](../../site/{item['downloads']['svg']}) · [DXF](../../site/{item['downloads']['dxf']})", ""]
        (folder / f"batch-{batch + 1:02}.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    build_districts(sys.argv[1])
    build_sign_queue()
