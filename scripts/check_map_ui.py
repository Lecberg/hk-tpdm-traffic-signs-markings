"""Offline Playwright check of the public map: search, panel, chips and URL state.

Serves site/ exactly as GitHub Pages would (static files, assistant disabled),
answers the Lands Department place search from a fixture, and blocks every
other outside request. Counts from the browser are compared with the server's
MapData on the same files, so both editions are known to agree.
"""

import functools
import json
import math
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from pyproj import Transformer

from svg2dxf.server.geo import MapData


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'site'
OUT = ROOT / 'tmp'
MONG_KOK = next(p for p in json.loads((SITE / 'places.json').read_text(encoding='utf-8'))
                if p['name_en'] == 'Mong Kok')
LANDS_FIXTURE = [
    {"nameEN": "QUEEN MARY HOSPITAL", "nameZH": "瑪麗醫院", "addressEN": "102 POK FU LAM ROAD",
     "addressZH": "薄扶林道102號", "districtEN": "Southern District", "districtZH": "南區",
     "x": 831487, "y": 814622},
    {"nameEN": "OUTSIDE", "nameZH": "界外", "x": 700000, "y": 700000},   # off the map: dropped
]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def server_count(data, lat, lon, radius, code=None):
    lat_delta = radius / 110.5
    lon_delta = radius / (111.3 * math.cos(math.radians(lat)))
    result = data.query((lat - lat_delta, lon - lon_delta, lat + lat_delta, lon + lon_delta),
                        limit=1, code=code, center=(lat, lon), radius_km=radius)
    return result['matched_total'], {k.upper(): v for k, v in result['code_counts'].items()}


def route_outside(route):
    url = route.request.url
    if url.startswith('https://www.map.gov.hk/gs/api/v1.0.0/locationSearch'):
        route.fulfill(status=200, content_type='application/json',
                      headers={'Access-Control-Allow-Origin': '*'},
                      body=json.dumps(LANDS_FIXTURE, ensure_ascii=False))
    elif url.startswith('http://127.0.0.1') or url.startswith('http://localhost'):
        route.continue_()
    else:
        route.abort()   # basemap tiles etc.: keep the check offline


def scope(page):
    return page.evaluate('window.svgCadMap.getScope()')


def chip_texts(page):
    return page.locator('#scope-chips > .chip').evaluate_all(
        '(els) => els.map(e => (e.querySelector("summary, .chip-label") || e).textContent.trim())')


