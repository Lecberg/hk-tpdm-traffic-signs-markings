"""Turn checked tool output into the only factual cards the assistant shows.

The model's reply is shown above these cards, but the cards themselves are
built only from tool results.
"""


def present(tool_results):
    blocks, actions = [], []
    seen_signs = set()
    for item in tool_results:
        name, result = item["tool"], item["result"]
        if result.get("error"):
            blocks.append({"type": "notice", "code": result["error"],
                           "message": result.get("message", "The lookup did not finish.")})
        elif name == "search_signs":
            signs = [sign for sign in result["results"] if sign["code"] not in seen_signs]
            seen_signs.update(sign["code"] for sign in signs)
            blocks.append({"type": "signs", "items": signs,
                           "matched_total": result["matched_total"], "truncated": result["truncated"],
                           "coverage": result["coverage"]})
            codes = [sign["code"] for sign in signs]
            if codes:
                actions.append({"type": "show_gallery", "codes": codes})
        elif name in ("get_sign", "get_downloads"):
            if result["code"] in seen_signs:
                continue
            seen_signs.add(result["code"])
            blocks.append({"type": "signs", "items": [result], "matched_total": 1,
                           "truncated": False})
            actions.append({"type": "show_gallery", "codes": [result["code"]]})
        elif name == "resolve_place":
            blocks.append({"type": "places", "items": result["results"],
                           "matched_total": result["matched_total"], "ambiguous": result["ambiguous"],
                           "truncated": result.get("truncated", False),
                           "lookup_status": result.get("lookup_status", "local")})
        elif name in ("find_nearby_signs", "summarize_area"):
            scope = result["query_scope"]
            key = (tuple(scope["center"] or ()), scope["radius_km"], scope["code"])
            # Asking for the same area twice shows it once, where it was last asked.
            for index, old in enumerate(blocks):
                if old["type"] == "map" and old["scope_key"] == key:
                    del blocks[index]
                    break
            actions[:] = [a for a in actions if a.get("scope_key") != key]
            place = result.get("place") or {}
            drawing = result.get("drawing") or {}
            counts = sorted((result.get("code_counts") or {}).items(), key=lambda kv: (-kv[1], kv[0]))
            blocks.append({"type": "map", "scope_key": key, "matched_total": result["matched_total"],
                           "returned_records": result.get("returned_records", []),
                           "truncated": result["truncated"], "data_complete": result["data_complete"],
                           "missing_cells": result["missing_cells"],
                           "available_drawings": result["available_drawings"],
                           "query_scope": scope,
                           "place": {k: place[k] for k in ("name_en", "name_zh_hant", "kind", "source") if k in place},
                           "drawing": {"code": drawing["code"], **{
                               k: drawing["metadata"][k] for k in ("name_en", "name_zh_hant")
                               if k in (drawing.get("metadata") or {})}} if drawing else None,
                           "code_counts": [{"code": code, "count": count} for code, count in counts[:10]]})
            if scope["center"] and scope["radius_km"]:
                actions.append({"type": "open_map", "scope_key": key, "latitude": scope["center"][0],
                                "longitude": scope["center"][1], "radius_km": scope["radius_km"],
                                "code": scope["code"], "place": blocks[-1]["place"] or None})
    for item in blocks + actions:
        item.pop("scope_key", None)
    return blocks, actions
