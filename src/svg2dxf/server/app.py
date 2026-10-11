"""Flask API used by the localhost Docker website."""

import json
import math
import os
import re
import secrets
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, g, jsonify, request
from werkzeug.exceptions import HTTPException

from .agent import provider_from_env
from .catalog import Catalog, normalize_code
from .geo import MapData
from .places import PlaceLookup
from .presentation import present

TTL = 3600
MAX_SESSIONS = 100
HK = (22.1, 113.8, 22.65, 114.5)


class ApiError(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status


def _number(value, name, low, high):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ApiError("invalid_argument", f"{name} must be a number")
    if not math.isfinite(number) or not low <= number <= high:
        raise ApiError("invalid_argument", f"{name} must be between {low} and {high}")
    return number


def _int(value, name, low, high):
    number = _number(value, name, low, high)
    if not number.is_integer():
        raise ApiError("invalid_argument", f"{name} must be an integer")
    return int(number)


def _payload():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("invalid_json", "Send a JSON object")
    return data


def create_app(site_dir=None, data_dir=None, provider=None):
    root = Path(__file__).resolve().parents[3]
    site = Path(site_dir or os.environ.get("SVG_CAD_SITE", root / "site"))
    data = Path(data_dir or os.environ.get("SVG_CAD_DATA", root / "data"))
    catalog = Catalog(site, data / "sign-metadata.json")
    map_data = MapData(site / "map-data")
    places = json.loads((data / "places.json").read_text(encoding="utf-8"))
    if not isinstance(places, list) or any(
        not isinstance(place, dict) or
        not isinstance(place.get("name_en"), str) or
        not isinstance(place.get("name_zh_hant"), str) or
        not isinstance(place.get("aliases", []), list) or
        not all(isinstance(alias, str) for alias in place.get("aliases", [])) or
        not isinstance(place.get("source", {}).get("url"), str) or
        not isinstance(place.get("latitude"), (int, float)) or
        not isinstance(place.get("longitude"), (int, float)) or
        not HK[0] <= place["latitude"] <= HK[2] or
        not HK[1] <= place["longitude"] <= HK[3]
        for place in places
    ):
        raise ValueError("place index contains an invalid entry")
    place_lookup = PlaceLookup(places)
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
    sessions = {}
    session_lock = threading.Lock()
    model_slots = threading.BoundedSemaphore(2)
    global_request_times = []
    provider_name, model, configured_provider = provider_from_env(os.environ)
    provider = provider or configured_provider
    search_agent = None
    if provider and hasattr(provider, "plan_search"):
        from .search_agent import SearchAgent
        search_agent = SearchAgent(provider,
                                   lambda query, category: catalog.search(query, 20, category),
                                   lambda query, remaining: place_lookup.search(query, remaining),
                                   lambda args: map_query(args))

    def expire():
        now = time.time()
        with session_lock:
            old = [sid for sid, state in sessions.items()
                   if now - state["seen"] > TTL and not state["lock"].locked()]
            for sid in old:
                forget(sessions.pop(sid))

    def forget(state):
        if search_agent:
            for turn in state["agent_turns"]:
                search_agent.forget(turn["thread_id"])

    def session(create=True):
        expire()
        sid = request.cookies.get("svgcad_session")
        with session_lock:
            if sid in sessions:
                state = sessions[sid]
                state["seen"] = time.time()
                g.session_id = sid
                return sid, state, False
            if not create:
                raise ApiError("not_found", "No active session was found", 404)
            if len(sessions) >= MAX_SESSIONS:
                raise ApiError("busy", "Too many active sessions. Try later.", 503)
            sid = secrets.token_urlsafe(24)
            state = {"seen": time.time(), "agent_turns": [], "agent_previous": {},
                     "agent_requests": {}, "lock": threading.Lock(), "request_times": []}
            sessions[sid] = state
            g.session_id = sid
            return sid, state, True

    @app.before_request
    def check_origin():
        host = request.host.split(":")[0].lower()
        if host not in ("localhost", "127.0.0.1"):
            raise ApiError("invalid_host", "Use localhost to access this service", 403)
        if request.method in ("POST", "PUT", "DELETE"):
            origin = request.headers.get("Origin")
            if origin and urlsplit(origin).netloc.lower() != request.host.lower():
                raise ApiError("invalid_origin", "Request must come from this website", 403)

    @app.after_request
    def security_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        sid = getattr(g, "session_id", None)
        if sid:
            response.set_cookie("svgcad_session", sid, max_age=TTL, httponly=True,
                                secure=False, samesite="Strict", path="/api")
        return response

    @app.errorhandler(ApiError)
    def api_error(error):
        return jsonify(error={"code": error.code, "message": error.message}), error.status

    @app.errorhandler(HTTPException)
    def http_error(error):
        code = "request_too_large" if error.code == 413 else "http_error"
        return jsonify(error={"code": code, "message": error.description}), error.code

    @app.errorhandler(Exception)
    def internal_error(error):
        app.logger.exception("API error")
        return jsonify(error={"code": "internal_error", "message": "Request failed. Please retry."}), 500

    @app.get("/api/health")
    def health():
        return jsonify(status="ok")

    @app.get("/api/capabilities")
    def capabilities():
        coverage = catalog.search("", 1)["coverage"]
        return jsonify(api_version=1, version="0.2.0", provider=provider_name if provider else None,
                       configured_provider=provider_name, model=model if provider else None,
                       features={"search": True, "map_query": True, "search_agent": bool(search_agent)},
                       agent={"framework": "LangGraph", "storage": "in-memory",
                              "prototype": True, "survives_restart": False},
                       metadata_coverage=coverage, places=len(places), session_ttl_seconds=TTL)

    @app.get("/api/signs")
    def signs():
        query = request.args.get("q", "").strip()[:120]
        if not query:
            raise ApiError("invalid_argument", "Enter a code or description")
        return jsonify(catalog.search(query, _int(request.args.get("limit", 20), "limit", 1, 50)))

    @app.get("/api/signs/<code>")
    def sign(code):
        detail = catalog.detail(code)
        if not detail:
            raise ApiError("not_found", "That drawing code is not in the catalog", 404)
        return jsonify(detail)

    def find_places(query, remaining=None):
        try:
            return place_lookup.search(query, remaining)
        except ValueError as error:
            raise ApiError("invalid_argument", str(error)) from error

    @app.get("/api/places")
    def place_search():
        return jsonify(find_places(request.args.get("q", "")))

    def map_query(args):
        if "radius_km" in args:
            lat = _number(args.get("latitude"), "latitude", HK[0], HK[2])
            lon = _number(args.get("longitude"), "longitude", HK[1], HK[3])
            radius = _number(args.get("radius_km"), "radius_km", 0.01, 5)
            lat_delta = radius / 110.5
            lon_delta = radius / (111.3 * math.cos(math.radians(lat)))
            bounds = [lat - lat_delta, lon - lon_delta, lat + lat_delta, lon + lon_delta]
            center = [lat, lon]
        else:
            bounds = [_number(args.get(name), name, HK[0] if name in ("south", "north") else HK[1],
                              HK[2] if name in ("south", "north") else HK[3])
                      for name in ("south", "west", "north", "east")]
            if bounds[2] <= bounds[0] or bounds[3] <= bounds[1] or (bounds[2]-bounds[0]) > 0.1 or (bounds[3]-bounds[1]) > 0.1:
                raise ApiError("invalid_argument", "Area must be positive and at most 0.1 degrees per side")
            center = radius = None
        code = args.get("code")
        if code is not None:
            code = validate_code(code)
        result = map_data.query(bounds, _int(args.get("limit", 200), "limit", 1, 500), code, center, radius)
        drawing_codes = sorted({"TS_" + code[2:] for code in result["code_counts"]
                                if catalog.detail(code) and catalog.detail(code)["downloads"]})
        result["available_drawings"] = drawing_codes
        return result

    @app.post("/api/map/query")
    def query_map():
        return jsonify(map_query(_payload()))

    def validate_code(code):
        if not isinstance(code, str) or not re.fullmatch(r"TS[\s_-]?\d+[A-Z]?", code, re.I):
            raise ApiError("invalid_argument", "Use a traffic sign code such as TS101")
        return normalize_code(code)

    def validate_context(raw):
        if raw is None:
            return {}
        if not isinstance(raw, dict) or set(raw) - {"page", "map_point", "scope"}:
            raise ApiError("invalid_argument", "Invalid page context")
        page = raw.get("page")
        if page not in ("gallery", "map"):
            raise ApiError("invalid_argument", "Page must be gallery or map")
        context = {"page": page}
        point = raw.get("map_point")
        if point is not None:
            if page != "map" or not isinstance(point, dict) or set(point) != {"latitude", "longitude", "source"}:
                raise ApiError("invalid_argument", "Invalid map point")
            if point["source"] not in ("selected", "center"):
                raise ApiError("invalid_argument", "Invalid map point source")
            context["map_point"] = {"latitude": _number(point["latitude"], "latitude", HK[0], HK[2]),
                                    "longitude": _number(point["longitude"], "longitude", HK[1], HK[3]),
                                    "source": point["source"]}
        # The search currently on the map, which may have been edited by hand
        # (chips, radius handle) since the agent last answered.
        scope = raw.get("scope")
        if scope is not None:
            if (page != "map" or not isinstance(scope, dict) or
                    set(scope) - {"latitude", "longitude", "radius_km", "code", "place"} or
                    not {"latitude", "longitude", "radius_km"} <= set(scope)):
                raise ApiError("invalid_argument", "Invalid map scope")
            place = scope.get("place")
            if place is not None and (not isinstance(place, str) or len(place) > 160):
                raise ApiError("invalid_argument", "Invalid map scope place")
            context["scope"] = {
                "latitude": _number(scope["latitude"], "latitude", HK[0], HK[2]),
                "longitude": _number(scope["longitude"], "longitude", HK[1], HK[3]),
                "radius_km": _number(scope["radius_km"], "radius_km", 0.01, 5),
                "code": None if scope.get("code") is None else validate_code(scope["code"]),
                "place": place}
        return context

    @app.post("/api/session/reset")
    def reset():
        sid = request.cookies.get("svgcad_session")
        with session_lock:
            state = sessions.get(sid)
            if state and state["lock"].locked():
                raise ApiError("turn_in_progress", "Wait for the current assistant request", 409)
            state = sessions.pop(sid, None)
        if state:
            forget(state)
        response = jsonify(status="reset")
        response.delete_cookie("svgcad_session", path="/api")
        return response

    def previous_search(previous, context):
        """The search to refine: what is on the map now, if the page sent it.

        The chips and the radius handle change the map without asking the
        agent, so "make it 1 km" must start from the page's scope rather than
        the agent's last answer. The confirmed place is kept while the centre
        is unchanged, so its name survives; a moved centre becomes a map point.
        """
        scope = context.get("scope")
        if not scope:
            return previous
        location = previous.get("location") or {}
        if not location or abs(location.get("latitude", 0) - scope["latitude"]) > 1e-6 or \
                abs(location.get("longitude", 0) - scope["longitude"]) > 1e-6:
            name = scope["place"] or "Selected map point"
            location = {"latitude": scope["latitude"], "longitude": scope["longitude"],
                        "name_en": name, "name_zh_hant": scope["place"] or "已選位置", "kind": "map_point"}
        drawing = {}
        if scope["code"]:
            old = previous.get("drawing") or {}
            drawing = old if normalize_code(old.get("code", "")) == scope["code"] else catalog.detail(scope["code"]) or {}
        plan = {"action": "nearby", "place_query": "", "sign_query": drawing.get("code", ""),
                "radius_km": scope["radius_km"], "category": "TS",
                "use_map_point": False, "clear_sign_filter": False}
        return {"plan": plan, "location": location, "drawing": drawing}

    def public_agent_turn(turn):
        return {key: value for key, value in turn.items() if key != "thread_id"}

    @app.get("/api/agent/history")
    def agent_history():
        try:
            _, state, _ = session(create=False)
        except ApiError as error:
            if error.code == "not_found":
                return jsonify(turns=[])
            raise
        with session_lock:
            return jsonify(turns=[public_agent_turn(turn) for turn in state["agent_turns"]])

    @app.post("/api/agent/search")
    @app.post("/api/agent/resume")
    @app.post("/api/agent/cancel")
    def agent_search():
        if not search_agent:
            raise ApiError("provider_unavailable", "The search agent needs a configured model service.", 503)
        args = _payload()
        operation = request.path.rsplit("/", 1)[-1]
        raw_id = args.get("request_id")
        try:
            request_id = str(uuid.UUID(raw_id)) if isinstance(raw_id, str) else ""
        except ValueError:
            request_id = ""
        if not request_id or raw_id.lower() != request_id:
            raise ApiError("invalid_argument", "request_id must be a standard UUID")
        _, state, _ = session()
        if not state["lock"].acquire(blocking=False):
            raise ApiError("turn_in_progress", "Wait for the current assistant request", 429)
        slot = False
        try:
            # Cache snapshots, not mutable turns: a replay must not execute anything again.
            cached = state["agent_requests"].get(request_id)
            if cached:
                return jsonify(cached)
            turn = None
            if operation == "search":
                if any(t["status"] == "waiting" for t in state["agent_turns"]):
                    raise ApiError("selection_pending", "Choose a result or cancel the pending search first", 409)
                message = args.get("message")
                language = args.get("language", "en")
                if not isinstance(message, str) or not 1 <= len(message.strip()) <= 2000:
                    raise ApiError("invalid_argument", "Message must be 1–2000 characters")
                if language not in ("en", "zh-Hant"):
                    raise ApiError("invalid_argument", "Language must be en or zh-Hant")
                context = validate_context(args.get("context"))
            else:
                turn = next((t for t in state["agent_turns"] if t["id"] == args.get("turn_id")), None)
                if not turn or turn["status"] != "waiting":
                    raise ApiError("stale_selection", "That search is no longer waiting for a selection", 409)
                if args.get("interrupt_id") != turn["pending"]["interrupt_id"]:
                    raise ApiError("stale_selection", "That selection is no longer pending", 409)
                if operation == "resume" and (not isinstance(args.get("choice_id"), str) or
                        args["choice_id"] not in {c["id"] for c in turn["pending"]["choices"]}):
                    raise ApiError("invalid_argument", "Choose one of the offered results")
            if operation != "cancel":
                if not model_slots.acquire(blocking=False):
                    raise ApiError("busy", "The assistant is busy. Try shortly.", 503)
                slot = True
                now = time.time()
                with session_lock:
                    state["request_times"] = [t for t in state["request_times"] if now - t < 60]
                    global_request_times[:] = [t for t in global_request_times if now - t < 3600]
                    if len(state["request_times"]) >= 5 or len(global_request_times) >= 60:
                        raise ApiError("request_limit", "Assistant request limit reached. Try again later.", 429)
                    state["request_times"].append(now)
                    global_request_times.append(now)
            if operation == "search":
                turn = {"id": request_id, "thread_id": secrets.token_urlsafe(24),
                        "message": message.strip(), "language": language, "created_at": time.time(),
                        "status": "working", "answer": "", "blocks": [], "actions": [],
                        "pending": None, "trace": [], "search": {}}
                state["agent_turns"].append(turn)
                while len(state["agent_turns"]) > 8:
                    search_agent.forget(state["agent_turns"].pop(0)["thread_id"])
            if operation == "cancel":
                search_agent.forget(turn["thread_id"])
                turn.update(status="cancelled", pending=None, answer="Search cancelled.")
            else:
                turn["status"] = "working"
                try:
                    if operation == "search":
                        result = search_agent.start(turn["thread_id"], message.strip(), language,
                                                    previous_search(state["agent_previous"], context), context)
                    else:
                        result = search_agent.resume(turn["thread_id"], args["interrupt_id"], args["choice_id"])
                    description = search_agent.describe(result)
                    confirmed = description.pop("state")
                    blocks, actions = present(description["tool_results"])
                    turn.update(**description, blocks=blocks, actions=actions)
                    if turn["status"] == "complete" and description["tool_results"]:
                        state["agent_previous"] = confirmed
                except (ValueError, TimeoutError) as error:
                    turn.update(status="failed", pending=None, answer=str(error)[:200])
                    search_agent.forget(turn["thread_id"])
                except Exception:
                    app.logger.exception("Search agent failed")
                    turn.update(status="failed", pending=None,
                                answer="The agent could not finish. Manual search is still available.")
                    search_agent.forget(turn["thread_id"])
            response = {"turn": public_agent_turn(turn)}
            state["agent_requests"][request_id] = json.loads(json.dumps(response))
            while len(state["agent_requests"]) > 64:
                state["agent_requests"].pop(next(iter(state["agent_requests"])))
            return jsonify(response)
        finally:
            if slot:
                model_slots.release()
            state["lock"].release()

    return app
