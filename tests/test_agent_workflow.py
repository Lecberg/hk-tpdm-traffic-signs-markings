"""Session, rate-limit and result-card guarantees around the search agent."""

import json
import threading
import uuid
from pathlib import Path

from svg2dxf.server import create_app
from svg2dxf.server.presentation import present


HELP = {"action": "help", "place_query": "", "sign_query": "", "radius_km": 0, "category": "ALL",
        "use_map_point": False, "clear_sign_filter": False}


class HelpPlanner:
    """Answers every request with a help plan, which finishes without map work."""

    def __init__(self):
        self.calls = 0

    def plan_search(self, message, previous, timeout):
        self.calls += 1
        return dict(HELP)


def search(client, message="Help"):
    return client.post('/api/agent/search', json={"request_id": str(uuid.uuid4()), "message": message})


def test_history_without_session_does_not_create_one():
    client = create_app(provider=HelpPlanner()).test_client()
    response = client.get('/api/agent/history')
    assert response.json == {"turns": []}
    assert 'Set-Cookie' not in response.headers


def test_session_cookie_is_renewed_and_capped(monkeypatch):
    from svg2dxf.server import app as app_module
    monkeypatch.setattr(app_module, 'MAX_SESSIONS', 1)
    app = create_app(provider=HelpPlanner())
    first, second = app.test_client(), app.test_client()
    assert search(first).status_code == 200
    restored = first.get('/api/agent/history')
    assert len(restored.json['turns']) == 1
    assert 'Max-Age=3600' in restored.headers['Set-Cookie']
    assert search(second).status_code == 503


def test_context_is_validated_and_five_requests_per_minute():
    provider = HelpPlanner()
    client = create_app(provider=provider).test_client()
    bad = client.post('/api/agent/search', json={"request_id": str(uuid.uuid4()), "message": "near this pin",
        "context": {"page": "map", "map_point": {"latitude": 100, "longitude": 114, "source": "selected"}}})
    assert bad.status_code == 400
    for i in range(5):
        assert search(client, str(i)).status_code == 200
    limited = search(client, "six")
    assert limited.status_code == 429
    assert limited.json['error']['code'] == 'request_limit'
    assert provider.calls == 5


def test_sixty_requests_per_hour_across_visits():
    app = create_app(provider=HelpPlanner())
    for _ in range(12):
        client = app.test_client()
        for _ in range(5):
            assert search(client).status_code == 200
    response = search(app.test_client())
    assert response.status_code == 429
    assert response.json['error']['code'] == 'request_limit'


def test_one_active_request_per_visit_and_two_model_calls_overall():
    class SlowPlanner:
        def __init__(self):
            self.calls = 0
            self.lock = threading.Lock()
            self.two_started = threading.Event()
            self.release = threading.Event()

        def plan_search(self, message, previous, timeout):
            if message == "warm-up":
                return dict(HELP)
            with self.lock:
                self.calls += 1
                if self.calls == 2:
                    self.two_started.set()
            assert self.release.wait(5)
            return dict(HELP)

    provider = SlowPlanner()
    app = create_app(provider=provider)
    clients = [app.test_client() for _ in range(3)]
    for client in clients:
        assert search(client, "warm-up").status_code == 200   # gives each visit its session
    results = []
    threads = [threading.Thread(target=lambda client=clients[i]: results.append(search(client).status_code))
               for i in range(2)]
    try:
        threads[0].start()
        assert provider.two_started.wait(0.1) is False
        assert search(clients[0], "Again").status_code == 429     # same visit, still running
        threads[1].start()
        assert provider.two_started.wait(5)
        assert search(clients[2], "Third").status_code == 503     # both model slots busy
        assert provider.calls == 2
    finally:
        provider.release.set()
        for thread in threads:
            if thread.ident is not None:
                thread.join(5)
    assert sorted(results) == [200, 200]


def test_all_result_block_shapes():
    sign = {"code": "TS_101", "downloads": {"svg": "svgs/TS_101.svg", "dxf": "dxfs/TS_101.dxf"}}
    place = {"name_en": "Central", "latitude": 22.28, "longitude": 114.15}
    scope = {"bounds": [22.2, 114.1, 22.3, 114.2], "center": [22.28, 114.15],
             "radius_km": 0.5, "code": "TS101"}
    results = [
        {"tool": "search_signs", "result": {"results": [sign], "matched_total": 1,
            "truncated": False, "coverage": {}}},
        {"tool": "get_sign", "result": sign},
        {"tool": "get_downloads", "result": sign},
        {"tool": "resolve_place", "result": {"results": [place], "matched_total": 1,
            "ambiguous": False}},
        {"tool": "find_nearby_signs", "result": {"matched_total": 5,
            "returned_records": [], "truncated": True, "data_complete": False,
            "missing_cells": ["example"], "available_drawings": ["TS_101"], "query_scope": scope}},
        {"tool": "summarize_area", "result": {"matched_total": 5,
            "truncated": False, "data_complete": True, "missing_cells": [],
            "available_drawings": [], "query_scope": scope}},
        {"tool": "turn_status", "result": {"error": "turn_timeout"}},
    ]
    blocks, actions = present(results)
    assert [block['type'] for block in blocks] == ['signs', 'places', 'map', 'map', 'notice']
    assert any(action['type'] == 'show_gallery' for action in actions)
    assert any(action['type'] == 'open_map' and action['code'] == 'TS101' for action in actions)
    assert json.dumps(blocks).count('TS_101') >= 1


def test_reviewed_queue_and_districts():
    root = Path(__file__).resolve().parents[1]
    queue = json.loads((root / 'data/sign-review-queue.json').read_text(encoding='utf-8'))
    places = json.loads((root / 'data/places.json').read_text(encoding='utf-8'))
    assert len(queue) == 100
    assert len({item['code'] for item in queue}) == 100
    assert all(item['review_status'] == 'verified' for item in queue)
    assert [len(queue[i:i + 20]) for i in range(0, 100, 20)] == [20] * 5
    assert len([place for place in places if place.get('kind') == 'district_center']) == 18
    assert len(places) == 26
