"""Offline Playwright check of the Docker assistant inside the map page.

Uses a deterministic tool-calling model, the real catalog/map data and a
disposable local server. Does not read API keys or make model requests.
"""

import json
import re
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


class OfflineModel:
    """Calls the agent's tools the way a model would, one step at a time,
    reading each result before choosing the next call."""

    PLACES = ('tuen mun', 'mong kok', 'tsim sha tsui')

    def complete(self, messages, tools, timeout, final=False):
        last_user = max(i for i, m in enumerate(messages) if m['role'] == 'user')
        text = messages[last_user]['content'].lower()
        done = [json.loads(m['content']) for m in messages[last_user:] if m['role'] == 'tool']

        def call(*calls):
            return {"content": "", "tool_calls": [
                {"id": f"c{len(done)}_{i}", "name": name, "arguments": json.dumps(args)}
                for i, (name, args) in enumerate(calls)]}

        def say(reply):
            return {"content": reply, "tool_calls": []}

        if 'rm1001' in text:
            return call(('search_signs', {"query": "RM1001", "category": "RM"})) if not done else \
                say('RM_1001 is a road-marking drawing.')
        if 'kilometre' in text or 'same area' in text:
            current = re.search(r'place_id "current" = .*?, radius ([\d.]+) km, (?:sign (TS_\d+[A-Z]?))?',
                                messages[0]['content'])
            radius = 1 if 'kilometre' in text else float(current.group(1))
            if not done:
                return call(('find_nearby_signs', {"place_id": "current", "radius_km": radius,
                                                   "code": current.group(2) or ""}))
            return say(f"Found {done[-1]['matched_total']} surveyed records within {radius:g} km.")
        names = sorted((n for n in self.PLACES if n in text), key=text.index)
        steps = ([('search_signs', {"query": "Stop", "category": "TS"})] if 'stop' in text else []) + \
            [('resolve_place', {"query": n.title()}) for n in names]
        if len(done) < len(steps):
            return call(steps[len(done)])
        counts = [r for r in done if 'matched_total' in r and 'place_id' in r and 'radius_km' in r]
        if not counts:
            ids = [r['place_id'] for r in done if 'place_id' in r]
            radius = 0.5
            return call(*[('find_nearby_signs', {"place_id": pid, "radius_km": radius,
                                                 "code": "TS101" if 'stop' in text else ""}) for pid in ids])
        return say(' '.join(f"{r['place']} has {r['matched_total']} surveyed records." for r in counts))


def route_outside(route):
    url = route.request.url
    if url.startswith('http://localhost') or url.startswith('http://127.0.0.1'):
        route.continue_()
    else:
        route.abort()   # tiles and place search: keep the check offline


