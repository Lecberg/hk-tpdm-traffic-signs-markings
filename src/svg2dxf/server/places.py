"""Bounded, source-backed lookup of Hong Kong location points."""

import json
import math
import threading
import time
from collections import OrderedDict
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pyproj import Transformer

from .catalog import normalize_text


SEARCH_URL = "https://www.map.gov.hk/gs/api/v1.0.0/locationSearch"
HK = (22.1, 113.8, 22.65, 114.5)
MAX_RESULTS = 10
MAX_CACHE = 256
CACHE_SECONDS = 24 * 60 * 60
MAX_CALLS_PER_MINUTE = 30


class PlaceLookup:
    def __init__(self, saved_places):
        self.saved_places = saved_places
        self.transformer = Transformer.from_crs("EPSG:2326", "EPSG:4326", always_xy=True)
        self.cache = OrderedDict()
        self.calls = []
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(2)

    def search(self, query, remaining=None):
        query = query.strip()
        if not query or len(query) > 120 or any(ord(char) < 32 for char in query):
            raise ValueError("Enter a place name of 1–120 characters")
        term = normalize_text(query)
        local = [place for place in self.saved_places if any(
            term in normalize_text(name) for name in
            [place["name_en"], place["name_zh_hant"], *place.get("aliases", [])])]
        if local:
            return self._result(query, local[:20], len(local), "local")

        now = time.monotonic()
        with self.lock:
            cached = self.cache.get(term)
            if cached and now - cached[0] < CACHE_SECONDS:
                self.cache.move_to_end(term)
                return {**cached[1], "query": query}
            if cached:
                del self.cache[term]
            self.calls = [started for started in self.calls if now - started < 60]
            if len(self.calls) >= MAX_CALLS_PER_MINUTE:
                return self._result(query, [], 0, "rate_limited")
            if not self.slots.acquire(blocking=False):
                return self._result(query, [], 0, "rate_limited")
            self.calls.append(now)

        try:
            timeout = min(4.0, remaining - 2) if remaining is not None else 4.0
            if timeout <= 0:
                return self._result(query, [], 0, "unavailable")
            url = SEARCH_URL + "?" + urlencode({"q": query})
            request = Request(url, headers={"Accept": "application/json", "User-Agent": "SVG-CAD/0.1"})
            with urlopen(request, timeout=timeout) as response:
                raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("Location response is too large")
            rows = json.loads(raw)
            if not isinstance(rows, list):
                raise ValueError("Location response has an unexpected shape")
            found, seen = [], set()
            for row in rows:
                point = self._point(row, url)
                if not point:
                    continue
                key = (normalize_text(point["name_en"]), normalize_text(point["name_zh_hant"]),
                       round(point["latitude"], 5), round(point["longitude"], 5))
                if key in seen:
                    continue
                seen.add(key)
                found.append(point)
            result = self._result(query, found[:MAX_RESULTS], len(found),
                                  "external" if found else "no_match")
            with self.lock:
                self.cache[term] = (time.monotonic(), result)
                while len(self.cache) > MAX_CACHE:
                    self.cache.popitem(last=False)
            return result
        except (OSError, TimeoutError, ValueError, UnicodeError, json.JSONDecodeError):
            return self._result(query, [], 0, "unavailable")
        finally:
            self.slots.release()

    def _point(self, row, url):
        if not isinstance(row, dict):
            return None
        name_en, name_zh = row.get("nameEN"), row.get("nameZH")
        if not isinstance(name_en, str) or not isinstance(name_zh, str):
            return None
        name_en, name_zh = name_en.strip()[:160], name_zh.strip()[:160]
        if not name_en or not name_zh:
            return None
        x, y = row.get("x"), row.get("y")
        if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            return None
        if not math.isfinite(x) or not math.isfinite(y):
            return None
        try:
            longitude, latitude = self.transformer.transform(x, y)
        except (ValueError, OverflowError):
            return None
        if not math.isfinite(latitude) or not math.isfinite(longitude) or not (HK[0] <= latitude <= HK[2] and HK[1] <= longitude <= HK[3]):
            return None

        def field(key, limit):
            value = row.get(key)
            return value.strip()[:limit] if isinstance(value, str) else ""

        return {"name_en": name_en, "name_zh_hant": name_zh,
                "address_en": field("addressEN", 200), "address_zh_hant": field("addressZH", 200),
                "district_en": field("districtEN", 80), "district_zh_hant": field("districtZH", 80),
                "latitude": round(latitude, 7), "longitude": round(longitude, 7),
                "kind": "location_point", "source": {"agency": "Lands Department", "url": url}}

    @staticmethod
    def _result(query, results, total, status):
        return {"query": query, "results": results, "matched_total": total,
                "ambiguous": total > 1, "truncated": total > len(results), "lookup_status": status}
