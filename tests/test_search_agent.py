"""Offline checks for the LangGraph prototype's pause/resume and trust boundaries."""

import copy
import uuid

import pytest

from svg2dxf.server import create_app


def plan(**changes):
    return {"action": "nearby", "place_query": "Mong Kok", "sign_query": "TS101",
            "radius_km": 0.3, "category": "TS", "use_map_point": False,
            "clear_sign_filter": False, **changes}


class Planner:
    def __init__(self, *plans):
        self.plans = list(plans)
        self.calls = []

    def plan_search(self, message, previous, timeout):
        self.calls.append((message, previous))
        return copy.deepcopy(self.plans.pop(0))


def start(client, message="Find stop signs near Mong Kok", **changes):
    return client.post('/api/agent/search', json={
        "request_id": str(uuid.uuid4()), "message": message, **changes})


def select(client, turn, operation="resume", **changes):
    return client.post('/api/agent/' + operation, json={
        "request_id": str(uuid.uuid4()), "turn_id": turn['id'],
        "interrupt_id": turn['pending']['interrupt_id'], "choice_id": "0", **changes})


@pytest.fixture
def agent_client(tmp_path):
    provider = Planner(plan(sign_query="Stop"), plan(action="refine", place_query="", sign_query="", radius_km=1))
    app = create_app(temp_dir=tmp_path, provider=provider)
    app.testing = True
    return app.test_client(), provider


def test_place_selection_pauses_and_resumes_original_radius(agent_client):
    client, provider = agent_client
    first = start(client).json['turn']
    assert first['status'] == 'waiting'
    assert first['pending']['kind'] == 'place'
    assert not any(block['type'] == 'map' for block in first['blocks'])
    assert 'thread_id' not in first
    resumed = select(client, first).json['turn']
    assert resumed['status'] == 'complete'
    block = next(block for block in resumed['blocks'] if block['type'] == 'map')
    assert block['query_scope']['radius_km'] == 0.3
    assert block['query_scope']['code'] == 'TS101'
    assert resumed['search']['place']['source']['url']
    assert len(provider.calls) == 1  # No repeat model call after the human selection.
    followup = start(client, "Make it one kilometre").json['turn']
    assert followup['status'] == 'complete'
    assert followup['search']['radius_km'] == 1
    assert followup['search']['place'] == resumed['search']['place']
    assert followup['search']['drawing']['code'] == 'TS_101'
    assert provider.calls[-1][1]['selected_place']


def test_resume_is_idempotent_and_other_sessions_cannot_resume(agent_client):
    client, provider = agent_client
    first = start(client).json['turn']
    payload = {"request_id": str(uuid.uuid4()), "turn_id": first['id'],
               "interrupt_id": first['pending']['interrupt_id'], "choice_id": "0"}
    other = client.application.test_client()
    assert other.post('/api/agent/resume', json=payload).status_code == 409
    response = client.post('/api/agent/resume', json=payload)
    repeated = client.post('/api/agent/resume', json=payload)
    assert response.json == repeated.json
    assert select(client, first).status_code == 409
    assert len(provider.calls) == 1


def test_invalid_and_stale_choices_leave_workflow_waiting(agent_client):
    client, _ = agent_client
    first = start(client).json['turn']
    assert select(client, first, choice_id="999").status_code == 400
    assert select(client, first, choice_id=[]).status_code == 400
    assert select(client, first, interrupt_id="invented").status_code == 409
    assert client.get('/api/agent/history').json['turns'][0]['status'] == 'waiting'
    assert start(client).status_code == 409
    cancelled = select(client, first, operation="cancel").json['turn']
    assert cancelled['status'] == 'cancelled'
    assert cancelled['pending'] is None


def test_category_filter_and_no_marking_location_claims(tmp_path):
    provider = Planner(plan(action="drawings", place_query="", sign_query="RM1001", category="RM"),
                       plan(sign_query="", category="RM"))
    client = create_app(temp_dir=tmp_path, provider=provider).test_client()
    drawing = start(client, "Show RM1001").json['turn']
    assert drawing['status'] == 'complete'
    assert drawing['blocks'][0]['items'][0]['code'] == 'RM_1001'
    assert all(item['category'] == 'RM' for block in drawing['blocks'] if block['type'] == 'signs' for item in block['items'])
    unavailable = start(client, "Find road markings near Mong Kok").json['turn']
    assert 'not in the surveyed map dataset' in unavailable['answer']
    assert not unavailable['blocks']


def test_page_point_must_be_explicit_and_validated(tmp_path):
    provider = Planner(plan(place_query="", sign_query="Stop", use_map_point=True))
    client = create_app(temp_dir=tmp_path, provider=provider).test_client()
    turn = start(client, "Stop signs near this pin", context={"page": "map", "map_point": {
        "latitude": 22.3193, "longitude": 114.1694, "source": "selected"}}).json['turn']
    assert turn['status'] == 'complete'
    assert turn['search']['place']['kind'] == 'map_point'
    assert start(client, context={"page": "map", "map_point": {
        "latitude": 0, "longitude": 0, "source": "selected"}}).status_code == 400


def test_reset_clears_history_and_refinement_context(agent_client):
    client, _ = agent_client
    first = start(client).json['turn']
    select(client, first)
    assert client.post('/api/session/reset', json={}).status_code == 200
    assert client.get('/api/agent/history').json == {'turns': []}
    following = start(client, "Make it one kilometre").json['turn']
    assert 'before refining' in following['answer']


def test_duplicate_search_does_not_call_provider_again(agent_client):
    client, provider = agent_client
    payload = {"request_id": str(uuid.uuid4()), "message": "Find Stop near Mong Kok"}
    first = client.post('/api/agent/search', json=payload)
    again = client.post('/api/agent/search', json=payload)
    assert first.json == again.json
    assert len(provider.calls) == 1


@pytest.mark.parametrize('radius', [-1, 6, float('nan'), True])
def test_invalid_model_radius_never_reaches_map(tmp_path, radius):
    client = create_app(temp_dir=tmp_path, provider=Planner(plan(radius_km=radius))).test_client()
    turn = start(client).json['turn']
    assert turn['status'] == 'failed'
    assert not turn['blocks']


def test_no_provider_keeps_manual_tools_available(tmp_path):
    client = create_app(temp_dir=tmp_path).test_client()
    assert not client.get('/api/capabilities').json['features']['search_agent']
    assert start(client).status_code == 503
    assert client.get('/api/signs?q=RM1001').status_code == 200
