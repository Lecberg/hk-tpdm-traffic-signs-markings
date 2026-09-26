"""Checks for grounded chat, saved turns, review gates, and result cards."""

import json
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace

from svg2dxf.server import create_app
from svg2dxf.server.agent import run_turn
from svg2dxf.server.presentation import present


class Call:
    def __init__(self, name, args):
        self.id = str(uuid.uuid4())
        self.function = SimpleNamespace(name=name, arguments=json.dumps(args))

    def model_dump(self, exclude_none=True):
        return {"id": self.id, "type": "function", "function": {
            "name": self.function.name, "arguments": self.function.arguments}}


class Provider:
    def __init__(self, call=None, invented="The answer is TS9999 with 999 signs.", fail_after=False):
        self.call = call
        self.invented = invented
        self.fail_after = fail_after
        self.calls = 0

    def complete(self, messages, timeout, require_tool=False):
        self.calls += 1
        if self.calls == 1:
            assert require_tool
            chosen = [self.call] if self.call else []
        elif self.fail_after:
            raise RuntimeError("model unavailable")
        else:
            chosen = []
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            tool_calls=chosen, content=self.invented))])


def test_invented_model_text_and_missing_tool_are_hidden():
    provider = Provider()
    answer, results, history = run_turn(provider, "find signs", "en", [], lambda *args: {})
    assert results == []
    assert "TS9999" not in answer + json.dumps(history)
    assert "could not verify" in answer


def test_missing_tool_call_marks_turn_failed(tmp_path):
    app = create_app(temp_dir=tmp_path, provider=Provider())
    result = app.test_client().post('/api/chat', json={"message": "What is TS9999?"})
    assert result.status_code == 200
    assert result.json['turn']['status'] == 'failed'
    assert result.json['turn']['tool_results'] == []
    assert 'TS9999' not in result.json['turn']['answer']


def test_checked_result_survives_later_model_failure(tmp_path):
    provider = Provider(Call("get_sign", {"code": "TS101"}), fail_after=True)
    app = create_app(temp_dir=tmp_path, provider=provider)
    response = app.test_client().post('/api/chat', json={
        "turn_id": str(uuid.uuid4()), "message": "Show TS101"})
    assert response.status_code == 200
    turn = response.json["turn"]
    assert turn["status"] == "partial"
    assert turn["blocks"][0]["items"][0]["code"] == "TS_101"
    assert turn["blocks"][1]["code"] == "provider_interrupted"
    assert "TS9999" not in json.dumps(turn)


def test_repeat_turn_history_and_cookie_renewal(tmp_path):
    provider = Provider(Call("get_sign", {"code": "TS101"}))
    app = create_app(temp_dir=tmp_path, provider=provider)
    client = app.test_client()
    request = {"turn_id": str(uuid.uuid4()), "message": "Show TS101",
               "context": {"page": "gallery", "active_code": "TS_101"}}
    first = client.post('/api/chat', json=request)
    repeated = client.post('/api/chat', json=request)
    assert first.json == repeated.json
    assert provider.calls == 2
    assert 'Max-Age=3600' in repeated.headers['Set-Cookie']
    restored = client.get('/api/chat/history')
    assert [turn['id'] for turn in restored.json['turns']] == [request['turn_id']]
    assert 'Max-Age=3600' in restored.headers['Set-Cookie']


def test_context_and_rate_limits(tmp_path):
    class HelpProvider:
        calls = 0

        def complete(self, messages, timeout, require_tool=False):
            self.calls += 1
            calls = [Call("help_or_clarify", {"kind": "help"})] if require_tool else []
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                tool_calls=calls, content="invented"))])

    provider = HelpProvider()
    client = create_app(temp_dir=tmp_path, provider=provider).test_client()
    bad = client.post('/api/chat', json={"message": "near this pin", "context": {
        "page": "map", "map_point": {"latitude": 100, "longitude": 114, "source": "selected"}}})
    assert bad.status_code == 400
    for i in range(5):
        response = client.post('/api/chat', json={"turn_id": str(uuid.uuid4()), "message": str(i),
            "context": {"page": "map", "map_point": {
                "latitude": 22.3, "longitude": 114.1, "source": "selected"}}})
        assert response.status_code == 200
    limited = client.post('/api/chat', json={"turn_id": str(uuid.uuid4()), "message": "six"})
    assert limited.status_code == 429
    assert provider.calls == 10


def test_unknown_file_does_not_create_a_session(tmp_path):
    client = create_app(temp_dir=tmp_path).test_client()
    response = client.get('/api/files/unknown')
    assert response.status_code == 404
    assert 'Set-Cookie' not in response.headers
    assert client.get('/api/chat/history').json == {"turns": []}
    assert not list(tmp_path.glob('svgcad_*'))


