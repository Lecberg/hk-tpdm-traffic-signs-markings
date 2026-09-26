"""Flask API used by the localhost Docker website."""

import json
import math
import multiprocessing
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path
from queue import Empty
from urllib.parse import urlsplit

from flask import Flask, g, jsonify, request, send_file
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

from .agent import provider_from_env, run_turn
from .catalog import Catalog, normalize_code
from .geo import MapData
from .places import PlaceLookup
from .presentation import present

MAX_SVG = 20 * 1024 * 1024
MAX_STORED_BYTES = 64 * 1024 * 1024
TTL = 3600
MAX_SESSIONS = 100
MAX_ARTIFACTS = 5
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


def _svg_safe(data):
    if not data or len(data) > MAX_SVG:
        raise ApiError("invalid_upload", "SVG must be between 1 byte and 20 MiB")
    head = data[:2000].lstrip(b"\xef\xbb\xbf\t\r\n ")
    if b"<svg" not in head.lower():
        raise ApiError("invalid_upload", "File must contain an SVG root")
    if re.search(rb"<!\s*(doctype|entity)\b", data, re.I):
        raise ApiError("unsafe_svg", "XML declarations for external resources are unsupported")
    if re.search(rb"\b(?:href|src)\s*=\s*(['\"])(?!#|data:)[^'\"]+\1", data, re.I):
        raise ApiError("unsafe_svg", "External SVG resources are unsupported")
    if re.search(rb"<\s*(?:script|foreignObject)\b", data, re.I):
        raise ApiError("unsafe_svg", "Scripts and embedded HTML are unsupported")
    if re.search(rb"(?:@import\b|url\s*\(\s*['\"]?\s*(?!#)[^)]+\))", data, re.I):
        raise ApiError("unsafe_svg", "External SVG resources are unsupported")


def _convert_worker(source, destination, options, queue):
    try:
        if os.name == "posix":
            import resource
            resource.setrlimit(resource.RLIMIT_CPU, (25, 25))
            resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024 * 1024, 32 * 1024 * 1024))
        from svg2dxf.cli import convert_file
        result = convert_file(Path(source), Path(destination), **options)
        queue.put({"ok": True, "stats": result})
    except Exception:
        queue.put({"ok": False})


