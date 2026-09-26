"""Deterministic catalog and reviewed-label search."""

import json
import re
from pathlib import Path


def normalize_code(value):
    return re.sub(r"[\s_-]+", "", str(value)).upper()


def normalize_text(value):
    return re.sub(r"\s+", " ", str(value).casefold()).strip()


class Catalog:
    def __init__(self, site_dir: Path, metadata_path: Path):
        self.site_dir = Path(site_dir)
        entries = json.loads((self.site_dir / "index.json").read_text(encoding="utf-8"))
        self.entries = {entry["code"]: entry for entry in entries}
        self.by_code = {normalize_code(code): code for code in self.entries}
        metadata = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
        if not isinstance(metadata, list):
            raise ValueError("metadata must be a list")
        self.metadata = {}
        for item in metadata:
            if not isinstance(item, dict):
                raise ValueError("metadata entries must be objects")
            code = item["code"]
            if code not in self.entries or code in self.metadata:
                raise ValueError(f"unknown or duplicate metadata code: {code}")
            if item.get("review_status") not in ("verified", "source_checked") or not item.get("source", {}).get("url"):
                raise ValueError(f"metadata must have a review state and source: {code}")
            if not item.get("name_en") or not item.get("name_zh_hant"):
                raise ValueError(f"bilingual names required: {code}")
            for field in ("name_en", "name_zh_hant"):
                if not isinstance(item[field], str):
                    raise ValueError(f"{field} must be text: {code}")
            for field in ("aliases_en", "aliases_zh_hant"):
                if not isinstance(item.get(field, []), list) or any(
                    not isinstance(alias, str) for alias in item.get(field, [])
                ):
                    raise ValueError(f"{field} must be a text list: {code}")
            self.metadata[code] = item

    def _detail(self, code):
        entry = self.entries[code]
        result = {"code": code, "category": entry["cat"],
                  "metadata_status": self.metadata[code]["review_status"] if code in self.metadata else "code_only",
                  "viewbox": {"width": entry.get("w"), "height": entry.get("h")},
                  "downloads": {}}
        for kind in ("svg", "dxf"):
            path = entry.get(kind)
            if path and (self.site_dir / path).is_file():
                result["downloads"][kind] = path
        # Pending review data is kept for editors, but never used as a public fact.
        if code in self.metadata and self.metadata[code]["review_status"] == "verified":
            result["metadata"] = self.metadata[code]
        return result

    def detail(self, query):
        code = self.by_code.get(normalize_code(query))
        return self._detail(code) if code else None

    def search(self, query, limit=20):
        code_query = normalize_code(query)
        text_query = normalize_text(query)
        matches = []
        for code in self.entries:
            normalized = normalize_code(code)
            meta = self.metadata.get(code)
            fields = []
            rank = 99
            if code_query and normalized == code_query:
                rank, fields = 0, ["code"]
            elif meta and meta["review_status"] == "verified" and text_query:
                names = [("name_en", meta["name_en"]), ("name_zh_hant", meta["name_zh_hant"])]
                names += [("aliases_en", a) for a in meta.get("aliases_en", [])]
                names += [("aliases_zh_hant", a) for a in meta.get("aliases_zh_hant", [])]
                fields = [name for name, value in names if normalize_text(value) == text_query]
                if fields:
                    rank = 1
                else:
                    fields = [name for name, value in names if text_query in normalize_text(value)]
                    if fields:
                        rank = 2
            if rank == 99 and code_query and code_query in normalized:
                rank, fields = 3, ["code"]
            if rank != 99:
                matches.append((rank, code, fields))
        matches.sort(key=lambda match: (match[0], match[1]))
        return {"query": query, "matched_total": len(matches), "truncated": len(matches) > limit,
                "results": [{**self._detail(code), "matched_fields": fields}
                            for _, code, fields in matches[:limit]],
                "coverage": {"total_drawings": len(self.entries),
                             "verified_bilingual": sum(item["review_status"] == "verified" for item in self.metadata.values()),
                             "source_checked_bilingual": sum(item["review_status"] == "source_checked" for item in self.metadata.values()),
                             "code_only": len(self.entries) - len(self.metadata)}}
