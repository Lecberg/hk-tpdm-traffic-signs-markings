/* Place search for the map, with no backend.
 *
 * Local first: site/places.json (built from data/places.json by
 * scripts/build_site_indexes.py). Anything else goes to the Lands Department's
 * location search, which allows cross-origin GETs. It answers in HK1980 Grid
 * coordinates, so hk80ToWgs84() converts them for Leaflet. The filtering rules
 * mirror src/svg2dxf/server/places.py so both editions agree.
 */
(function () {
  'use strict';

  var SEARCH_URL = 'https://www.map.gov.hk/gs/api/v1.0.0/locationSearch';
  var HK = { south: 22.1, west: 113.8, north: 22.65, east: 114.5 };
  var MAX_RESULTS = 10;
  var MAX_CACHE = 100;
  var TIMEOUT_MS = 6000;

  // ---- HK1980 Grid (EPSG:2326) -> WGS84 --------------------------------------
  // Inverse transverse Mercator on the International 1924 ellipsoid, then the
  // Lands Department's published HK80 -> WGS84 shift (-5.5" lat, +8.8" lon),
  // good to a few metres anywhere in Hong Kong.

  var A = 6378388, F = 1 / 297, E2 = F * (2 - F), EP2 = E2 / (1 - E2);
  var K0 = 1, E0 = 836694.05, N0 = 819069.80;
  var LAT0 = dms(22, 18, 43.68), LON0 = dms(114, 10, 42.80);
  var RAD = Math.PI / 180;

  function dms(d, m, s) { return d + m / 60 + s / 3600; }

  function meridianArc(phi) {
    var e4 = E2 * E2, e6 = e4 * E2;
    return A * ((1 - E2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi -
      (3 * E2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * Math.sin(2 * phi) +
      (15 * e4 / 256 + 45 * e6 / 1024) * Math.sin(4 * phi) -
      (35 * e6 / 3072) * Math.sin(6 * phi));
  }

  var M0 = meridianArc(LAT0 * RAD);

  function hk80ToWgs84(x, y) {
    var e4 = E2 * E2, e6 = e4 * E2;
    var mu = (M0 + (y - N0) / K0) / (A * (1 - E2 / 4 - 3 * e4 / 64 - 5 * e6 / 256));
    var e1 = (1 - Math.sqrt(1 - E2)) / (1 + Math.sqrt(1 - E2));
    var phi1 = mu + (3 * e1 / 2 - 27 * Math.pow(e1, 3) / 32) * Math.sin(2 * mu) +
      (21 * e1 * e1 / 16 - 55 * Math.pow(e1, 4) / 32) * Math.sin(4 * mu) +
      (151 * Math.pow(e1, 3) / 96) * Math.sin(6 * mu) +
      (1097 * Math.pow(e1, 4) / 512) * Math.sin(8 * mu);
    var sin1 = Math.sin(phi1), cos1 = Math.cos(phi1), tan1 = Math.tan(phi1);
    var c1 = EP2 * cos1 * cos1, t1 = tan1 * tan1;
    var n1 = A / Math.sqrt(1 - E2 * sin1 * sin1);
    var r1 = A * (1 - E2) / Math.pow(1 - E2 * sin1 * sin1, 1.5);
    var d = (x - E0) / (n1 * K0);
    var lat = phi1 - (n1 * tan1 / r1) * (d * d / 2 -
      (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * EP2) * Math.pow(d, 4) / 24 +
      (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * EP2 - 3 * c1 * c1) * Math.pow(d, 6) / 720);
    var lon = LON0 * RAD + (d - (1 + 2 * t1 + c1) * Math.pow(d, 3) / 6 +
      (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * EP2 + 24 * t1 * t1) * Math.pow(d, 5) / 120) / cos1;
    return { latitude: lat / RAD - 5.5 / 3600, longitude: lon / RAD + 8.8 / 3600 };
  }

  // ---- matching --------------------------------------------------------------

  function normalize(value) {
    return String(value || '').toLowerCase().replace(/\s+/g, ' ').trim();
  }

  function insideHk(lat, lon) {
    return Number.isFinite(lat) && Number.isFinite(lon) &&
      lat >= HK.south && lat <= HK.north && lon >= HK.west && lon <= HK.east;
  }

  var saved = [];
  var ready = fetch('places.json')
    .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(function (list) {
      saved = list.filter(function (p) { return insideHk(p.latitude, p.longitude); });
      return true;
    })
    .catch(function (err) {
      console.warn('Saved places unavailable:', err.message);
      return false;
    });

  function searchLocal(query) {
    var term = normalize(query);
    if (!term) return [];
    return saved.filter(function (place) {
      return [place.name_en, place.name_zh_hant].concat(place.aliases || [])
        .some(function (name) { return normalize(name).indexOf(term) !== -1; });
    }).slice(0, 20);
  }

  function text(row, key, limit) {
    return typeof row[key] === 'string' ? row[key].trim().slice(0, limit) : '';
  }

  function remotePoint(row, url) {
    if (!row || typeof row !== 'object') return null;
    var nameEn = text(row, 'nameEN', 160), nameZh = text(row, 'nameZH', 160);
    if (!nameEn || !nameZh) return null;
    if (typeof row.x !== 'number' || typeof row.y !== 'number' ||
        !Number.isFinite(row.x) || !Number.isFinite(row.y)) return null;
    var p = hk80ToWgs84(row.x, row.y);
    if (!insideHk(p.latitude, p.longitude)) return null;
    return {
      name_en: nameEn, name_zh_hant: nameZh,
      address_en: text(row, 'addressEN', 200), address_zh_hant: text(row, 'addressZH', 200),
      district_en: text(row, 'districtEN', 80), district_zh_hant: text(row, 'districtZH', 80),
      latitude: Math.round(p.latitude * 1e7) / 1e7, longitude: Math.round(p.longitude * 1e7) / 1e7,
      kind: 'location_point', source: { agency: 'Lands Department', url: url }
    };
  }

  var cache = new Map();
  var inflight = null;

  // Resolves to {status: 'external'|'no_match'|'unavailable'|'aborted', results}.
  // Only one lookup runs at a time: a newer query aborts the older one.
  function searchRemote(query) {
    var q = String(query || '').trim();
    var term = normalize(q);
    if (!term || q.length > 120) return Promise.resolve({ status: 'no_match', results: [] });
    if (cache.has(term)) return Promise.resolve(cache.get(term));
    if (inflight) inflight.abort();
    var controller = inflight = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, TIMEOUT_MS);
    var url = SEARCH_URL + '?q=' + encodeURIComponent(q);
    return fetch(url, { signal: controller.signal, credentials: 'omit', referrerPolicy: 'no-referrer' })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (rows) {
        if (!Array.isArray(rows)) throw new Error('unexpected shape');
        var seen = {}, found = [];
        rows.forEach(function (row) {
          var point = remotePoint(row, url);
          if (!point) return;
          var key = [normalize(point.name_en), normalize(point.name_zh_hant),
                     point.latitude.toFixed(5), point.longitude.toFixed(5)].join('|');
          if (seen[key]) return;
          seen[key] = true;
          found.push(point);
        });
        var result = { status: found.length ? 'external' : 'no_match',
                       results: found.slice(0, MAX_RESULTS), matched_total: found.length };
        cache.set(term, result);
        if (cache.size > MAX_CACHE) cache.delete(cache.keys().next().value);
        return result;
      })
      .catch(function (err) {
        // A superseded lookup is not a failure; the caller just drops it.
        var aborted = err.name === 'AbortError' && inflight !== controller;
        return { status: aborted ? 'aborted' : 'unavailable', results: [] };
      })
      .finally(function () {
        clearTimeout(timer);
        if (inflight === controller) inflight = null;
      });
  }

  function label(place, language) {
    var zh = language === 'zh-Hant';
    return (zh ? place.name_zh_hant : place.name_en) || place.name_en || place.name_zh_hant || '';
  }

  function detail(place, language) {
    var zh = language === 'zh-Hant';
    if (place.kind === 'district_center') return zh ? '區域中心參考點' : 'District centre point';
    return [zh ? place.district_zh_hant : place.district_en,
            zh ? place.address_zh_hant : place.address_en].filter(Boolean).join(' · ');
  }

  window.svgCadPlaces = {
    ready: function () { return ready; },
    searchLocal: searchLocal,
    searchRemote: searchRemote,
    hk80ToWgs84: hk80ToWgs84,
    label: label,
    detail: detail,
    insideHk: insideHk
  };
})();
