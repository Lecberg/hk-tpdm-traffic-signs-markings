"""Place lookup uses checked government points and keeps saved places available."""

import io
import json
from types import SimpleNamespace

from svg2dxf.server import create_app
from svg2dxf.server import places as places_module


def row(name="QUEEN MARY HOSPITAL", name_zh="瑪麗醫院", x=831487.0, y=814622.0):
    return {"nameEN": name, "nameZH": name_zh, "addressEN": "102 POK FU LAM ROAD",
            "addressZH": "薄扶林道102號", "districtEN": "Southern District",
            "districtZH": "南區", "x": x, "y": y}


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def fake_service(monkeypatch, rows):
    calls = []

    def open_url(request, timeout):
        calls.append((request.full_url, timeout))
        return Response(json.dumps(rows, ensure_ascii=False).encode("utf-8"))

    monkeypatch.setattr(places_module, "urlopen", open_url)
    return calls


def test_saved_places_first_and_external_bilingual_points(tmp_path, monkeypatch):
    calls = fake_service(monkeypatch, [row()])
    client = create_app(temp_dir=tmp_path).test_client()
    local = client.get('/api/places?q=Mong%20Kok').json
    assert local['lookup_status'] == 'local'
    assert local['results'][0]['name_en'] == 'Mong Kok'
    assert not calls

    english = client.get('/api/places?q=Queen%20Mary%20Hospital').json
    chinese = client.get('/api/places?q=%E7%91%AA%E9%BA%97%E9%86%AB%E9%99%A2').json
    for result in (english, chinese):
        assert result['lookup_status'] == 'external'
        assert result['matched_total'] == 1
        assert not result['ambiguous']
        point = result['results'][0]
        assert point['name_zh_hant'] == '瑪麗醫院'
        assert point['address_en'] == '102 POK FU LAM ROAD'
        assert point['district_zh_hant'] == '南區'
        assert 22.26 < point['latitude'] < 22.28
        assert 114.12 < point['longitude'] < 114.14
        assert point['source']['agency'] == 'Lands Department'
        assert point['kind'] == 'location_point'
    assert len(calls) == 2
    assert '%E7%91%AA' in calls[1][0]
    assert all(timeout <= 4 for _, timeout in calls)
    assert 'Set-Cookie' not in client.get('/api/places?q=Queen%20Mary%20Hospital').headers
    assert len(calls) == 2  # Cached lookup needs no second service request.


def test_place_choices_deduplicate_validate_and_limit(tmp_path, monkeypatch):
    rows = [row(name=f"Hospital {i}", x=831487 + i) for i in range(12)]
    rows.insert(1, rows[0].copy())
    rows.extend([row(name="Outside", x=0, y=0), row(name="Bad", x=float('nan')),
                 {"nameEN": "Missing grid", "nameZH": "沒有座標"}])
    fake_service(monkeypatch, rows)
    client = create_app(temp_dir=tmp_path).test_client()
    result = client.get('/api/places?q=Hospital').json
    assert result['lookup_status'] == 'external'
    assert result['matched_total'] == 12
    assert len(result['results']) == 10
    assert result['ambiguous'] and result['truncated']
    assert [item['name_en'] for item in result['results']] == [f'Hospital {i}' for i in range(10)]


def test_no_match_failure_and_rate_limit(tmp_path, monkeypatch):
    calls = fake_service(monkeypatch, [])
    client = create_app(temp_dir=tmp_path).test_client()
    assert client.get('/api/places?q=Nothing%20here').json['lookup_status'] == 'no_match'
    for index in range(29):
        assert client.get(f'/api/places?q=Unknown{index}').json['lookup_status'] == 'no_match'
    limited = client.get('/api/places?q=One%20more').json
    assert limited['lookup_status'] == 'rate_limited'
    assert len(calls) == 30

    def fail(*_args, **_kwargs):
        raise TimeoutError('service timed out')

    monkeypatch.setattr(places_module, 'urlopen', fail)
    other = create_app(temp_dir=tmp_path).test_client()
    unavailable = other.get('/api/places?q=An%20unknown%20place').json
    assert unavailable['lookup_status'] == 'unavailable'
    assert unavailable['results'] == []
    assert other.get('/api/places?q=Mong%20Kok').json['lookup_status'] == 'local'
    assert other.get('/api/places?q=').status_code == 400


def test_chat_place_card_uses_service_result_not_model_prose(tmp_path, monkeypatch):
    fake_service(monkeypatch, [row()])

    class Call:
        id = 'place_1'
        function = SimpleNamespace(name='resolve_place', arguments='{"query":"Queen Mary Hospital"}')

        def model_dump(self, exclude_none=True):
            return {'id': self.id, 'type': 'function',
                    'function': {'name': self.function.name, 'arguments': self.function.arguments}}

    class Provider:
        def complete(self, messages, timeout, require_tool=False):
            calls = [Call()] if require_tool else []
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                tool_calls=calls, content='The hospital is at invented coordinates 0, 0.'))])

    client = create_app(temp_dir=tmp_path, provider=Provider()).test_client()
    turn = client.post('/api/chat', json={'message': 'Find Queen Mary Hospital'}).json['turn']
    assert turn['blocks'][0]['type'] == 'places'
    assert turn['blocks'][0]['lookup_status'] == 'external'
    assert turn['blocks'][0]['items'][0]['name_en'] == 'QUEEN MARY HOSPITAL'
    assert 'invented' not in json.dumps(turn)
    assert not turn['actions']  # A place choice never opens the map automatically.


def test_chat_rejects_guessed_place_coordinates(tmp_path):
    class Call:
        id = 'guessed_1'
        function = SimpleNamespace(name='find_nearby_signs', arguments=json.dumps({
            'latitude': 22.2704, 'longitude': 114.1305, 'radius_km': 0.5}))

        def model_dump(self, exclude_none=True):
            return {'id': self.id, 'type': 'function',
                    'function': {'name': self.function.name, 'arguments': self.function.arguments}}

    class Provider:
        def complete(self, messages, timeout, require_tool=False):
            calls = [Call()] if require_tool else []
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                tool_calls=calls, content='There are 999 signs nearby.'))])

    client = create_app(temp_dir=tmp_path, provider=Provider()).test_client()
    turn = client.post('/api/chat', json={'message': 'How many signs are near Queen Mary Hospital?'}).json['turn']
    assert turn['tool_results'][0]['result']['error'] == 'unverified_point'
    assert turn['blocks'][0]['type'] == 'notice'
    assert not turn['actions']
    assert '999' not in json.dumps(turn)