def test_session_bootstrap_and_limits(tmp_path, monkeypatch):
    from svg2dxf.server import app as app_module
    monkeypatch.setattr(app_module, 'MAX_SESSIONS', 1)
    app = create_app(temp_dir=tmp_path)
    first, second = app.test_client(), app.test_client()
    assert first.get('/api/session').status_code == 200
    assert second.get('/api/session').status_code == 503
    assert first.get('/api/session').status_code == 200


def test_one_active_visit_and_two_global_model_calls(tmp_path):
    class SlowProvider:
        def __init__(self):
            self.calls = 0
            self.lock = threading.Lock()
            self.two_started = threading.Event()
            self.release = threading.Event()

        def complete(self, messages, timeout, require_tool=False):
            if require_tool:
                with self.lock:
                    self.calls += 1
                    if self.calls == 2:
                        self.two_started.set()
                assert self.release.wait(5)
            calls = [Call('help_or_clarify', {'kind': 'help'})] if require_tool else []
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                tool_calls=calls, content='invented'))])

    provider = SlowProvider()
    app = create_app(temp_dir=tmp_path, provider=provider)
    clients = [app.test_client() for _ in range(3)]
    for client in clients:
        assert client.get('/api/session').status_code == 200
    results = []
    threads = [threading.Thread(target=lambda client=clients[i]: results.append(
        client.post('/api/chat', json={'turn_id': str(uuid.uuid4()), 'message': 'Help'}).status_code))
        for i in range(2)]
    try:
        threads[0].start()
        assert provider.two_started.wait(0.1) is False
        assert clients[0].get('/api/chat/history').json['turns'][0]['status'] == 'working'
        same_visit = clients[0].post('/api/chat', json={
            'turn_id': str(uuid.uuid4()), 'message': 'Again'})
        assert same_visit.status_code == 429
        threads[1].start()
        assert provider.two_started.wait(5)
        third = clients[2].post('/api/chat', json={
            'turn_id': str(uuid.uuid4()), 'message': 'Third'})
        assert third.status_code == 503
        assert provider.calls == 2
    finally:
        provider.release.set()
        for thread in threads:
            if thread.ident is not None:
                thread.join(5)
    assert sorted(results) == [200, 200]
    assert clients[0].get('/api/chat/history').json['turns'][0]['status'] == 'complete'


def test_full_turn_deadline_keeps_completed_tool(monkeypatch):
    import svg2dxf.server.agent as agent_module
    ticks = iter([0, 0, 0, 59])
    monkeypatch.setattr(agent_module.time, 'monotonic', lambda: next(ticks))
    provider = Provider(Call('get_sign', {'code': 'TS101'}))
    answer, results, _ = run_turn(provider, 'Show TS101', 'en', [],
                                  lambda name, args, remaining: {'code': 'TS_101'})
    assert answer.startswith('Drawing TS_101.')
    assert results[0]['result']['code'] == 'TS_101'
    assert results[1]['result']['error'] == 'turn_timeout'
    assert provider.calls == 1


def test_sixty_turns_per_hour_across_visits(tmp_path):
    class HelpProvider:
        def complete(self, messages, timeout, require_tool=False):
            calls = [Call('help_or_clarify', {'kind': 'help'})] if require_tool else []
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                tool_calls=calls, content='ignored'))])

    app = create_app(temp_dir=tmp_path, provider=HelpProvider())
    for _ in range(12):
        client = app.test_client()
        assert client.get('/api/session').status_code == 200
        for _ in range(5):
            assert client.post('/api/chat', json={
                'turn_id': str(uuid.uuid4()), 'message': 'Help'}).status_code == 200
    extra = app.test_client()
    assert extra.get('/api/session').status_code == 200
    response = extra.post('/api/chat', json={
        'turn_id': str(uuid.uuid4()), 'message': 'Help'})
    assert response.status_code == 429
    assert response.json['error']['code'] == 'chat_limit'


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
        {"tool": "convert_uploaded_svg", "result": {"download_url": "/api/files/abc",
            "stats": {"warnings": []}, "expires_in": 3600}},
        {"tool": "help_or_clarify", "result": {"kind": "clarify"}},
        {"tool": "turn_status", "result": {"error": "turn_timeout"}},
    ]
    blocks, actions = present(results)
    assert [block['type'] for block in blocks] == [
        'signs', 'places', 'map', 'map', 'conversion', 'clarify', 'notice']
    assert any(action['type'] == 'show_gallery' for action in actions)
    assert any(action['type'] == 'open_map' and action['code'] == 'TS101' for action in actions)


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