def main():
    errors = []
    output = ROOT / 'tmp'
    output.mkdir(exist_ok=True)
    app = create_app(provider=OfflineModel())

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
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://localhost:{server.server_port}'
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            context.route('**/*', route_outside)
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))

            # Nothing of the old assistant is left: no launcher, tabs, chat or convert.
            page.goto(base + '/map.html?agent=1')
            page.wait_for_load_state('networkidle')
            request = page.locator('#assistant-agent-input')
            expect(request).to_be_enabled()
            for gone in ('.assistant-open', '.assistant-tasks', '#map-search-mode', '#map-ask-input',
                         '#assistant-view-chat', '#assistant-view-convert'):
                assert page.locator(gone).count() == 0, gone

            # The search box offers the assistant first for a sentence.
            box = page.locator('#filter')
            box.fill('stop signs near mong kok')
            expect(page.locator('.suggest-option.kind-ask').first).to_be_visible()
            assert 'kind-ask' in page.locator('.suggest-option').first.get_attribute('class')
            box.press('Escape')
            box.fill('')

            # An ambiguous place pauses the agent's loop; choices are also numbered map pins.
            # ("Tuen Mun" is both a town and a district.)
            request.fill('Stop signs near Tuen Mun within 500 metres')
            page.get_by_role('button', name='Run search', exact=True).click()
            expect(page.get_by_role('button', name='Select: Tuen Mun', exact=True)).to_be_visible()
            expect(request).to_be_hidden()
            expect(page.locator('.choice-pin')).to_have_count(2)
            page.screenshot(path=str(output / 'agent-waiting-desktop.png'))

            # Reload while interrupted: the choice and the pins survive; a pin resumes it.
            page.reload()
            page.wait_for_load_state('networkidle')
            expect(page.get_by_role('button', name='Select: Tuen Mun', exact=True)).to_be_visible()
            page.locator('.choice-pin').first.click()
            expect(request).to_be_enabled()
            latest = page.locator('.assistant-agent-history > .assistant-agent-turn')
            expect(latest.locator('.assistant-agent-count')).to_contain_text('surveyed records')
            # The model's reply sits above the result card, and its count matches the card.
            card_count = latest.locator('.assistant-agent-count strong').inner_text()
            expect(latest.locator('.assistant-agent-answer')).to_contain_text(f'Tuen Mun has {card_count}')

            # A finished search applies itself to the map, and the panel's own
            # count (computed in the browser) agrees with the agent's.
            page.wait_for_function('window.svgCadMap.getScope().area && window.svgCadMap.getScope().code')
            scope = page.evaluate('window.svgCadMap.getScope()')
            assert scope['area']['radius_km'] == 0.5 and scope['code']['text'] == 'TS101', scope
            agent_count = latest.locator('.assistant-agent-count strong').inner_text()
            expect(page.locator('.result-count strong')).to_have_text(agent_count)
            expect(page.get_by_role('button', name='Show all signs', exact=True)).to_be_visible()
            assert 'TS_101' in page.locator('#scope-chips').inner_text()

            # Hand edit: widen to 2 km with the chip, then refine without a radius.
            page.locator('.chip-radius summary').click()
            page.locator('.chip-menu').get_by_role('button', name='2 km').click()
            page.wait_for_function('window.svgCadMap.getScope().area.radius_km === 2')
            request.fill('Show the same area')
            page.get_by_role('button', name='Run search', exact=True).click()
            expect(latest.locator('.assistant-agent-scope')).to_contain_text('2 km')

            # A normal refinement still works and stays in sync with the map.
            request.fill('Make it 1 kilometre')
            page.get_by_role('button', name='Run search', exact=True).click()
            expect(latest.locator('.assistant-agent-scope')).to_contain_text('1 km')
            expect(latest.locator('.assistant-agent-scope')).to_contain_text('TS_101')
            page.wait_for_function('window.svgCadMap.getScope().area.radius_km === 1')
            km_count = latest.locator('.assistant-agent-count strong').inner_text()
            expect(page.locator('.result-count strong')).to_have_text(km_count)
            expect(page.locator('.assistant-agent-count')).to_have_count(3)
            assert not page.locator('.assistant-agent-previous').evaluate('(e) => e.open')
            assert not latest.locator('.assistant-agent-trace').evaluate('(e) => e.open')
            expect(latest.locator('img[alt="TS_101"]')).to_have_count(1)
            expect(latest.get_by_role('button', name='Show on map', exact=True)).to_be_visible()
            page.screenshot(path=str(output / 'agent-results-desktop.png'))

            # Older results and execution details stay reachable.
            page.locator('.assistant-agent-previous > summary').click()
            page.locator('.assistant-agent-saved > summary').first.click()
            expect(page.locator('.assistant-agent-saved .assistant-agent-count').first).to_be_visible()
            page.locator('.assistant-agent-previous > summary').click()
            latest.locator('.assistant-agent-trace > summary').click()
            expect(latest.locator('.assistant-agent-trace ol')).to_be_visible()
            latest.locator('.assistant-agent-trace > summary').click()

            # Drawings are downloadable from an agent answer.
            request.fill('Show drawing RM1001')
            page.get_by_role('button', name='Run search', exact=True).click()
            expect(latest).to_contain_text('RM_1001')
            with page.expect_download() as download:
                latest.get_by_role('link', name='DXF', exact=True).click()
            assert download.value.suggested_filename.endswith('.dxf')

            # Narrow screens: the panel is a bottom sheet with no sideways scroll.
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_function('document.getElementById("map-panel").dataset.sheet')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(output / 'agent-results-mobile.png'))

            # A comparison shows one result row per place, each with its own map button
            # (a fresh visit, so the per-minute limit is not shared).
            compare = browser.new_context(viewport={"width": 1440, "height": 900})
            compare.route('**/*', route_outside)
            c = compare.new_page()
            c.on('pageerror', lambda error: errors.append(str(error)))
            c.goto(base + '/map.html?agent=1')
            c.wait_for_load_state('networkidle')
            c.locator('#assistant-agent-input').fill('Compare Stop signs near Mong Kok and Tsim Sha Tsui')
            c.get_by_role('button', name='Run search', exact=True).click()
            rows = c.locator('.assistant-agent-history > .assistant-agent-turn .assistant-agent-map-result')
            expect(rows).to_have_count(2)
            expect(rows.nth(0).locator('h4')).to_have_text('Mong Kok')
            expect(rows.nth(1).locator('h4')).to_have_text('Tsim Sha Tsui')
            c.wait_for_function('window.svgCadMap.getScope().area && '
                                'window.svgCadMap.getScope().area.place.name_en === "Tsim Sha Tsui"')
            rows.nth(0).get_by_role('button', name='Show on map', exact=True).click()
            c.wait_for_function('window.svgCadMap.getScope().area.place.name_en === "Mong Kok"')
            first_count = rows.nth(0).locator('.assistant-agent-count strong').inner_text()
            expect(c.locator('.result-count strong')).to_have_text(first_count)
            c.screenshot(path=str(output / 'agent-compare-desktop.png'))

            # Gallery hand-off (a fresh visit, so the per-minute limit is not shared).
            gallery = browser.new_context(viewport={"width": 1280, "height": 800})
            gallery.route('**/*', route_outside)
            g = gallery.new_page()
            g.on('pageerror', lambda error: errors.append(str(error)))
            g.goto(base + '/index.html')
            g.wait_for_load_state('networkidle')
            g.locator('#search').fill('stop signs near mong kok')
            g.get_by_role('button', name='Ask on the map →').click()
            g.wait_for_url('**/map.html*')
            g.wait_for_function('document.querySelectorAll(".assistant-agent-turn").length === 1')
            assert 'ask=' not in g.url
            expect(g.locator('.assistant-agent-history .assistant-agent-count')).to_be_visible()
            g.reload()
            g.wait_for_load_state('networkidle')
            expect(g.locator('.assistant-agent-history > .assistant-agent-turn')).to_have_count(1)
            assert g.locator('.assistant-agent-previous').count() == 0   # sent exactly once

            assert not errors, errors
            browser.close()
            print(json.dumps({"pass": True, "javascript_errors": errors,
                              "checks": ["no launcher/tabs/chat/convert", "ask suggestion in search box",
                                         "ambiguous place pauses with numbered pins", "reload and resume by pin",
                                         "model reply matches the card", "result applied to map; counts agree",
                                         "refine follows hand-edited radius", "1 km refinement agrees with map",
                                         "collapsed history and trace", "drawing DXF download",
                                         "mobile bottom sheet", "comparison shows one row per place",
                                         "gallery hand-off sent exactly once"],
                              "screenshots": ["tmp/agent-waiting-desktop.png", "tmp/agent-results-desktop.png",
                                              "tmp/agent-results-mobile.png", "tmp/agent-compare-desktop.png"]},
                             indent=1))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
