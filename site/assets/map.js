/* Traffic signs map.
 * Sign locations come from the Transport Department's Digitized Traffic Aids
 * Drawings dataset (Traffic Sign Abbreviation points), pre-processed into
 * per-cell JSON by scripts/build_map_data.py.
 */
(function () {
  'use strict';

  var MIN_SIGN_ZOOM = 15;   // below this, signs are hidden (too many)
  var ICON_ZOOM = 17;       // at/above this, draw SVG icons instead of dots
  var MAX_ICONS = 600;      // icon markers are DOM nodes — cap them
  var ICON_SIZE = 26;

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

  L.tileLayer('https://mapapi.geodata.gov.hk/gs/api/v1.0.0/xyz/basemap/wgs84/{z}/{x}/{y}.png', {
    maxZoom: 20,
    attribution: '&copy; <a href="https://portal.csdi.gov.hk/">Lands Department</a> | Signs: <a href="https://data.gov.hk/en-data/dataset/hk-td-tis_16-traffic-aids-drawings-v2">Transport Department</a>'
  }).addTo(map);

  L.tileLayer('https://mapapi.geodata.gov.hk/gs/api/v1.0.0/xyz/label/hk/en/wgs84/{z}/{x}/{y}.png', {
    maxZoom: 20
  }).addTo(map);

  var statusEl = document.getElementById('status');
  var filterEl = document.getElementById('filter');

  var cellSize = 0.05;
  var cellIndex = {};          // "x_y" -> sign count
  var cellCache = {};          // "x_y" -> array of [code, lon, lat, angle]
  var cellPending = {};        // "x_y" -> Promise
  var iconAvailable = null;    // Set of site codes ("TS_115") with SVGs
  var signLayer = L.layerGroup().addTo(map);
  var filterText = '';

  // ---- data loading -------------------------------------------------------

  fetch('map-data/index.json')
    .then(function (r) { return r.json(); })
    .then(function (idx) {
      cellSize = idx.cell;
      cellIndex = idx.cells;
      refresh();
    });

  fetch('index.json')
    .then(function (r) { return r.json(); })
    .then(function (items) {
      iconAvailable = new Set(items.map(function (it) { return it.code; }));
      refresh();
    });

  function loadCell(key) {
    if (cellCache[key]) return Promise.resolve(cellCache[key]);
    if (!cellPending[key]) {
      cellPending[key] = fetch('map-data/' + key + '.json')
        .then(function (r) { return r.json(); })
        .then(function (rows) {
          cellCache[key] = rows;
          delete cellPending[key];
          return rows;
        });
    }
    return cellPending[key];
  }

  function visibleCellKeys() {
    var b = map.getBounds();
    var keys = [];
    var x0 = Math.floor(b.getWest() / cellSize), x1 = Math.floor(b.getEast() / cellSize);
    var y0 = Math.floor(b.getSouth() / cellSize), y1 = Math.floor(b.getNorth() / cellSize);
    for (var x = x0; x <= x1; x++) {
      for (var y = y0; y <= y1; y++) {
        var key = x + '_' + y;
        if (cellIndex[key]) keys.push(key);
      }
    }
    return keys;
  }

  // ---- rendering ----------------------------------------------------------

  function siteCode(code) {
    // dataset "TS115" -> site "TS_115"
    return code.indexOf('TS') === 0 ? 'TS_' + code.slice(2) : code;
  }

  function popupHtml(code, angle) {
    var sc = siteCode(code);
    var hasIcon = iconAvailable && iconAvailable.has(sc);
    var h = '<div class="sign-popup">';
    if (hasIcon) h += '<img src="svgs/' + sc + '.svg" alt="' + code + '">';
    h += '<div class="code">' + code + '</div>';
    h += '<div class="meta">' + (angle != null ? 'Facing ' + angle + '&deg;' : 'TPDM traffic sign') + '</div>';
    if (hasIcon) {
      h += '<div class="dl"><a href="svgs/' + sc + '.svg" download>SVG</a>' +
           '<a href="dxfs/' + sc + '.dxf" download>DXF</a></div>';
    }
    h += '</div>';
    return h;
  }

  function render() {
    signLayer.clearLayers();
    var zoom = map.getZoom();
    hint.update();
    if (zoom < MIN_SIGN_ZOOM) { setStatus(''); return; }

    var bounds = map.getBounds().pad(0.05);
    var rows = [];
    visibleCellKeys().forEach(function (key) {
      var cell = cellCache[key];
      if (!cell) return;
      for (var i = 0; i < cell.length; i++) {
        var r = cell[i];
        if (filterText && r[0].toLowerCase().indexOf(filterText) === -1) continue;
        if (bounds.contains([r[2], r[1]])) rows.push(r);
      }
    });

    var useIcons = zoom >= ICON_ZOOM && rows.length <= MAX_ICONS;
    rows.forEach(function (r) {
      var code = r[0], lon = r[1], lat = r[2], angle = r[3];
      var marker;
      var sc = siteCode(code);
      if (useIcons && iconAvailable && iconAvailable.has(sc)) {
        marker = L.marker([lat, lon], {
          icon: L.divIcon({
            className: 'sign-marker',
            html: '<img src="svgs/' + sc + '.svg" alt="">',
            iconSize: [ICON_SIZE, ICON_SIZE],
            iconAnchor: [ICON_SIZE / 2, ICON_SIZE / 2]
          })
        });
      } else {
        marker = L.circleMarker([lat, lon], {
          radius: useIcons ? 5 : 3.5,
          color: '#ffffff',
          weight: 1,
          fillColor: '#c1121f',
          fillOpacity: 0.9
        });
      }
      marker.bindPopup(popupHtml(code, angle));
      signLayer.addLayer(marker);
    });

    setStatus(rows.length
      ? rows.length.toLocaleString() + ' sign' + (rows.length === 1 ? '' : 's') + ' in view'
      : (filterText ? 'No signs match "' + filterText + '" here' : ''));
  }

  function refresh() {
    if (map.getZoom() < MIN_SIGN_ZOOM) { render(); return; }
    var keys = visibleCellKeys();
    var missing = keys.filter(function (k) { return !cellCache[k]; });
    if (!missing.length) { render(); return; }
    setStatus('Loading signs…');
    Promise.all(missing.map(loadCell)).then(render);
  }

  function setStatus(text) { statusEl.textContent = text; }

  // ---- zoom hint control --------------------------------------------------

  var HintControl = L.Control.extend({
    onAdd: function () {
      this._div = L.DomUtil.create('div', 'zoom-hint');
      this.update();
      return this._div;
    },
    update: function () {
      if (!this._div) return;
      this._div.style.display = map.getZoom() < MIN_SIGN_ZOOM ? '' : 'none';
      this._div.textContent = 'Zoom in to see traffic signs';
    }
  });
  var hint = new HintControl({ position: 'topright' });
  hint.addTo(map);

  // ---- events -------------------------------------------------------------

  map.on('moveend zoomend', function () {
    var c = map.getCenter();
    history.replaceState(null, '',
      '#' + map.getZoom() + '/' + c.lat.toFixed(5) + '/' + c.lng.toFixed(5));
    refresh();
  });

  var filterTimer;
  filterEl.addEventListener('input', function () {
    clearTimeout(filterTimer);
    filterTimer = setTimeout(function () {
      filterText = filterEl.value.trim().toLowerCase();
      render();
    }, 150);
  });
})();
