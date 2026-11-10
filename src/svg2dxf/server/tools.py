"""The lookups the search agent's model can call, and their guardrails.

The model never passes coordinates. ``resolve_place`` gives each place a
handle such as ``p1``, and ``find_nearby_signs`` only accepts handles that
were issued in this session, plus ``current`` (the search now on the map)
and ``map_point`` (the selected pin or the map centre) when the page sent
them. A bad argument comes back to the model as an error it can fix; it
never fails the turn.
"""

import json
import math
import re

from .catalog import normalize_code, normalize_text

MAX_CHOICES = 10
CODE = re.compile(r"(TS|RM)[\s_-]?\d+[A-Z]?", re.I)
COUNT_NOTE = "Counts are surveyed records, not necessarily unique physical signs."


def _function(name, description, properties, required):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties,
                       "required": required, "additionalProperties": False}}}


TOOLS = [
    _function("search_signs",
              "Search the drawing catalog by code (TS101, RM1001) or by a short reviewed name "
              "such as 'Stop' or 'No entry' (English or Chinese). Only about 100 drawings have "
              "reviewed names, so a description can find nothing; a code always works. Results "
              "marked exact are the best match.",
              {"query": {"type": "string", "description": "A code or a short name, not a sentence."},
               "category": {"type": "string", "enum": ["ALL", "TS", "RM"],
                            "description": "TS traffic signs, RM road markings, ALL if unspecified."}},
              ["query", "category"]),
    _function("get_sign", "Get one drawing by its catalog code, with its reviewed name and downloads.",
              {"code": {"type": "string"}}, ["code"]),
    _function("resolve_place",
              "Find a Hong Kong place by name (English or Chinese) and get a place_id for "
              "find_nearby_signs. If several places match, the user picks one and you receive "
              "their choice.",
              {"query": {"type": "string", "description": "A short place name, not a sentence."}},
              ["query"]),
    _function("find_nearby_signs",
              "Count surveyed traffic-sign records within a radius of a known place, with the most "
              "common drawings. Use a place_id from resolve_place, or 'current' or 'map_point' "
              "when the conversation says they are available.",
              {"place_id": {"type": "string"},
               "radius_km": {"type": "number", "description": "0.01 to 5. 500 metres is 0.5."},
               "code": {"type": "string",
                        "description": "One traffic-sign code such as TS101, or empty for all signs."}},
              ["place_id", "radius_km", "code"]),
    _function("choose_drawing",
              "Ask the user to pick one drawing when several catalog drawings fit the request. "
              "You receive the code they chose.",
              {"codes": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 8}},
              ["codes"]),
]

TOOL_NAMES = [tool["function"]["name"] for tool in TOOLS]


class ToolError(Exception):
    pass


class Outcome:
    """What one tool call produced.

    ``model`` is the compact view the model reads, ``cards`` the full results
    for the panel, ``pending`` a choice the user must make first, ``places``
    the place registry after the call, and ``detail`` one line for the trace.
    """

    def __init__(self, model=None, cards=(), pending=None, places=None, detail=""):
        self.model, self.cards, self.pending = model, list(cards), pending
        self.places, self.detail = places, detail


def place_brief(place):
    brief = {"name_en": place.get("name_en", ""), "name_zh_hant": place.get("name_zh_hant", "")}
    if place.get("district_en"):
        brief["district_en"] = place["district_en"]
    if place.get("kind") == "district_center":
        brief["note"] = "District centre point, not a boundary."
    return brief


def register(places, item):
    """Add a place to the registry, reusing the handle of an identical one."""
    for pid, known in places.items():
        if pid.startswith("p") and known.get("name_en") == item.get("name_en") and \
                abs(known["latitude"] - item["latitude"]) < 1e-7 and \
                abs(known["longitude"] - item["longitude"]) < 1e-7:
            return places, pid
    taken = [int(pid[1:]) for pid in places if re.fullmatch(r"p\d+", pid)]
    pid = "p" + str(max(taken, default=0) + 1)
    return {**places, pid: item}, pid


def _allowed(args, keys):
    extra = sorted(set(args) - set(keys))
    if extra:
        raise ToolError("Unexpected argument(s): " + ", ".join(extra) +
                        ". Places are passed as place_id, never as coordinates.")


