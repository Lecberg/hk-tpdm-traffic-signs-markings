"""Offline Playwright smoke test of the real LangGraph + browser integration.

Uses a deterministic planner, the real catalog/map data, and a disposable local
server. Does not read API keys or make model requests.
"""

import json
import tempfile
import threading
from pathlib import Path

from flask import jsonify, send_from_directory
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import WSGIRequestHandler, make_server

from svg2dxf.server import create_app


ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(WSGIRequestHandler):
    def log_request(self, code='-', size='-'):
        pass


class OfflinePlanner:
    def plan_search(self, message, previous, timeout):
        refine = 'kilometre' in message
        marking = 'RM1001' in message
        return {"action": "refine" if refine else "drawings" if marking else "nearby",
                "place_query": "" if refine or marking else "Mong Kok",
                "sign_query": "" if refine else "RM1001" if marking else "Stop",
                "radius_km": 1 if refine else 0.5,
                "category": "RM" if marking else "TS", "use_map_point": False,
                "clear_sign_filter": False}


def main():
    errors = []
    output = ROOT / 'tmp'
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='svgcad_ui_') as temp:
        app = create_app(temp_dir=temp, provider=OfflinePlanner())

        @app.get('/runtime-config.json')
        def runtime():
            return jsonify(api_enabled=True, api_version=1)

        @app.get('/')
        def index():
            return send_from_directory(ROOT / 'site', 'index.html')

        @app.get('/<path:path>')
        def assets(path):
            return send_from_directory(ROOT / 'site', path)

        server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=QuietHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 900})
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                base = f'http://localhost:{server.server_port}'
                page.goto(base + '/map.html?agent=1')
                page.wait_for_load_state('networkidle')
                request = page.locator('#assistant-agent-input')
                expect(request).to_be_enabled()
                request.fill('Stop signs near Mong Kok within 500 metres')
                page.get_by_role('button', name='Run search', exact=True).click()
                expect(page.get_by_role('button', name='Select: Mong Kok', exact=True)).to_be_visible()
                expect(request).to_be_disabled()
                expect(request).to_be_hidden()
                page.screenshot(path=str(output / 'agent-waiting-desktop.png'))

                # Reload while interrupted: choices and graph state must both survive.
                page.reload()
                page.wait_for_load_state('networkidle')
                expect(page.get_by_role('button', name='Select: Mong Kok', exact=True)).to_be_visible()
                page.get_by_role('button', name='Select: Mong Kok', exact=True).click()
                expect(request).to_be_enabled()
                expect(page.locator('.assistant-agent-count')).to_contain_text('surveyed records')
                page.get_by_role('button', name='Open map', exact=True).last.click()
                expect(page.get_by_role('button', name='Show all signs', exact=True)).to_be_visible()

                request.fill('Make it 1 kilometre')
                page.get_by_role('button', name='Run search', exact=True).click()
                latest = page.locator('.assistant-agent-history > .assistant-agent-turn')
                expect(latest.locator('.assistant-agent-scope')).to_contain_text('1 km')
                expect(latest.locator('.assistant-agent-scope')).to_contain_text('TS_101')
                expect(latest.locator('.assistant-agent-count')).to_contain_text('36')
                expect(page.locator('.assistant-agent-count')).to_have_count(2)
                assert not page.locator('.assistant-agent-previous').evaluate('(e) => e.open')
                assert not latest.locator('.assistant-agent-trace').evaluate('(e) => e.open')
                expect(latest.locator('img[alt="TS_101"]')).to_have_count(1)
                expect(latest.get_by_role('button', name='TS_101', exact=True)).to_have_count(0)
                expect(latest.get_by_role('button', name='Open map', exact=True)).to_be_in_viewport()
                expect(latest.get_by_role('link', name='DXF', exact=True)).to_be_in_viewport()
                latest.get_by_role('button', name='Open map', exact=True).click()
                page.wait_for_load_state('networkidle')
                page.screenshot(path=str(output / 'agent-results-desktop.png'))

                page.set_viewport_size({"width": 390, "height": 844})
                expect(latest.locator('.assistant-agent-count')).to_be_in_viewport()
                expect(latest.get_by_role('link', name='DXF', exact=True)).to_be_in_viewport()
                page.screenshot(path=str(output / 'agent-results-mobile.png'))
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')

                # Older results and execution details stay accessible without cluttering the main card.
                page.locator('.assistant-agent-previous > summary').click()
                page.locator('.assistant-agent-saved > summary').click()
                expect(page.locator('.assistant-agent-saved .assistant-agent-count')).to_be_visible()
                page.locator('.assistant-agent-previous > summary').click()
                latest.locator('.assistant-agent-trace > summary').click()
                expect(latest.locator('.assistant-agent-trace ol')).to_be_visible()
                latest.locator('.assistant-agent-trace > summary').click()

                page.goto(base + '/index.html?agent=1')
                page.wait_for_load_state('networkidle')
                expect(page.locator('.assistant-agent-count')).to_have_count(2)
                request.fill('Show drawing RM1001')
                page.get_by_role('button', name='Run search', exact=True).click()
                expect(latest).to_contain_text('RM_1001')
                expect(latest.get_by_role('link', name='DXF', exact=True)).to_be_visible()
                with page.expect_download() as download:
                    latest.get_by_role('link', name='DXF', exact=True).click()
                assert download.value.suggested_filename.endswith('.dxf')
                assert not errors, errors
                browser.close()
                print(json.dumps({"pass": True, "javascript_errors": errors,
                                  "checks": ["place pause", "refresh/resume", "map action", "radius follow-up",
                                             "latest result first", "collapsed history and trace", "deduplicated drawings",
                                             "visible mobile controls", "gallery shared session", "marking DXF download"],
                                  "screenshots": ["tmp/agent-waiting-desktop.png", "tmp/agent-results-desktop.png",
                                                  "tmp/agent-results-mobile.png"]}))
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()