def main():
    OUT.mkdir(exist_ok=True)
    data = MapData(SITE / 'map-data')
    handler = functools.partial(QuietHandler, directory=str(SITE))
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{httpd.server_port}'
    errors, checks = [], []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': 1280, 'height': 800})
            context.route('**/*', route_outside)
            page = context.new_page()
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(base + '/map.html')
            page.wait_for_function('window.svgCadMap && window.svgCadPlaces && window.svgCadSearch')
            page.evaluate('window.svgCadMap.ready()')

            # 1. Browser counts equal the server's MapData on the same files.
            lat, lon = MONG_KOK['latitude'], MONG_KOK['longitude']
            for radius in (0.5, 1, 5):
                for code in (None, 'TS101'):
                    js = page.evaluate('(q) => window.svgCadMap.queryRadius(q)',
                                       {'latitude': lat, 'longitude': lon, 'radius_km': radius, 'code': code})
                    total, counts = server_count(data, lat, lon, radius, code)
                    assert js['matched_total'] == total, (radius, code, js['matched_total'], total)
                    assert js['code_counts'] == counts, (radius, code)
                    assert js['data_complete']
            checks.append('browser counts match server MapData (Mong Kok, 0.5/1/5 km, all and TS101)')

            # 2. HK1980 grid conversion agrees with pyproj.
            transformer = Transformer.from_crs('EPSG:2326', 'EPSG:4326', always_xy=True)
            for x, y in [(831487, 814622), (836694.05, 819069.80), (815000, 840000), (860000, 825000)]:
                plon, plat = transformer.transform(x, y)
                js = page.evaluate('([x, y]) => window.svgCadPlaces.hk80ToWgs84(x, y)', [x, y])
                metres = math.hypot((js['latitude'] - plat) * 110574,
                                    (js['longitude'] - plon) * 111320 * math.cos(math.radians(plat)))
                assert metres < 5, (x, y, metres)
            checks.append('HK1980 conversion within 5 m of pyproj')

            box = page.locator('#filter')
            # 3. Codes filter live from the box, exact and partial.
            box.fill('115')
            page.wait_for_function('window.svgCadMap.getScope().code && window.svgCadMap.getScope().code.text === "115"')
            assert scope(page)['code'] == {'text': '115', 'exact': False, 'source': 'box'}
            box.fill('TS 101')
            page.wait_for_function('window.svgCadMap.getScope().code && window.svgCadMap.getScope().code.exact')
            assert scope(page)['code']['text'] == 'TS101'
            box.fill('')
            page.wait_for_function('!window.svgCadMap.getScope().code')
            checks.append('code filter: partial, exact and cleared')

            # 4. Place search -> chips, panel and count.
            box.fill('mong kok')
            option = page.get_by_role('option', name='Mong Kok')
            expect(option.first).to_be_visible()
            box.press('Enter')
            panel = page.locator('#map-panel')
            expect(panel).to_be_visible()
            total, _ = server_count(data, lat, lon, 0.5)
            expect(panel.locator('.result-count strong')).to_have_text(f'{total:,}')
            assert chip_texts(page)[:2] == ['Mong Kok', '500 m'], chip_texts(page)
            assert 'r=0.5' in page.url and 'place=Mong+Kok' in page.url
            page.screenshot(path=str(OUT / 'map-search-desktop.png'))
            checks.append('place search opens the panel with the server count')

            # 5. Radius chip menu changes the radius and refits.
            page.locator('.chip-radius summary').click()
            page.locator('.chip-menu').get_by_role('button', name='1 km').click()
            total_1km, _ = server_count(data, lat, lon, 1)
            expect(panel.locator('.result-count strong')).to_have_text(f'{total_1km:,}')
            assert 'r=1&' in page.url or page.url.endswith('r=1')
            checks.append('radius chip re-counts')

            # 6. Filter to one drawing from the breakdown, then remove the chip.
            panel.get_by_role('button', name='Show only TS_115').click()
            total_115, _ = server_count(data, lat, lon, 1, 'TS115')
            expect(panel.locator('.result-count strong')).to_have_text(f'{total_115:,}')
            assert 'TS_115' in chip_texts(page)
            page.get_by_role('button', name='Remove drawing filter TS_115').click()
            expect(panel.locator('.result-count strong')).to_have_text(f'{total_1km:,}')
            checks.append('breakdown filter and chip removal')

            # 7. Back restores the previous search; reload restores the current one.
            page.go_back()
            expect(panel.locator('.result-count strong')).to_have_text(f'{total_115:,}')
            page.go_forward()
            expect(panel.locator('.result-count strong')).to_have_text(f'{total_1km:,}')
            page.reload()
            page.wait_for_function('window.svgCadMap && window.svgCadMap.getScope().area')
            expect(page.locator('#map-panel .result-count strong')).to_have_text(f'{total_1km:,}')
            checks.append('back/forward and reload restore the search')

            # 8. Dragging the radius handle changes the radius.
            handle = page.locator('.radius-handle')
            hb = handle.bounding_box()
            page.mouse.move(hb['x'] + hb['width'] / 2, hb['y'] + hb['height'] / 2)
            page.mouse.down()
            page.mouse.move(hb['x'] - 80, hb['y'] + hb['height'] / 2, steps=8)
            page.mouse.up()
            page.wait_for_function('window.svgCadMap.getScope().area.radius_km < 1')
            dragged = scope(page)['area']['radius_km']
            total_drag, _ = server_count(data, lat, lon, dragged)
            expect(page.locator('#map-panel .result-count strong')).to_have_text(f'{total_drag:,}')
            checks.append(f'radius handle drag re-counts ({dragged} km)')

            # 9. Removing the place chip clears the area and closes the panel.
            page.get_by_role('button', name='Remove place Mong Kok').click()
            page.wait_for_function('!window.svgCadMap.getScope().area')
            expect(page.locator('#map-panel')).to_be_hidden()
            checks.append('place chip removal')

            # 10. A drawing name finds its code.
            box.fill('stop')
            stop = page.get_by_role('option').filter(has_text='TS_101')
            expect(stop.first).to_be_visible()
            stop.first.click()
            page.wait_for_function('window.svgCadMap.getScope().code && window.svgCadMap.getScope().code.text === "TS101"')
            assert 'TS_101' in chip_texts(page)
            page.get_by_role('button', name='Remove drawing filter TS_101').click()
            checks.append('drawing-name suggestion')

            # 11. Lands Department places (fixture), converted from HK1980.
            box.fill('Queen Mary Hospital')
            qmh = page.get_by_role('option').filter(has_text='QUEEN MARY HOSPITAL')
            expect(qmh.first).to_be_visible()
            expect(page.get_by_role('option').filter(has_text='OUTSIDE')).to_have_count(0)
            qmh.first.click()
            area = scope(page)['area']
            assert 22.26 < area['latitude'] < 22.28 and 114.12 < area['longitude'] < 114.14, area
            assert area['place']['source']['url'].startswith('https://www.map.gov.hk/')
            checks.append('Lands Department place search')

            # 12. Right-click: search around here.
            page.locator('#map').click(button='right', position={'x': 300, 'y': 300})
            page.get_by_role('button', name='Search around here').click()
            page.wait_for_function('window.svgCadMap.getScope().area.place.name_en === "Selected point"')
            checks.append('right-click search around a point')

            # 13. Sign popup: signs like this nearby.
            page.evaluate('''() => {
              const s = window.svgCadMap; s.clearScope();
              s.setArea({latitude: %f, longitude: %f, radius_km: 0.25});
            }''' % (lat, lon))
            page.evaluate('window._signsMap.setView([%f, %f], 18, {animate: false})' % (lat, lon))
            page.wait_for_function('document.querySelectorAll(".sign-marker, .leaflet-interactive").length > 5')
            page.evaluate('''() => {
              let opened = false;
              window._signsMap.eachLayer(l => {
                if (!opened && l.getPopup && l.getPopup() && /data-popup-action/.test(l.getPopup().getContent())) {
                  l.openPopup(); opened = true;
                }
              });
            }''')
            nearby = page.get_by_role('button', name='Signs like this nearby')
            expect(nearby).to_be_visible()
            nearby.click()
            page.wait_for_function('window.svgCadMap.getScope().code && window.svgCadMap.getScope().code.exact')
            s = scope(page)
            assert s['area']['radius_km'] == 0.5 and s['area']['place']['name_en'].startswith('Near TS_')
            checks.append('popup: signs like this nearby')

            # 14. Narrow screens: bottom sheet, no sideways scroll.
            page.set_viewport_size({'width': 390, 'height': 844})
            page.goto(base + f'/map.html?lat={lat}&lng={lon}&r=0.5&place=Mong+Kok')
            page.wait_for_function('document.getElementById("map-panel").dataset.sheet === "half"')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('.map-panel-grip').click()
            page.wait_for_function('document.getElementById("map-panel").dataset.sheet === "full"')
            page.screenshot(path=str(OUT / 'map-search-mobile.png'))
            checks.append('mobile bottom sheet')

            # 15. Dark theme renders; the public edition has no assistant.
            page.set_viewport_size({'width': 1280, 'height': 800})
            page.emulate_media(color_scheme='dark')
            page.reload()
            page.wait_for_function('window.svgCadMap && window.svgCadMap.getScope().area')
            expect(page.locator('#map-panel .result-count strong')).to_have_text(f'{total:,}')
            page.screenshot(path=str(OUT / 'map-search-dark.png'))
            assert page.locator('.assistant-agent, #assistant-agent-input').count() == 0
            checks.append('dark theme; no assistant in the public edition')

            assert not errors, errors
            browser.close()
    finally:
        httpd.shutdown()
    print(json.dumps({'pass': True, 'checks': checks,
                      'screenshots': ['tmp/map-search-desktop.png', 'tmp/map-search-mobile.png',
                                      'tmp/map-search-dark.png']}, indent=1))


if __name__ == '__main__':
    main()