def _text(args, key, limit=120):
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"{key} must be non-empty text.")
    value = value.strip()
    if len(value) > limit or any(ord(char) < 32 for char in value):
        raise ToolError(f"{key} must be short plain text (at most {limit} characters).")
    return value


class Toolbox:
    def __init__(self, catalog, place_lookup, map_query):
        self.catalog = catalog
        self.place_lookup = place_lookup
        self.map_query = map_query
        self.handlers = {"search_signs": self._search_signs, "get_sign": self._get_sign,
                         "resolve_place": self._resolve_place,
                         "find_nearby_signs": self._find_nearby_signs,
                         "choose_drawing": self._choose_drawing}

    def run(self, name, raw_arguments, places, remaining=None):
        try:
            handler = self.handlers.get(name)
            if not handler:
                raise ToolError(f"Unknown tool {name!r}. Use one of: {', '.join(TOOL_NAMES)}.")
            try:
                args = json.loads(raw_arguments) if str(raw_arguments or "").strip() else {}
            except (TypeError, ValueError):
                raise ToolError("Arguments must be a JSON object.")
            if not isinstance(args, dict):
                raise ToolError("Arguments must be a JSON object.")
            return handler(args, places, remaining)
        except ToolError as error:
            return Outcome({"error": str(error)}, detail="Error: " + str(error))

    # -- catalog --------------------------------------------------------------

    def _sign_brief(self, item):
        brief = {"code": item["code"], "category": item["category"]}
        meta = item.get("metadata") or {}
        if meta.get("name_en"):
            brief["name_en"] = meta["name_en"]
        if meta.get("name_zh_hant"):
            brief["name_zh_hant"] = meta["name_zh_hant"]
        return brief

    def _detail(self, code):
        if not isinstance(code, str) or not CODE.fullmatch(code.strip()):
            raise ToolError("Use a catalog code such as TS101 or RM1001.")
        detail = self.catalog.detail(code.strip())
        if not detail:
            raise ToolError(f"{code.strip()} is not in the catalog. Never guess codes; search first.")
        return detail

    def _search_signs(self, args, places, remaining):
        _allowed(args, ("query", "category"))
        query = _text(args, "query")
        category = args.get("category", "ALL")
        if category not in ("ALL", "TS", "RM"):
            raise ToolError("category must be ALL, TS or RM.")
        result = self.catalog.search(query, 20, category)
        items = []
        for item in result["results"][:10]:
            brief = self._sign_brief(item)
            meta = item.get("metadata") or {}
            names = [meta.get("name_en", ""), meta.get("name_zh_hant", ""),
                     *meta.get("aliases_en", []), *meta.get("aliases_zh_hant", [])]
            brief["exact"] = normalize_code(query) == normalize_code(item["code"]) or any(
                normalize_text(name) == normalize_text(query) for name in names if name)
            items.append(brief)
        model = {"query": query, "matched_total": result["matched_total"], "results": items}
        if not items:
            model["note"] = "No reviewed name matched. Ask the user for a drawing code."
        return Outcome(model, [{"tool": "search_signs", "result": result}],
                       detail=f'{result["matched_total"]} drawing(s) for "{query}"')

    def _get_sign(self, args, places, remaining):
        _allowed(args, ("code",))
        detail = self._detail(args.get("code"))
        model = {**self._sign_brief(detail), "downloads": sorted(detail["downloads"])}
        return Outcome(model, [{"tool": "get_sign", "result": detail}], detail="Drawing " + detail["code"])

    def _choose_drawing(self, args, places, remaining):
        _allowed(args, ("codes",))
        codes = args.get("codes")
        if not isinstance(codes, list) or not 2 <= len(codes) <= 8:
            raise ToolError("codes must list 2 to 8 catalog codes.")
        found = []
        for code in codes:
            detail = self._detail(code)
            if detail["code"] not in [item["code"] for item in found]:
                found.append(detail)
        if len(found) < 2:
            raise ToolError("codes must name at least 2 different drawings.")
        choices = [{"id": str(i), "label": item["code"], "item": item} for i, item in enumerate(found)]
        return Outcome(pending={"kind": "drawing", "question": "Choose the drawing to search for.",
                                "choices": choices},
                       detail=f"{len(found)} drawings fit; waiting for your choice")

    # -- places and the map ---------------------------------------------------

    def _resolve_place(self, args, places, remaining):
        _allowed(args, ("query",))
        query = _text(args, "query")
        try:
            result = self.place_lookup.search(query, remaining)
        except ValueError as error:
            raise ToolError(str(error))
        items = result["results"]
        if not items:
            status = result.get("lookup_status", "no_match")
            message = {"unavailable": "The place lookup service is unavailable.",
                       "rate_limited": "Place lookup is busy. Try again shortly."}.get(
                status, "No place matched. Ask for a more specific name, or suggest selecting a map point.")
            return Outcome({"query": query, "matched_total": 0, "status": status, "message": message},
                           [{"tool": "resolve_place", "result": result}], detail=f'"{query}": {status}')
        term = normalize_text(query)
        exact = [item for item in items if term in (
            normalize_text(item.get("name_en", "")), normalize_text(item.get("name_zh_hant", "")),
            *[normalize_text(alias) for alias in item.get("aliases", [])])]
        if len(items) == 1 or len(exact) == 1:
            item = items[0] if len(items) == 1 else exact[0]
            places, pid = register(places, item)
            return Outcome({"query": query, "place_id": pid, **place_brief(item)}, places=places,
                           detail=f'"{query}" → {item["name_en"]} ({pid})')
        choices = [{"id": str(i), "label": item["name_en"], "item": item}
                   for i, item in enumerate(items[:MAX_CHOICES])]
        return Outcome(pending={"kind": "place", "question": "Choose a location to continue the search.",
                                "choices": choices},
                       detail=f'"{query}" → {len(choices)} places; waiting for your choice')

    def _find_nearby_signs(self, args, places, remaining):
        _allowed(args, ("place_id", "radius_km", "code"))
        pid = args.get("place_id")
        if not isinstance(pid, str) or pid not in places:
            known = ", ".join(places) or "none yet"
            raise ToolError(f"Unknown place_id {pid!r}. Call resolve_place first. Known: {known}.")
        radius = args.get("radius_km")
        if isinstance(radius, bool) or not isinstance(radius, (int, float)) or \
                not math.isfinite(radius) or not 0.01 <= radius <= 5:
            raise ToolError("radius_km must be a number from 0.01 to 5.")
        code = args.get("code") or ""
        drawing = None
        if code:
            drawing = self._detail(code)
            if drawing["category"] != "TS":
                raise ToolError("Surveyed locations exist only for traffic signs (TS). "
                                "Road-marking locations are not available.")
        place = places[pid]
        query = {"latitude": place["latitude"], "longitude": place["longitude"],
                 "radius_km": radius, "limit": 50}
        if drawing:
            query["code"] = normalize_code(drawing["code"])
        result = {**self.map_query(query), "place": place, "drawing": drawing}
        top = []
        for dataset_code, count in sorted(result["code_counts"].items(), key=lambda kv: (-kv[1], kv[0]))[:15]:
            detail = self.catalog.detail(dataset_code)
            entry = {"code": detail["code"] if detail else dataset_code, "count": count}
            name = ((detail or {}).get("metadata") or {}).get("name_en")
            if name:
                entry["name_en"] = name
            top.append(entry)
        model = {"place_id": pid, "place": place.get("name_en", ""), "radius_km": radius,
                 "code": drawing["code"] if drawing else "all traffic signs",
                 "matched_total": result["matched_total"],
                 "distinct_drawings": len(result["code_counts"]), "top_codes": top,
                 "data_complete": result["data_complete"], "note": COUNT_NOTE}
        cards = ([{"tool": "get_sign", "result": drawing}] if drawing else []) + \
            [{"tool": "find_nearby_signs", "result": result}]
        label = f'{result["matched_total"]} records within {radius} km of {place.get("name_en", pid)}'
        return Outcome(model, cards, detail=label + (f", {drawing['code']}" if drawing else ""))

    # -- a user's choice ------------------------------------------------------

    def chosen(self, pending, item, places):
        if pending["kind"] == "place":
            places, pid = register(places, item)
            return Outcome({"place_id": pid, **place_brief(item), "selected_by_user": True},
                           places=places, detail=f'You chose {item["name_en"]} ({pid})')
        return Outcome({**self._sign_brief(item), "selected_by_user": True},
                       [{"tool": "get_sign", "result": item}], detail="You chose " + item["code"])
