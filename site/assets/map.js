/* Traffic signs map.
 * Sign locations come from the Transport Department's Digitized Traffic Aids
 * Drawings dataset (Traffic Sign Abbreviation points), pre-processed into
 * per-cell JSON by scripts/build_map_data.py.
 *
 * Zoom tiers: 10-12 cluster bubbles from per-cell counts (no data fetch),
 * 13-14 cluster bubbles binned from real points, 15-16 dots, 17+ sign SVGs.
 */
(function () {
  'use strict';

  var DOT_ZOOM = 15;        // below this, cluster bubbles
  var BIN_ZOOM = 13;        // from this zoom, clusters are binned real points
  var ICON_ZOOM = 17;       // at/above this, draw SVG icons instead of dots
  var MAX_ICONS = 600;      // icon markers are DOM nodes — cap them
  var BIN_PX = 96;          // screen-pixel bin size for zoom 13-14 clusters

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
    'Dark': cartoLayer('dark_nolabels'),
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

  map.attributionControl.addAttribution('Signs: <a href="https://data.gov.hk/en-data/dataset/hk-td-tis_16-traffic-aids-drawings-v2">Transport Department</a>');

  // The dark-mode CSS dims light basemaps; flag the true dark one so it
  // isn't double-darkened.
  map.on('baselayerchange', function (e) {
    document.getElementById('map').classList.toggle('dark-basemap', e.layer === baseLayers['Dark']);
  });

  var statusEl = document.getElementById('status');
  var filterEl = document.getElementById('filter');

  var cellSize = 0.05;
  var cellIndex = {};          // "x_y" -> sign count
  var cellCache = {};          // "x_y" -> array of [code, lon, lat, angle]
  var cellPending = {};        // "x_y" -> Promise
  var iconAvailable = null;    // Set of site codes ("TS_115") with SVGs
  var iconAspect = {};         // site code -> width/height ratio of its SVG
  var signLayer = L.layerGroup().addTo(map);
  var clusterLayer = L.layerGroup().addTo(map);
  var signMarkers = {};        // marker key -> Leaflet marker (diffed on render)
  var filterText = '';

  // ---- data loading -------------------------------------------------------

  fetch('map-data/index.json')
    .then(function (r) { return r.json(); })
    .then(function (idx) {
      cellSize = idx.cell;
      cellIndex = idx.cells;
      refresh();
    });

  // Cropped marker icons (built by scripts/build_map_icons.py) and their
  // width/height aspect ratios.
  fetch('map-icons/index.json')
    .then(function (r) { return r.json(); })
    .then(function (aspects) {
      iconAspect = aspects;
      iconAvailable = new Set(Object.keys(aspects));
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

  function visibleRows() {
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
    return rows;
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

  // Zoom 10-12: one bubble per data cell, from precomputed counts.
  function renderCellBubbles() {
    clusterLayer.clearLayers();
    var b = map.getBounds().pad(0.1);
    var total = 0;
    Object.keys(cellIndex).forEach(function (key) {
      var xy = key.split('_');
      var lon = (Number(xy[0]) + 0.5) * cellSize;
      var lat = (Number(xy[1]) + 0.5) * cellSize;
      if (!b.contains([lat, lon])) return;
      total += cellIndex[key];
      clusterLayer.addLayer(bubbleMarker(lat, lon, cellIndex[key]));
    });
    setStatus(total
      ? compactCount(total) + ' signs in view' +
        (filterText ? ' — zoom in to apply the filter' : '')
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
      : (filterText ? 'No signs match "' + filterText + '" here' : ''));
  }

  // ---- sign markers (zoom >= 15) ------------------------------------------

  function siteCode(code) {
    // dataset "TS115" -> site "TS_115"
    return code.indexOf('TS') === 0 ? 'TS_' + code.slice(2) : code;
  }

  function iconSize(zoom) {
    return zoom >= 19 ? 34 : zoom >= 18 ? 28 : 22;
  }

  function popupHtml(code, angle) {
    var sc = siteCode(code);
    var hasIcon = iconAvailable && iconAvailable.has(sc);
    var h = '<div class="sign-popup">';
    if (hasIcon) h += '<img src="map-icons/' + sc + '.svg" alt="' + code + '">';
    h += '<div class="code">' + code + '</div>';
    h += '<div class="meta">' + (angle != null
      ? 'Facing ' + angle + '&deg; <span class="dir" style="transform:rotate(' +
        angle + 'deg)">&#9650;</span>'
      : 'TPDM traffic sign') + '</div>';
    if (hasIcon) {
      h += '<div class="dl"><a href="svgs/' + sc + '.svg" download>SVG</a>' +
           '<a href="dxfs/' + sc + '.dxf" download>DXF</a></div>';
    }
    h += '</div>';
    return h;
  }

  function makeMarker(r, useIcons, zoom) {
    var code = r[0], lon = r[1], lat = r[2], angle = r[3];
    var sc = siteCode(code);
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
    marker.bindPopup(popupHtml(code, angle));
    marker.bindTooltip(code, { direction: 'top', className: 'sign-tip' });
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
      : (filterText ? 'No signs match "' + filterText + '" here' : ''));
  }

  function clearSigns() {
    signLayer.clearLayers();
    signMarkers = {};
  }

  // ---- render dispatch -----------------------------------------------------

  function render() {
    var zoom = map.getZoom();
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
    if (map.getZoom() < BIN_ZOOM) { render(); return; }
    var missing = visibleCellKeys().filter(function (k) { return !cellCache[k]; });
    if (!missing.length) { render(); return; }
    setStatus('Loading signs…');
    Promise.all(missing.map(loadCell)).then(render);
  }

  function setStatus(text) { statusEl.textContent = text; }

  // ---- events -------------------------------------------------------------

  map.on('moveend zoomend', function () {
    var c = map.getCenter();
    history.replaceState(null, '',
      '#' + map.getZoom() + '/' + c.lat.toFixed(5) + '/' + c.lng.toFixed(5));
    refresh();
  });

  // Debug/console handle (also lets tests drive the map).
  window._signsMap = map;

  var filterTimer;
  filterEl.addEventListener('input', function () {
    clearTimeout(filterTimer);
    filterTimer = setTimeout(function () {
      filterText = filterEl.value.trim().toLowerCase();
      clearSigns();   // filter changes what a key means — rebuild
      refresh();
    }, 150);
  });
})();
