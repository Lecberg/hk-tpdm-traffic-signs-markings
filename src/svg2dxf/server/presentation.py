"""Turn checked tool output into the only factual cards shown by chat."""


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
            blocks.append({"type": "map", "matched_total": result["matched_total"],
                           "returned_records": result.get("returned_records", []),
                           "truncated": result["truncated"], "data_complete": result["data_complete"],
                           "missing_cells": result["missing_cells"],
                           "available_drawings": result["available_drawings"],
                           "query_scope": result["query_scope"]})
            scope = result["query_scope"]
            if scope["center"] and scope["radius_km"]:
                actions.append({"type": "open_map", "latitude": scope["center"][0],
                                "longitude": scope["center"][1], "radius_km": scope["radius_km"],
                                "code": scope["code"]})
        elif name == "convert_uploaded_svg":
            blocks.append({"type": "conversion", "download_url": result["download_url"],
                           "stats": result["stats"], "expires_in": result["expires_in"]})
        elif name == "help_or_clarify":
            blocks.append({"type": result["kind"]})
    return blocks, actions
