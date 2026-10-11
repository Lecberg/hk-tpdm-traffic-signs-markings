"""Local API guarantees that do not need Docker or a model key."""

import json
import sys
from types import SimpleNamespace

import pytest

from svg2dxf.server import create_app
from svg2dxf.server.catalog import Catalog
from svg2dxf.server.geo import MapData
from svg2dxf.server.agent import provider_from_env


@pytest.fixture
def client(tmp_path):
    app = create_app()
    app.testing = True
    return app.test_client()


def test_capabilities_and_code_forms(client):
    cap = client.get('/api/capabilities').json
    assert cap['api_version'] == 1
    assert cap['features'] == {'search': True, 'map_query': True, 'search_agent': False}
    assert cap['metadata_coverage']['total_drawings'] == 1327
    assert cap['metadata_coverage']['verified_bilingual'] == 100
    assert cap['metadata_coverage']['source_checked_bilingual'] == 0
    codes = [client.get('/api/signs/' + code).json['code']
             for code in ('TS101', 'TS 101', 'TS_101')]
    assert codes == ['TS_101'] * 3
    found = client.get('/api/signs?q=TS%20101').json
    assert found['results'][0]['code'] == 'TS_101'
    assert client.get('/api/signs?q=%E5%81%9C%E8%BB%8A').json['results'][0]['code'] == 'TS_101'
    assert client.get('/api/signs/TS101').json['metadata']['name_en'] == 'Stop'


def test_metadata_requires_known_sourced_bilingual_code(tmp_path):
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    source = tmp_path / 'metadata.json'
    source.write_text(json.dumps([{'code': 'TS_101', 'name_en': 'Example',
        'name_zh_hant': '示例', 'source': {'url': 'https://example.test'},
        'review_status': 'verified'}]), encoding='utf-8')
    catalog = Catalog(root / 'site', source)
    assert catalog.search('示例')['results'][0]['code'] == 'TS_101'
    source.write_text(json.dumps([{'code': 'NO_SUCH_CODE', 'name_en': 'A',
        'name_zh_hant': '甲', 'source': {'url': 'https://example.test'},
        'review_status': 'verified'}]), encoding='utf-8')
    with pytest.raises(ValueError):
        Catalog(root / 'site', source)


def test_radius_query_and_incomplete_cell(tmp_path):
    directory = tmp_path / 'map'
    directory.mkdir()
    (directory / 'index.json').write_text(json.dumps({'cell': 0.05,
        'cells': {'2280_440': 2}, 'splits': {}}), encoding='utf-8')
    (directory / '2280_440.json').write_text(json.dumps([
        ['TS101', 114.001, 22.001, None], ['TS101', 114.04, 22.04, 0]]), encoding='utf-8')
    data = MapData(directory)
    near = data.query([22, 114, 22.05, 114.05], center=[22.001, 114.001], radius_km=0.1)
    assert near['matched_total'] == 1
    assert near['data_complete']
    (directory / '2280_440.json').unlink()
    data._read.cache_clear()
    missing = data.query([22, 114, 22.05, 114.05])
    assert missing['data_complete'] is False
    assert missing['missing_cells'] == ['2280_440']


def test_split_cell_selection_and_full_counts(tmp_path):
    directory = tmp_path / 'map'
    directory.mkdir()
    index = {'cell': 0.05, 'cells': {'2280_440': 3},
             'splits': {'2280_440': {'n': 2, 'parts': {'0-0': 2, '1-1': 1}}}}
    (directory / 'index.json').write_text(json.dumps(index), encoding='utf-8')
    (directory / '2280_440_0-0.json').write_text(json.dumps([
        ['TS101', 114.001, 22.001, 0], ['TS101', 114.002, 22.002, 90]]), encoding='utf-8')
    data = MapData(directory)
    near = data.query([22, 114, 22.02, 114.02], limit=1)
    assert near['data_complete']
    assert near['matched_total'] == 2
    assert near['truncated']
    assert near['code_counts'] == {'TS101': 2}
    wider = data.query([22, 114, 22.05, 114.05])
    assert not wider['data_complete']
    assert wider['missing_cells'] == ['2280_440_1-1']


def test_chat_and_conversion_endpoints_are_gone(client):
    # The assistant is the search agent only; uploads, conversion and free chat
    # were removed with their tabs.
    for method, path in (('post', '/api/uploads'), ('post', '/api/conversions'),
                         ('get', '/api/files/abc'), ('post', '/api/chat'),
                         ('get', '/api/chat/history'), ('get', '/api/session')):
        assert getattr(client, method)(path).status_code in (404, 405), path


def test_cross_origin_posts_are_rejected(client):
    cross = client.post('/api/map/query', json={}, headers={'Origin': 'https://evil.test'})
    assert cross.status_code == 403
    assert client.post('/api/agent/search', json={},
                       headers={'Origin': 'https://evil.test'}).status_code == 403


def test_map_query_bound_validation(client):
    bad = client.post('/api/map/query', json={'latitude': 22.3, 'longitude': 114.1,
                                             'radius_km': 100})
    assert bad.status_code == 400
    ok = client.post('/api/map/query', json={'latitude': 22.3193,
                                            'longitude': 114.1694, 'radius_km': 0.1})
    assert ok.status_code == 200
    assert ok.json['data_complete']
    assert ok.json['matched_total'] >= len(ok.json['returned_records'])


