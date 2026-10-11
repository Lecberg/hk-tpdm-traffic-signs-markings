/* Traffic signs map.
 * Sign locations come from the Transport Department's Digitized Traffic Aids
 * Drawings dataset (Traffic Sign Abbreviation points), pre-processed into
 * per-cell JSON by scripts/build_map_data.py.
 *
 * Zoom tiers: 10-12 cluster bubbles from per-cell counts (no data fetch),
 * 13-14 cluster bubbles binned from real points, 15-16 dots, 17+ sign SVGs.
 *
 * The search scope (a circle around a place, a drawing code, or both) lives
 * here too; map-search.js and map-panel.js drive it through window.svgCadMap
 * and listen for `svgcad:scope-changed`.
 */
(function () {
  'use strict';

  var DOT_ZOOM = 15;        // below this, cluster bubbles
  var BIN_ZOOM = 13;        // from this zoom, clusters are binned real points
  var ICON_ZOOM = 17;       // at/above this, draw SVG icons instead of dots
  var MAX_ICONS = 600;      // icon markers are DOM nodes — cap them
  var BIN_PX = 96;          // screen-pixel bin size for zoom 13-14 clusters
  var CELL_RETRY_MS = 1200; // wait before retrying a failed cell fetch once

  // #zoom/lat/lng deep links, e.g. map.html#17/22.3193/114.1694
  var view = { center: [22.3193, 114.1694], zoom: 12 };
  var hash = location.hash.slice(1).split('/').map(Number);
  if (hash.length === 3 && hash.every(isFinite)) {
    view = { center: [hash[1], hash[2]], zoom: hash[0] };
  }

  var map = L.map('map', {
    center: view.center,
    zoom: view.zoom,
    minZoom: 10,
    maxZoom: 20,
    maxBounds: [[22.1, 113.8], [22.65, 114.5]],
    preferCanvas: true
  });

  var landsDept = '&copy; <a href="https://portal.csdi.gov.hk/">Lands Department</a>';
  var cartoAttr = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>';

  function hkLayer(path, zIndex) {
    return L.tileLayer('https://mapapi.geodata.gov.hk/gs/api/v1.0.0/xyz/' + path + '/wgs84/{z}/{x}/{y}.png', {
      maxZoom: 20,
      zIndex: zIndex,
      attribution: landsDept
    });
  }

  // CARTO basemaps use the *_nolabels variants so the HK GeoData label
  // overlays provide consistent, bilingual-capable labels everywhere.
  function cartoLayer(style) {
    return L.tileLayer('https://{s}.basemaps.cartocdn.com/' + style + '/{z}/{x}/{y}{r}.png', {
      maxZoom: 20,
      zIndex: 1,
      attribution: cartoAttr
    });
  }

  var baseLayers = {
    'Map': hkLayer('basemap', 1).addTo(map),
    'Satellite': hkLayer('imagery', 1),
    'Light': cartoLayer('light_nolabels'),
    'OpenStreetMap': L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 20,
      maxNativeZoom: 19,
      zIndex: 1,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    })
  };

  // Street/place name overlays sit above whichever basemap is active.
  var overlays = {
    'Street names (EN)': hkLayer('label/hk/en', 5).addTo(map),
    '街道名稱 (中文)': hkLayer('label/hk/tc', 5)
  };

  var layersControl = L.control.layers(baseLayers, overlays).addTo(map);

  // The panel should open on click (the toggle's own handler) and stay open
  // until the map is clicked — not flicker in and out on hover, so unbind
  // the hover handlers Leaflet wires up in Control.Layers._initLayout.
  L.DomEvent.off(layersControl.getContainer(), {
    mouseenter: layersControl._expandSafely,
    mouseleave: layersControl.collapse
  }, layersControl);

  // Closing needs to be deferred by one animation. Leaflet's collapse() simply
  // drops the `-expanded` class, which un-pads the panel and re-shows the
  // toggle button while the list is still fading — so hold that off until the
  // exit animation (map.css `.is-closing`) has played.
  var LAYERS_CLOSE_MS = 130;
  var layersBox = layersControl.getContainer();
  var baseCollapse = L.Control.Layers.prototype.collapse;
  var baseExpand = L.Control.Layers.prototype.expand;
  var layersCloseTimer = null;

  layersControl.collapse = function () {
    if (layersCloseTimer ||
        !L.DomUtil.hasClass(layersBox, 'leaflet-control-layers-expanded')) return this;
    var control = this;
    L.DomUtil.addClass(layersBox, 'is-closing');
    layersCloseTimer = setTimeout(function () {
      layersCloseTimer = null;
      L.DomUtil.removeClass(layersBox, 'is-closing');
      baseCollapse.call(control);
    }, LAYERS_CLOSE_MS);
    return this;
  };

  layersControl.expand = function () {
    if (layersCloseTimer) {
      clearTimeout(layersCloseTimer);
      layersCloseTimer = null;
      L.DomUtil.removeClass(layersBox, 'is-closing');
    }
    return baseExpand.call(this);
  };

  // Leaflet bound the map-click collapse to the prototype method before the
  // override above existed, so re-point it at the instance.
  map.off('click', L.Control.Layers.prototype.collapse, layersControl);
  map.on('click', function () { layersControl.collapse(); });

  map.attributionControl.addAttribution('Signs: <a href="https://data.gov.hk/en-data/dataset/hk-td-tis_16-traffic-aids-drawings-v2">Transport Department</a>');


  var statusEl = document.getElementById('status');
  var clearScopeEl = document.getElementById('clear-scope');

  var HK = { south: 22.1, west: 113.8, north: 22.65, east: 114.5 };
  var MIN_RADIUS = 0.05, MAX_RADIUS = 5;
  var EXACT_CODE = /^TS\d+[A-Z]?$/;

  var cellSize = 0.05;
  var cellIndex = {};          // "x_y" -> sign count
  var cellSplits = {};         // "x_y" -> {n, parts} for cells stored in parts
  var cellCache = {};          // "x_y" -> array of [code, lon, lat, angle]
  var cellPending = {};        // "x_y" -> Promise
  var iconAvailable = null;    // Set of site codes ("TS_115") with SVGs
  var iconAspect = {};         // site code -> width/height ratio of its SVG
  var signLayer = L.layerGroup().addTo(map);
  var clusterLayer = L.layerGroup().addTo(map);
  var queryLayer = L.layerGroup().addTo(map);
  var pinLayer = L.layerGroup().addTo(map);
  var signMarkers = {};        // marker key -> Leaflet marker (diffed on render)
  var fatalStatus = false;     // once set, render() must not overwrite it
  var applying = false;        // true while the map moves itself
  var padding = { right: 0, bottom: 0 };

  // ---- search scope ---------------------------------------------------------
  // Two independent filters, both optional:
  //   area: {latitude, longitude, radius_km, place}   — signs within a circle
  //   code: {text, exact, source}                     — a drawing code
  // An exact code ("TS101") matches one drawing; anything shorter ("115") is a
  // substring match, as the plain code filter has always been. `source` says
  // who owns the code: 'box' while it is just what is typed in the search box,
  // 'chip' once it has been committed (a place was picked, a drawing chosen).

  var area = null;
  var code = null;
  var scopeToken = 0;          // drops counts that finish after a newer change

  function datasetCode(text) {
    // "TS 101", "ts_101", "TS-101A" -> "TS101A"; anything else unchanged.
    var compact = String(text || '').replace(/[\s_-]+/g, '').toUpperCase();
    return EXACT_CODE.test(compact) ? compact : null;
  }

  function codeMatcher() {
    if (!code) return null;
    if (code.exact) {
      var wanted = code.text;
      return function (c) { return c.toUpperCase() === wanted; };
    }
    var part = code.text.toLowerCase();
    return function (c) { return c.toLowerCase().indexOf(part) !== -1; };
  }

  function getScope() {
    return {
      area: area ? { latitude: area.latitude, longitude: area.longitude,
                     radius_km: area.radius_km, place: area.place } : null,
      code: code ? { text: code.text, exact: code.exact, source: code.source } : null
    };
  }

  function hasScope() { return !!(area || code); }

  function syncScopeButton() {
    clearScopeEl.hidden = !hasScope();
  }

  function emitScope(result, loading) {
    window.dispatchEvent(new CustomEvent('svgcad:scope-changed', {
      detail: { scope: getScope(), result: result || null, loading: !!loading }
    }));
  }

  // Everything that changes the scope ends here: redraw, update the URL,
  // announce the change, then count the area (if any) and announce again.
  function scopeChanged(opts) {
    opts = opts || {};
    var token = ++scopeToken;
    syncScopeButton();
    drawArea();
    if (!opts.fromHistory) writeUrl(opts.push !== false);
    window.dispatchEvent(new Event('svgcad:user-action'));
    clearSigns();
    refresh();
    if (!area) { emitScope(null, false); return; }
    emitScope(null, true);
    queryRadius({ latitude: area.latitude, longitude: area.longitude,
                  radius_km: area.radius_km, code: code })
      .then(function (result) {
        if (token === scopeToken) emitScope(result, false);
      });
  }

  function validArea(a) {
    return a && Number.isFinite(a.latitude) && Number.isFinite(a.longitude) &&
      a.latitude >= HK.south && a.latitude <= HK.north &&
      a.longitude >= HK.west && a.longitude <= HK.east &&
      Number.isFinite(a.radius_km) && a.radius_km >= 0.01 && a.radius_km <= MAX_RADIUS;
  }

  function cleanPlace(place) {
    if (!place || typeof place !== 'object') return null;
    var en = typeof place.name_en === 'string' ? place.name_en.slice(0, 160) : '';
    var zh = typeof place.name_zh_hant === 'string' ? place.name_zh_hant.slice(0, 160) : '';
    if (!en && !zh) return null;
    return { name_en: en || zh, name_zh_hant: zh || en,
             kind: typeof place.kind === 'string' ? place.kind : null,
             source: place.source && typeof place.source.url === 'string' ? { url: place.source.url } : null };
  }

  // Set or replace the search area. `fit` (default true) frames the circle.
  function setArea(next, opts) {
    opts = opts || {};
    if (!validArea(next)) return false;
    area = { latitude: next.latitude, longitude: next.longitude,
             radius_km: Math.round(next.radius_km * 1000) / 1000,
             place: cleanPlace(next.place) };
    clearChoicePins();
    if (opts.fit !== false) fitArea();
    scopeChanged(opts);
    return true;
  }

  function clearArea(opts) {
    if (!area) return false;
    area = null;
    clearChoicePins();
    scopeChanged(opts);
    return true;
  }

  function setRadius(km, opts) {
    if (!area) return false;
    return setArea(Object.assign({}, area, { radius_km: km }), Object.assign({ fit: false }, opts));
  }

  // text: null clears. Exact codes are normalised ("TS 101" -> "TS101").
  function setCode(text, opts) {
    opts = opts || {};
    var source = opts.source || 'chip';
    var raw = String(text == null ? '' : text).trim();
    if (!raw) {
      if (!code || (opts.onlySource && code.source !== opts.onlySource)) return false;
      code = null;
    } else {
      var exact = datasetCode(raw);
      var next = exact ? { text: exact, exact: true, source: source }
                       : { text: raw.toLowerCase().slice(0, 40), exact: false, source: source };
      if (code && code.text === next.text && code.exact === next.exact && code.source === next.source) return true;
      code = next;
    }
    scopeChanged(opts);
    return true;
  }

  function clearScope(opts) {
    if (!hasScope()) return;
    area = null;
    code = null;
    clearChoicePins();
    scopeChanged(opts);
    window.dispatchEvent(new Event('svgcad:scope-cleared'));
  }

  // Backwards-compatible entry point for the assistant: one call sets the
  // area and an exact code together.
  function applyQuery(action, opts) {
    if (!validArea(action)) return false;
    if (action.code && !EXACT_CODE.test(action.code)) return false;
    code = action.code ? { text: action.code, exact: true, source: 'chip' } : null;
    return setArea({ latitude: action.latitude, longitude: action.longitude,
                     radius_km: action.radius_km, place: action.place }, opts);
  }

  // ---- area drawing: circle + radius handle ---------------------------------

  var circle = null, handle = null;

  function edgePoint(lat, lon, km) {
    return [lat, lon + km / (111.32 * Math.cos(lat * Math.PI / 180))];
  }

  function niceRadius(km) {
    km = Math.max(MIN_RADIUS, Math.min(MAX_RADIUS, km));
    return km < 1 ? Math.round(km * 20) / 20 : Math.round(km * 10) / 10;
  }

  function formatKm(km) {
    return km < 1 ? Math.round(km * 1000) + ' m' : (Math.round(km * 10) / 10) + ' km';
  }

  function drawArea() {
    queryLayer.clearLayers();
    circle = handle = null;
    if (!area) return;
    circle = L.circle([area.latitude, area.longitude], {
      radius: area.radius_km * 1000, color: '#c1121f', weight: 2,
      fillColor: '#c1121f', fillOpacity: 0.07, interactive: false
    }).addTo(queryLayer);
    L.circleMarker([area.latitude, area.longitude], {
      radius: 5, color: '#ffffff', weight: 2, fillColor: '#c1121f', fillOpacity: 1, interactive: false
    }).addTo(queryLayer);
    handle = L.marker(edgePoint(area.latitude, area.longitude, area.radius_km), {
      draggable: true, keyboard: true, title: 'Drag to change the search radius',
      icon: L.divIcon({ className: 'radius-handle', iconSize: [18, 18], iconAnchor: [9, 9],
                        html: '<span></span>' })
    }).addTo(queryLayer);
    handle.bindTooltip(formatKm(area.radius_km), { permanent: true, direction: 'right',
                                                   offset: [10, 0], className: 'radius-tip' });
    handle.on('drag', function (e) {
      var km = niceRadius(map.distance([area.latitude, area.longitude], e.target.getLatLng()) / 1000);
      circle.setRadius(km * 1000);
      handle.setTooltipContent(formatKm(km));
    });
    handle.on('dragend', function (e) {
      var km = niceRadius(map.distance([area.latitude, area.longitude], e.target.getLatLng()) / 1000);
      setRadius(km);
    });
  }

  function fitArea() {
    if (!area) return;
    var b = L.latLng(area.latitude, area.longitude).toBounds(area.radius_km * 2000);
    applying = true;
    map.fitBounds(b, { paddingTopLeft: [24, 24],
                       paddingBottomRight: [24 + padding.right, 24 + padding.bottom],
                       maxZoom: 17, animate: false });
    applying = false;
  }

  // ---- choice pins (assistant asks "which place?") --------------------------

  function clearChoicePins() { pinLayer.clearLayers(); }

  function showChoicePins(choices, onPick) {
    clearChoicePins();
    var points = [];
    (choices || []).forEach(function (choice, i) {
      if (!Number.isFinite(choice.latitude) || !Number.isFinite(choice.longitude)) return;
      var marker = L.marker([choice.latitude, choice.longitude], {
        title: choice.label, keyboard: true,
        icon: L.divIcon({ className: 'choice-pin', iconSize: [28, 28], iconAnchor: [14, 28],
                          html: '<span>' + (i + 1) + '</span>' })
      }).addTo(pinLayer);
      marker.bindTooltip(choice.label, { direction: 'top', offset: [0, -26], className: 'sign-tip' });
      marker.on('click', function () { onPick(choice); });
      points.push([choice.latitude, choice.longitude]);
    });
    if (points.length) {
      applying = true;
      map.fitBounds(L.latLngBounds(points).pad(0.3), {
        paddingBottomRight: [padding.right, padding.bottom], maxZoom: 15, animate: false });
      applying = false;
    }
  }

  // ---- URL state --------------------------------------------------------------
  // ?lat=&lng=&r=&code=&place= next to the #zoom/lat/lng view hash. A new search
  // pushes a history entry so Back steps through searches.

  function writeUrl(push) {
    var params = new URLSearchParams(location.search);
    ['lat', 'lng', 'r', 'code', 'place'].forEach(function (k) { params.delete(k); });
    if (area) {
      // Full place precision, so a shared link reproduces the exact count.
      params.set('lat', String(Number(area.latitude.toFixed(7))));
      params.set('lng', String(Number(area.longitude.toFixed(7))));
      params.set('r', String(area.radius_km));
      if (area.place) params.set('place', area.place.name_en);
    }
    if (code && code.source === 'chip') params.set('code', code.text);
    var query = params.toString();
    var url = location.pathname + (query ? '?' + query : '') + location.hash;
    if (url === location.pathname + location.search + location.hash) return;
    if (push) history.pushState({ svgcad: true }, '', url);
    else history.replaceState({ svgcad: true }, '', url);
  }

  function readUrl(opts) {
    var params = new URLSearchParams(location.search);
    var lat = Number(params.get('lat')), lng = Number(params.get('lng')), r = Number(params.get('r'));
    var codeText = params.get('code');
    var nextArea = params.has('lat') && validArea({ latitude: lat, longitude: lng, radius_km: r })
      ? { latitude: lat, longitude: lng, radius_km: r,
          place: params.get('place') ? { name_en: params.get('place'), name_zh_hant: params.get('place') } : null }
      : null;
    code = codeText ? (datasetCode(codeText)
      ? { text: datasetCode(codeText), exact: true, source: 'chip' }
      : { text: codeText.toLowerCase().slice(0, 40), exact: false, source: 'chip' }) : null;
    if (nextArea) return setArea(nextArea, opts);
    area = null;
    scopeChanged(opts);
    return !!code;
  }

  window.addEventListener('popstate', function () {
    readUrl({ fromHistory: true });
  });

  // ---- data loading -------------------------------------------------------

  function fetchJson(path) {
    return fetch(path).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status + ' for ' + path);
      return r.json();
    });
  }

  // Without the cell index nothing can be drawn at all, so say so rather than
  // leaving an empty map with an empty status line.
  var indexReady = fetchJson('map-data/index.json')
    .then(function (idx) {
      cellSize = idx.cell;
      cellIndex = idx.cells;
      cellSplits = idx.splits || {};   // absent in indexes built before splitting
      refresh();
      return true;
    })
    .catch(function (err) {
      setFatalStatus('Could not load the sign index (' + err.message +
                     ') — reload to retry');
      return false;
    });

  // Cropped marker icons (built by scripts/build_map_icons.py) and their
  // width/height aspect ratios. Losing these is survivable: markers fall back
  // to plain dots, so it only warrants a console warning.
  var iconsReady = fetchJson('map-icons/index.json')
    .then(function (aspects) {
      iconAspect = aspects;
      iconAvailable = new Set(Object.keys(aspects));
      refresh();
    })
    .catch(function (err) {
      iconAvailable = new Set();   // unblock the icon tier's fallback to dots
      console.warn('Sign icons unavailable, falling back to dots:', err.message);
      refresh();
    });

  function fetchCell(key) {
    return fetch('map-data/' + key + '.json').then(function (r) {
      // Without this an error page reaches r.json(), which throws a much
      // less useful parse error.
      if (!r.ok) throw new Error('HTTP ' + r.status + ' for cell ' + key);
      return r.json();
    });
  }

  function loadCell(key) {
    if (cellCache[key]) return Promise.resolve(cellCache[key]);
    if (!cellPending[key]) {
      // One automatic retry absorbs a transient network blip; the dense,
      // larger files are the likeliest to fail.
      //
      // Either way the pending entry is dropped when it settles: caching a
      // rejected promise here would make every later loadCell() replay that
      // same failure, blacking the area out for the rest of the session even
      // after the network recovered.
      cellPending[key] = fetchCell(key)
        .catch(function () {
          return new Promise(function (resolve) {
            setTimeout(resolve, CELL_RETRY_MS);
          }).then(function () { return fetchCell(key); });
        })
        .then(function (rows) {
          cellCache[key] = rows;
          delete cellPending[key];
          return rows;
        }, function (err) {
          delete cellPending[key];
          throw err;
        });
    }
    return cellPending[key];
  }

  // Names of the files covering a lat/lng box. Usually one per cell, but a
  // cell dense enough to have been split (see scripts/build_map_data.py)
  // contributes only the parts the box actually touches — Kowloon's cell is
  // 26k signs, and pulling all of it to look at one junction is what used to
  // make that area so slow and failure-prone.
  function cellKeysForBounds(b) {
    var keys = [];
    var x0 = Math.floor(b.getWest() / cellSize), x1 = Math.floor(b.getEast() / cellSize);
    var y0 = Math.floor(b.getSouth() / cellSize), y1 = Math.floor(b.getNorth() / cellSize);
    for (var x = x0; x <= x1; x++) {
      for (var y = y0; y <= y1; y++) {
        var key = x + '_' + y;
        if (!cellIndex[key]) continue;
        var split = cellSplits[key];
        if (!split) { keys.push(key); continue; }

        // Same arithmetic as partition() in the build script.
        var sub = cellSize / split.n;
        var i0 = Math.max(0, Math.floor((b.getWest() - x * cellSize) / sub));
        var i1 = Math.min(split.n - 1, Math.floor((b.getEast() - x * cellSize) / sub));
        var j0 = Math.max(0, Math.floor((b.getSouth() - y * cellSize) / sub));
        var j1 = Math.min(split.n - 1, Math.floor((b.getNorth() - y * cellSize) / sub));
        for (var i = i0; i <= i1; i++) {
          for (var j = j0; j <= j1; j++) {
            var part = i + '-' + j;
            if (split.parts[part]) keys.push(key + '_' + part);
          }
        }
      }
    }
    return keys;
  }

  // Padded to match visibleRows(): a row in that margin is drawn, so its file
  // has to have been fetched.
  function visibleCellKeys() {
    return cellKeysForBounds(map.getBounds().pad(0.05));
  }

  function visibleRows() {
    var bounds = map.getBounds().pad(0.05);
    var match = codeMatcher();
    var rows = [];
    visibleCellKeys().forEach(function (key) {
      var cell = cellCache[key];
      if (!cell) return;
      for (var i = 0; i < cell.length; i++) {
        var r = cell[i];
        if (match && !match(r[0])) continue;
        if (area && distanceKm(area.latitude, area.longitude, r[2], r[1]) > area.radius_km) continue;
        if (bounds.contains([r[2], r[1]])) rows.push(r);
      }
    });
    return rows;
  }

  function distanceKm(aLat, aLon, bLat, bLon) {
    var p1 = aLat * Math.PI / 180, p2 = bLat * Math.PI / 180;
    var dp = p2 - p1, dl = (bLon - aLon) * Math.PI / 180;
    var h = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
    return 6371.0088 * 2 * Math.asin(Math.min(1, Math.sqrt(h)));
  }

  // Count every surveyed sign within a circle, not just the ones in view. The
  // same box-then-haversine method as MapData.query in src/svg2dxf/server/geo.py,
  // so the public map and the Docker backend report the same numbers.
  // q.code may be a scope code object ({text, exact}) or an exact code string.
  function queryRadius(q) {
    if (!validArea(q)) return Promise.reject(new Error('Invalid search area'));
    var c = typeof q.code === 'string' ? { text: datasetCode(q.code) || q.code, exact: !!datasetCode(q.code) } : q.code;
    var match = c ? (c.exact
      ? function (x) { return x.toUpperCase() === c.text; }
      : function (x) { return x.toLowerCase().indexOf(c.text.toLowerCase()) !== -1; }) : null;
    var latDelta = q.radius_km / 110.5;
    var lonDelta = q.radius_km / (111.3 * Math.cos(q.latitude * Math.PI / 180));
    var box = L.latLngBounds([q.latitude - latDelta, q.longitude - lonDelta],
                             [q.latitude + latDelta, q.longitude + lonDelta]);
    return indexReady.then(function () {
      var keys = cellKeysForBounds(box);
      var missing = [];
      return Promise.all(keys.map(function (key) {
        return loadCell(key).catch(function () { missing.push(key); return []; });
      })).then(function (cells) {
        var counts = {}, total = 0;
        cells.forEach(function (cell) {
          for (var i = 0; i < cell.length; i++) {
            var r = cell[i];
            if (r[2] < box.getSouth() || r[2] > box.getNorth() ||
                r[1] < box.getWest() || r[1] > box.getEast()) continue;
            if (match && !match(r[0])) continue;
            if (distanceKm(q.latitude, q.longitude, r[2], r[1]) > q.radius_km) continue;
            var k = r[0].toUpperCase();
            counts[k] = (counts[k] || 0) + 1;
            total++;
          }
        });
        return { matched_total: total, code_counts: counts,
                 data_complete: !missing.length, missing_cells: missing.sort() };
      });
    });
  }

  // ---- cluster bubbles (zoom < 15) ---------------------------------------

  function compactCount(n) {
    if (n < 1000) return String(n);
    var k = (n / 1000).toFixed(n < 10000 ? 1 : 0).replace(/\.0$/, '');
    return k + 'k';
  }

  function bubbleMarker(lat, lon, count) {
    var d = Math.round(Math.min(64, 24 + Math.sqrt(count) * 0.45));
    var marker = L.marker([lat, lon], {
      icon: L.divIcon({
        className: 'cluster-bubble-wrap',
        html: '<div class="cluster-bubble" style="width:' + d + 'px;height:' + d +
              'px;line-height:' + d + 'px">' + compactCount(count) + '</div>',
        iconSize: [d, d],
        iconAnchor: [d / 2, d / 2]
      }),
      keyboard: false
    });
    marker.on('click', function () {
      map.setView([lat, lon], Math.min(map.getZoom() + 2, 16));
    });
    return marker;
  }

  // Per drawing, how many signs each cell holds (site/map-codes.json, built by
  // scripts/build_site_indexes.py). Fetched only once an exact code is
  // filtered, so the low zooms can show that one drawing across Hong Kong.
  var codeCells = null, codeCellsPending = null;

  function codeCellsFor(c) {
    if (codeCells) return codeCells[c] || {};
    if (!codeCellsPending) {
      codeCellsPending = fetchJson('map-codes.json')
        .then(function (data) { codeCells = data; refresh(); })
        .catch(function (err) { console.warn('Per-drawing counts unavailable:', err.message); });
    }
    return null;
  }

  // Zoom 10-12: one bubble per data cell, from precomputed counts.
  function renderCellBubbles() {
    clusterLayer.clearLayers();
    var b = map.getBounds().pad(0.1);
    var perCode = code && code.exact ? codeCellsFor(code.text) : null;
    var counts = perCode || cellIndex;
    var total = 0;
    Object.keys(counts).forEach(function (key) {
      var xy = key.split('_');
      var lon = (Number(xy[0]) + 0.5) * cellSize;
      var lat = (Number(xy[1]) + 0.5) * cellSize;
      if (!b.contains([lat, lon])) return;
      total += counts[key];
      clusterLayer.addLayer(bubbleMarker(lat, lon, counts[key]));
    });
    if (perCode) {
      setStatus(total ? compactCount(total) + ' ' + siteCode(code.text) + ' signs in view'
                      : 'No ' + siteCode(code.text) + ' signs here');
      return;
    }
    setStatus(total
      ? compactCount(total) + ' signs in view' +
        (code ? ' — zoom in to apply the filter' : '')
      : '');
  }

  // Zoom 13-14: bin the real points into screen-pixel cells.
  function renderBinnedBubbles() {
    clusterLayer.clearLayers();
    var zoom = map.getZoom();
    var bins = {};   // "bx_by" -> {count, latSum, lonSum}
    var rows = visibleRows();
    rows.forEach(function (r) {
      var p = map.project([r[2], r[1]], zoom);
      var key = Math.floor(p.x / BIN_PX) + '_' + Math.floor(p.y / BIN_PX);
      var bin = bins[key] || (bins[key] = { count: 0, latSum: 0, lonSum: 0 });
      bin.count++;
      bin.latSum += r[2];
      bin.lonSum += r[1];
    });
    Object.keys(bins).forEach(function (key) {
      var bin = bins[key];
      clusterLayer.addLayer(
        bubbleMarker(bin.latSum / bin.count, bin.lonSum / bin.count, bin.count));
    });
    setStatus(rows.length
      ? compactCount(rows.length) + ' signs in view'
      : (code ? 'No signs match "' + siteCode(code.text) + '" here' : ''));
  }

  // ---- sign markers (zoom >= 15) ------------------------------------------

  function siteCode(c) {
    // dataset "TS115" -> site "TS_115"
    return c.toUpperCase().indexOf('TS') === 0 ? 'TS_' + c.slice(2).toUpperCase() : c;
  }

  function iconSize(zoom) {
    return zoom >= 19 ? 34 : zoom >= 18 ? 28 : 22;
  }

  function popupHtml(c, angle, lat, lon) {
    var sc = siteCode(c);
    var hasIcon = iconAvailable && iconAvailable.has(sc);
    var h = '<div class="sign-popup">';
    if (hasIcon) h += '<img src="map-icons/' + sc + '.svg" alt="' + c + '">';
    h += '<div class="code">' + c + '</div>';
    h += '<div class="meta">' + (angle != null
      ? 'Facing ' + angle + '&deg; <span class="dir" style="transform:rotate(' +
        angle + 'deg)">&#9650;</span>'
      : 'TPDM traffic sign') + '</div>';
    if (hasIcon) {
      h += '<div class="dl"><a href="svgs/' + sc + '.svg" download>SVG</a>' +
           '<a href="dxfs/' + sc + '.dxf" download>DXF</a></div>';
    }
    if (EXACT_CODE.test(c)) {
      h += '<div class="popup-actions">' +
           '<button type="button" data-popup-action="nearby" data-code="' + c +
           '" data-lat="' + lat + '" data-lng="' + lon + '">Signs like this nearby</button>' +
           (hasIcon ? '<a href="index.html?q=' + sc + '">Open in gallery</a>' : '') +
           '</div>';
    }
    h += '</div>';
    return h;
  }

  function makeMarker(r, useIcons, zoom) {
    var c = r[0], lon = r[1], lat = r[2], angle = r[3];
    var sc = siteCode(c);
    var marker;
    if (useIcons && iconAvailable && iconAvailable.has(sc)) {
      var size = iconSize(zoom);
      // Size the plate to the sign's real proportions (clamped so extreme
      // panels don't dominate); `size` is the height.
      var ar = Math.max(0.4, Math.min(2.5, iconAspect[sc] || 1));
      var w = Math.round(size * ar);
      var html = '<div class="sign-plate"><img src="map-icons/' + sc + '.svg" alt=""></div>';
      if (angle != null) {
        html += '<div class="tick-wrap" style="transform:rotate(' + angle +
                'deg)"><div class="sign-tick"></div></div>';
      }
      marker = L.marker([lat, lon], {
        icon: L.divIcon({
          className: 'sign-marker',
          html: html,
          iconSize: [w, size],
          iconAnchor: [w / 2, size / 2]
        })
      });
    } else {
      marker = L.circleMarker([lat, lon], {
        radius: useIcons ? 5 : zoom >= 16 ? 4.5 : 3,
        color: '#ffffff',
        weight: 1,
        fillColor: '#c1121f',
        fillOpacity: 0.9
      });
    }
    marker.bindPopup(popupHtml(c, angle, lat, lon));
    marker.bindTooltip(c, { direction: 'top', className: 'sign-tip' });
    return marker;
  }

  function renderSigns() {
    clusterLayer.clearLayers();
    var zoom = map.getZoom();
    var rows = visibleRows();
    var useIcons = zoom >= ICON_ZOOM && rows.length <= MAX_ICONS;

    // Diff against what's already on the map so panning doesn't flash:
    // only markers entering/leaving the view are touched. Keys encode the
    // render mode and size, so tier changes replace everything naturally.
    var mode = (useIcons ? 'i' + iconSize(zoom) : 'd' + (zoom >= 16 ? 1 : 0));
    var wanted = {};
    rows.forEach(function (r) {
      wanted[mode + '|' + r[0] + '|' + r[1] + '|' + r[2]] = r;
    });

    Object.keys(signMarkers).forEach(function (key) {
      if (!wanted[key]) {
        signLayer.removeLayer(signMarkers[key]);
        delete signMarkers[key];
      }
    });
    Object.keys(wanted).forEach(function (key) {
      if (!signMarkers[key]) {
        var marker = makeMarker(wanted[key], useIcons, zoom);
        signMarkers[key] = marker;
        signLayer.addLayer(marker);
      }
    });

    setStatus(rows.length
      ? rows.length.toLocaleString() + ' sign' + (rows.length === 1 ? '' : 's') + ' in view'
      : (code ? 'No signs match "' + siteCode(code.text) + '" here' : ''));
  }

  function clearSigns() {
    signLayer.clearLayers();
    signMarkers = {};
  }

  // ---- render dispatch -----------------------------------------------------

  function render() {
    var zoom = map.getZoom();
    if (area && zoom < DOT_ZOOM) {
      clearSigns();
      renderBinnedBubbles();
      return;
    }
    if (zoom < BIN_ZOOM) {
      clearSigns();
      renderCellBubbles();
    } else if (zoom < DOT_ZOOM) {
      clearSigns();
      renderBinnedBubbles();
    } else {
      renderSigns();
    }
  }

  function refresh() {
    if (map.getZoom() < BIN_ZOOM && !area) { render(); return; }
    var missing = visibleCellKeys().filter(function (k) { return !cellCache[k]; });
    if (!missing.length) { render(); return; }
    setStatus('Loading signs…');
    var failed = 0;
    Promise.all(missing.map(function (key) {
      // Swallow per cell so one failure can't reject the whole batch and
      // leave the map stuck on "Loading signs…" with nothing drawn.
      return loadCell(key).catch(function () { failed++; });
    })).then(function () {
      render();   // draws whatever did arrive
      if (failed) setStatus('Some signs could not be loaded — pan or zoom to retry');
    });
  }

  // A fatal message latches: without the cell index every later render()
  // reports "0 signs in view" and would otherwise wipe the explanation.
  function setStatus(text) {
    if (!fatalStatus) statusEl.textContent = text;
  }

  function setFatalStatus(text) {
    statusEl.textContent = text;
    fatalStatus = true;
  }

  // ---- events -------------------------------------------------------------

  map.on('moveend zoomend', function () {
    var c = map.getCenter();
    // Fragment-only URL keeps the ?search params; keep the history state too.
    history.replaceState(history.state, '',
      '#' + map.getZoom() + '/' + c.lat.toFixed(5) + '/' + c.lng.toFixed(5));
    refresh();
  });

  map.on('movestart', function () {
    if (!applying) window.dispatchEvent(new Event('svgcad:user-action'));
  });

  clearScopeEl.addEventListener('click', function () { clearScope(); });

  // Right-click (long-press on touch) offers a search around that point.
  map.on('contextmenu', function (e) {
    var menu = L.DomUtil.create('div', 'map-context');
    var btn = L.DomUtil.create('button', '', menu);
    btn.type = 'button';
    btn.textContent = 'Search around here';
    var popup = L.popup({ className: 'map-context-popup', closeButton: false, offset: [0, -4] })
      .setLatLng(e.latlng).setContent(menu).openOn(map);
    L.DomEvent.on(btn, 'click', function () {
      map.closePopup(popup);
      setArea({ latitude: e.latlng.lat, longitude: e.latlng.lng,
                radius_km: area ? area.radius_km : 0.5,
                place: { name_en: 'Selected point', name_zh_hant: '已選位置', kind: 'map_point' } });
    });
    setTimeout(function () { btn.focus(); }, 0);
  });

  // Popup buttons are plain HTML strings, so handle them by delegation.
  map.getContainer().addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('[data-popup-action="nearby"]');
    if (!btn) return;
    var lat = Number(btn.dataset.lat), lng = Number(btn.dataset.lng);
    map.closePopup();
    code = { text: btn.dataset.code, exact: true, source: 'chip' };
    setArea({ latitude: lat, longitude: lng, radius_km: 0.5,
              place: { name_en: 'Near ' + siteCode(btn.dataset.code),
                       name_zh_hant: siteCode(btn.dataset.code) + ' 附近', kind: 'map_point' } });
  });

  // Debug/console handle (also lets tests drive the map).
  window._signsMap = map;

  window.svgCadMap = {
    map: map,
    ready: function () { return indexReady; },
    iconsReady: function () { return iconsReady; },
    currentPoint: function () {
      var c = area ? L.latLng(area.latitude, area.longitude) : map.getCenter();
      return { latitude: c.lat, longitude: c.lng, source: area ? 'selected' : 'center' };
    },
    getScope: getScope,
    setArea: setArea,
    setRadius: setRadius,
    clearArea: clearArea,
    setCode: setCode,
    clearScope: clearScope,
    clearCodeFilter: function () { setCode(null, { onlySource: 'box' }); },
    applyQuery: applyQuery,
    queryRadius: queryRadius,
    showChoicePins: showChoicePins,
    clearChoicePins: clearChoicePins,
    datasetCode: datasetCode,
    siteCode: siteCode,
    hasIcon: function (c) { return !!(iconAvailable && iconAvailable.has(siteCode(c))); },
    formatKm: formatKm,
    setPadding: function (p) {
      padding = { right: Math.max(0, p.right || 0), bottom: Math.max(0, p.bottom || 0) };
    },
    fitArea: fitArea,
    invalidateSize: function () { map.invalidateSize({ pan: false }); }
  };

  // A shared link restores its search; keep the hash view if it has one.
  indexReady.then(function () {
    if (/[?&](lat|code)=/.test(location.search)) {
      readUrl({ push: false, fit: !/^#\d/.test(location.hash) });
    }
  });
})();