def create_app(site_dir=None, data_dir=None, temp_dir=None, provider=None):
    root = Path(__file__).resolve().parents[3]
    site = Path(site_dir or os.environ.get("SVG_CAD_SITE", root / "site"))
    data = Path(data_dir or os.environ.get("SVG_CAD_DATA", root / "data"))
    scratch = Path(temp_dir or os.environ.get("SVG_CAD_TEMP", tempfile.gettempdir()))
    scratch.mkdir(parents=True, exist_ok=True)
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
    app.config["MAX_CONTENT_LENGTH"] = MAX_SVG + 1024 * 1024
    sessions = {}
    session_lock = threading.Lock()
    conversion_lock = threading.Lock()
    model_slots = threading.BoundedSemaphore(2)
    global_chat_times = []
    provider_name, model, configured_provider = provider_from_env(os.environ)
    provider = provider or configured_provider
    validation_path = data / "provider-validation.json"
    validation = json.loads(validation_path.read_text(encoding="utf-8")) if validation_path.is_file() else {}

    def expire():
        now = time.time()
        with session_lock:
            old = [sid for sid, state in sessions.items()
                   if now - state["seen"] > TTL and not state["chat_lock"].locked()]
            for sid in old:
                shutil.rmtree(sessions.pop(sid)["path"], ignore_errors=True)

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
            path = Path(tempfile.mkdtemp(prefix="svgcad_", dir=scratch))
            state = {"path": path, "seen": time.time(), "uploads": {}, "files": {},
                     "conversions": {}, "history": [], "turns": [], "turn_index": {},
                     "chat_lock": threading.Lock(), "chat_times": []}
            sessions[sid] = state
            g.session_id = sid
            return sid, state, True

    def stored_bytes():
        with session_lock:
            return sum(item.get("size", 0) for state in sessions.values()
                       for group in (state["uploads"], state["files"])
                       for item in group.values())

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

    def reply(payload, sid=None):
        return jsonify(payload)

    @app.get("/api/health")
    def health():
        return jsonify(status="ok")

    @app.get("/api/session")
    def start_session():
        session()
        return jsonify(status="ready", expires_in=TTL)

    @app.get("/api/capabilities")
    def capabilities():
        coverage = catalog.search("", 1)["coverage"]
        return jsonify(api_version=1, version="0.1.0", provider=provider_name if provider else None,
                       configured_provider=provider_name,
                       model=model if provider else None, chat_available=bool(provider),
                       provider_validation=("validated" if configured_provider and provider_name == "deepseek" and
                           validation.get("provider") == "deepseek" and validation.get("model") == model and
                           validation.get("pass") is True and validation.get("scores", {}).get("en", 0) >= 27 and
                           validation.get("scores", {}).get("zh-Hant", 0) >= 27 and
                           validation.get("invented_visible_facts") == 0 and validation.get("questions") == 60
                           else "unverified" if provider_name == "deepseek" else "experimental"),
                       features={"search": True, "map_query": True, "conversion": True},
                       metadata_coverage=coverage, places=len(places),
                       artifact_ttl_seconds=TTL)

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
            if not isinstance(code, str) or not re.fullmatch(r"TS[\s_-]?\d+[A-Z]?", code, re.I):
                raise ApiError("invalid_argument", "Use a traffic sign code such as TS101")
            code = normalize_code(code)
        result = map_data.query(bounds, _int(args.get("limit", 200), "limit", 1, 500), code, center, radius)
        drawing_codes = sorted({"TS_" + code[2:] for code in result["code_counts"]
                                if catalog.detail(code) and catalog.detail(code)["downloads"]})
        result["available_drawings"] = drawing_codes
        return result

    @app.post("/api/map/query")
    def query_map():
        return jsonify(map_query(_payload()))

    @app.post("/api/uploads")
    def upload():
        file = request.files.get("file")
        if not file or not file.filename or not file.filename.lower().endswith(".svg"):
            raise ApiError("invalid_upload", "Choose an .svg file")
        payload = file.stream.read(MAX_SVG + 1)
        _svg_safe(payload)
        sid, state, fresh = session()
        if len(state["uploads"]) >= MAX_ARTIFACTS:
            raise ApiError("artifact_limit", "Reset the session before uploading more files", 429)
        if stored_bytes() + len(payload) > MAX_STORED_BYTES:
            raise ApiError("storage_full", "Temporary storage is full. Reset a session or retry later.", 503)
        upload_id = secrets.token_urlsafe(18)
        source = state["path"] / (upload_id + ".svg")
        source.write_bytes(payload)
        state["uploads"][upload_id] = {"path": source, "size": len(payload),
                                       "name": Path(secure_filename(file.filename)).stem[:60] or "converted"}
        return reply({"upload_id": upload_id, "expires_in": TTL}, sid if fresh else None)

    def convert(args, state, max_wait=30):
        upload_id = args.get("upload_id")
        upload_data = state["uploads"].get(upload_id)
        if not upload_data:
            raise ApiError("not_found", "Upload was not found in this session", 404)
        options = {name: _number(args.get(name, default), name, low, high)
                   for name, default, low, high in (("curve_tol", 0.05, 0.001, 2),
                                                    ("snap_tol", 0.01, 0.0001, 1),
                                                    ("scale", 1, 0.001, 1000))}
        outline = args.get("stroke_as_outline", False)
        if not isinstance(outline, bool):
            raise ApiError("invalid_argument", "stroke_as_outline must be true or false")
        options["stroke_as_outline"] = outline
        cache_key = (upload_id, *options.values())
        cached = state["conversions"].get(cache_key)
        if cached and cached["file_id"] in state["files"]:
            return cached
        if len(state["files"]) >= MAX_ARTIFACTS:
            raise ApiError("artifact_limit", "Reset the session before converting more files", 429)
        if not conversion_lock.acquire(blocking=False):
            raise ApiError("busy", "A conversion is running. Retry shortly.", 503)
        file_id = secrets.token_urlsafe(18)
        destination = state["path"] / (file_id + ".dxf")
        queue = multiprocessing.Queue(maxsize=1)
        process = multiprocessing.Process(target=_convert_worker,
                                          args=(str(upload_data["path"]), str(destination), options, queue))
        try:
            process.start()
            process.join(max(0.1, min(30, max_wait)))
            if process.is_alive():
                process.terminate()
                process.join(3)
                raise ApiError("conversion_timeout", "Conversion took too long", 504)
            try:
                result = queue.get(timeout=1)
            except Empty:
                result = {"ok": False}
            if not result["ok"] or not destination.is_file():
                raise ApiError("conversion_failed", "This SVG could not be converted", 422)
            stats = result["stats"]
            if stats.get("regions", 0) == 0 and stats.get("stroke_lines", 0) == 0:
                raise ApiError("no_geometry", "No drawable geometry was found", 422)
            size = destination.stat().st_size
            if stored_bytes() + size > MAX_STORED_BYTES:
                raise ApiError("storage_full", "Temporary storage is full. Reset a session or retry later.", 503)
            state["files"][file_id] = {"path": destination, "size": size,
                                       "name": upload_data["name"] + ".dxf"}
            response = {"file_id": file_id, "download_url": "/api/files/" + file_id,
                        "stats": stats, "expires_in": TTL}
            state["conversions"][cache_key] = response
            return response
        finally:
            if file_id not in state["files"]:
                destination.unlink(missing_ok=True)
            conversion_lock.release()

    @app.post("/api/conversions")
    def conversions():
        args = _payload()
        _, state, _ = session(create=False)
        return jsonify(convert(args, state))

    @app.get("/api/files/<file_id>")
    def file_download(file_id):
        _, state, _ = session(create=False)
        artifact = state["files"].get(file_id)
        if not artifact or not artifact["path"].is_file():
            raise ApiError("not_found", "File was not found in this session", 404)
        return send_file(artifact["path"], mimetype="application/dxf", as_attachment=True,
                         download_name=artifact["name"])

    def validate_context(raw):
        if raw is None:
            return {}
        if not isinstance(raw, dict) or set(raw) - {"page", "map_point", "active_code"}:
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
        code = raw.get("active_code")
        if code is not None:
            detail = catalog.detail(code) if isinstance(code, str) else None
            if not detail:
                raise ApiError("invalid_argument", "Selected drawing is not in the catalog")
            context["active_code"] = detail["code"]
        return context

    def dispatch(name, args, state, remaining, message="", context=None):
        if name == "search_signs":
            return catalog.search(str(args["query"])[:120], 10)
        if name in ("get_sign", "get_downloads"):
            result = catalog.detail(args["code"])
            return result or {"error": "not_found"}
        if name == "resolve_place":
            return find_places(str(args["query"]), remaining)
        if name == "find_nearby_signs":
            point = (context or {}).get("map_point")
            from_page = point and abs(args["latitude"] - point["latitude"]) < 0.00001 and abs(
                args["longitude"] - point["longitude"]) < 0.00001
            stated = [float(value) for value in re.findall(r"(?<![\w.])\d{2,3}\.\d+(?![\w.])", message)]
            from_message = any(abs(value - args["latitude"]) < 0.00001 for value in stated) and any(
                abs(value - args["longitude"]) < 0.00001 for value in stated)
            if not from_page and not from_message:
                return {"error": "unverified_point", "message": "Choose a map point before counting signs."}
            return map_query({**args, "limit": 50})
        if name == "summarize_area":
            result = map_query({**args, "limit": 500})
            result.pop("returned_records")
            return result
        if name == "convert_uploaded_svg":
            return convert(args, state, max_wait=max(0.1, remaining - 2))
        if name == "help_or_clarify":
            return {"kind": args["kind"]}
        raise ValueError("unknown tool")

    def safe_dispatch(name, args, state, remaining, message="", context=None):
        try:
            return dispatch(name, args, state, remaining, message, context)
        except ApiError as error:
            return {"error": error.code, "message": error.message}

    @app.post("/api/chat")
    def chat():
        if not provider:
            raise ApiError("provider_unavailable", "Chat needs an API key. Search and conversion still work.", 503)
        args = _payload()
        message = args.get("message")
        language = args.get("language", "en")
        if not isinstance(message, str) or not 1 <= len(message.strip()) <= 2000:
            raise ApiError("invalid_argument", "Message must be 1–2000 characters")
        if language not in ("en", "zh-Hant"):
            raise ApiError("invalid_argument", "Language must be en or zh-Hant")
        raw_turn_id = args.get("turn_id", str(uuid.uuid4()))
        if not isinstance(raw_turn_id, str):
            raise ApiError("invalid_argument", "turn_id must be a UUID")
        try:
            turn_id = str(uuid.UUID(raw_turn_id))
        except (ValueError, AttributeError, TypeError):
            raise ApiError("invalid_argument", "turn_id must be a UUID")
        if raw_turn_id.lower() != turn_id:
            raise ApiError("invalid_argument", "turn_id must be a standard UUID")
        context = validate_context(args.get("context"))
        _, state, _ = session()
        upload_id = args.get("upload_id")
        if upload_id is not None and upload_id not in state["uploads"]:
            raise ApiError("not_found", "Upload was not found in this session", 404)
        with session_lock:
            prior = state["turn_index"].get(turn_id)
        if prior:
            if prior["status"] == "working":
                raise ApiError("turn_in_progress", "That chat turn is still running", 409)
            return reply({"turn": prior, "answer": prior["answer"],
                          "tool_results": prior.get("tool_results", [])})
        if not state["chat_lock"].acquire(blocking=False):
            raise ApiError("turn_in_progress", "Wait for the current chat reply", 429)
        if not model_slots.acquire(blocking=False):
            state["chat_lock"].release()
            raise ApiError("busy", "Two model calls are already running", 503)
        try:
            now = time.time()
            with session_lock:
                state["chat_times"] = [t for t in state["chat_times"] if now - t < 60]
                global_chat_times[:] = [t for t in global_chat_times if now - t < 3600]
                if len(state["chat_times"]) >= 5 or len(global_chat_times) >= 60:
                    raise ApiError("chat_limit", "Chat limit reached. Try again later.", 429)
                state["chat_times"].append(now)
                global_chat_times.append(now)
                turn = {"id": turn_id, "message": message.strip(), "language": language,
                        "created_at": now, "status": "working", "answer": "",
                        "blocks": [], "actions": []}
                state["turn_index"][turn_id] = turn
                state["turns"].append(turn)
                state["turns"] = state["turns"][-8:]
                while len(state["turn_index"]) > 64:
                    state["turn_index"].pop(next(iter(state["turn_index"])))
            try:
                answer, tool_results, new_history = run_turn(
                    provider, message.strip(), language, list(state["history"]),
                    lambda name, params, remaining: safe_dispatch(
                        name, params, state, remaining, message.strip(), context),
                    upload_id, context)
                blocks, actions = present(tool_results)
                status = ("failed" if not tool_results else
                          "partial" if any(item["tool"] == "turn_status" for item in tool_results) else "complete")
            except Exception:
                app.logger.exception("Provider turn failed")
                answer = ("助手暫時無法回應。搜尋和轉換仍可使用。" if language == "zh-Hant" else
                          "Chat is unavailable. Search and conversion still work.")
                tool_results, new_history, actions = [], [], []
                blocks, status = [{"type": "notice", "code": "provider_failed", "message": answer}], "failed"
            with session_lock:
                state["history"] = (state["history"] + new_history)[-8:]
                turn.update(status=status, answer=answer, blocks=blocks, actions=actions,
                            tool_results=tool_results)
            return reply({"turn": turn, "answer": answer, "tool_results": tool_results})
        finally:
            model_slots.release()
            state["chat_lock"].release()

    @app.get("/api/chat/history")
    def chat_history():
        try:
            _, state, _ = session(create=False)
        except ApiError as error:
            if error.code == "not_found":
                return jsonify(turns=[])
            raise
        with session_lock:
            return jsonify(turns=list(state["turns"]))

    @app.post("/api/session/reset")
    def reset():
        sid = request.cookies.get("svgcad_session")
        with session_lock:
            state = sessions.get(sid)
            if state and state["chat_lock"].locked():
                raise ApiError("turn_in_progress", "Wait for the current chat reply", 409)
            state = sessions.pop(sid, None)
        if state:
            shutil.rmtree(state["path"], ignore_errors=True)
        response = jsonify(status="reset")
        response.delete_cookie("svgcad_session", path="/api")
        return response

    return app