def test_provider_selection_and_request_options(monkeypatch, tmp_path):
    created = []

    class FakeOpenAI:
        def __init__(self, **options):
            self.options = options
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.complete))
            created.append(self)

        def complete(self, **options):
            self.request = options
            call = SimpleNamespace(function=SimpleNamespace(name='plan_search', arguments='{}'))
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call]))])

    monkeypatch.setitem(sys.modules, 'openai', SimpleNamespace(OpenAI=FakeOpenAI))
    name, model, provider = provider_from_env({'AI_PROVIDER': 'openai', 'OPENAI_API_KEY': 'test-openai'})
    assert (name, model) == ('openai', 'gpt-4.1-mini')
    assert 'base_url' not in created[-1].options
    assert provider.plan_search('hello', {}, 3) == {}
    assert created[-1].request['parallel_tool_calls'] is False
    assert created[-1].request['tool_choice'] == 'required'
    assert created[-1].request['tools'][0]['function']['name'] == 'plan_search'

    name, model, provider = provider_from_env({'AI_PROVIDER': 'deepseek',
        'OPENAI_API_KEY': 'ignored', 'DEEPSEEK_API_KEY': 'test-deepseek'})
    assert (name, model) == ('deepseek', 'deepseek-flash')
    assert created[-1].options['base_url'] == 'https://api.deepseek.com'
    assert created[-1].options['api_key'] == 'test-deepseek'
    provider.plan_search('hello', {}, 3)
    assert created[-1].request['max_tokens'] == 500
    assert created[-1].request['extra_body'] == {'thinking': {'type': 'disabled'}}
    assert 'parallel_tool_calls' not in created[-1].request

    name, model, provider = provider_from_env({'AI_PROVIDER': 'vercel',
        'AI_GATEWAY_API_KEY': 'test-gateway', 'AI_GATEWAY_MODEL': 'openai/gpt-6-astra'})
    assert (name, model) == ('vercel', 'openai/gpt-6-astra')
    assert created[-1].options['base_url'] == 'https://ai-gateway.vercel.sh/v1'
    provider.plan_search('hello', {}, 3)
    assert created[-1].request['max_completion_tokens'] == 500

    name, model, provider = provider_from_env({'AI_PROVIDER': 'custom',
        'CUSTOM_API_BASE_URL': 'https://models.example.test/v1',
        'CUSTOM_API_KEY': 'test-custom', 'CUSTOM_MODEL': 'my-model',
        'OPENAI_API_KEY': 'ignored'})
    assert (name, model) == ('custom', 'my-model')
    assert created[-1].options['base_url'] == 'https://models.example.test/v1'
    assert created[-1].options['api_key'] == 'test-custom'
    provider.plan_search('hello', {}, 3)
    assert created[-1].request['max_tokens'] == 500
    assert created[-1].request['tool_choice'] == 'required'
    assert 'parallel_tool_calls' not in created[-1].request

    _, _, provider = provider_from_env({'AI_PROVIDER': 'deepseek', 'OPENAI_API_KEY': 'ignored'})
    assert provider is None
    _, _, provider = provider_from_env({'AI_PROVIDER': 'custom',
        'CUSTOM_API_BASE_URL': 'http://host.docker.internal:1234/v1',
        'CUSTOM_MODEL': 'local-model'})
    assert provider is None
    with pytest.raises(ValueError):
        provider_from_env({'AI_PROVIDER': 'unknown'})
    with pytest.raises(ValueError):
        provider_from_env({'AI_PROVIDER': 'vercel', 'AI_GATEWAY_MODEL': 'bad-model'})
    with pytest.raises(ValueError, match='CUSTOM_API_BASE_URL'):
        provider_from_env({'AI_PROVIDER': 'custom', 'CUSTOM_API_BASE_URL': 'file:///tmp/model',
            'CUSTOM_API_KEY': 'test-custom', 'CUSTOM_MODEL': 'my-model'})
    with pytest.raises(ValueError, match='CUSTOM_API_BASE_URL'):
        provider_from_env({'AI_PROVIDER': 'custom', 'CUSTOM_API_BASE_URL': 'https://example.test/v1?key=abc'})
    with pytest.raises(ValueError, match='omit /chat/completions'):
        provider_from_env({'AI_PROVIDER': 'custom',
            'CUSTOM_API_BASE_URL': 'https://example.test/v1/chat/completions'})
    with pytest.raises(ValueError, match='CUSTOM_MODEL and CUSTOM_API_BASE_URL'):
        provider_from_env({'AI_PROVIDER': 'custom', 'CUSTOM_API_KEY': 'test-custom'})

    monkeypatch.setenv('AI_PROVIDER', 'deepseek')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-deepseek')
    app = create_app()
    capabilities = app.test_client().get('/api/capabilities').json
    assert capabilities['features']['search_agent']
    assert capabilities['provider'] == 'deepseek'
    assert capabilities['model'] == 'deepseek-flash'

    monkeypatch.setenv('AI_PROVIDER', 'custom')
    monkeypatch.setenv('CUSTOM_API_BASE_URL', 'https://models.example.test/v1')
    monkeypatch.setenv('CUSTOM_API_KEY', 'test-custom')
    monkeypatch.setenv('CUSTOM_MODEL', 'my-model')
    custom = create_app().test_client().get('/api/capabilities').json
    assert custom['provider'] == 'custom'
    assert custom['model'] == 'my-model'
    assert 'test-custom' not in json.dumps(custom)
    assert 'models.example.test' not in json.dumps(custom)
