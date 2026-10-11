/* Results panel and filter chips for the map.
 *
 * Desktop: a panel docked beside the map (the map narrows to make room).
 * Narrow screens: a bottom sheet over the map that snaps to peek / half /
 * full. Both render whatever map.js reports through `svgcad:scope-changed`.
 * The Docker assistant mounts its own sections with svgCadPanel.mount().
 */
(function () {
  'use strict';

  if (!window.svgCadMap) return;
  var mapApi = window.svgCadMap;
  var panel = document.getElementById('map-panel');
  var chips = document.getElementById('scope-chips');
  var body = document.querySelector('.map-body');
  if (!panel || !chips || !body) return;

  var RADII = [0.25, 0.5, 1, 2, 5];
  var BREAKDOWN_ROWS = 12;
  var narrow = window.matchMedia('(max-width: 720px)');
  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function button(text, cls, onClick) {
    var b = el('button', cls, text);
    b.type = 'button';
    if (onClick) b.addEventListener('click', onClick);
    return b;
  }

  // ---- skeleton ----------------------------------------------------------------

  var grip = el('div', 'map-panel-grip');
  grip.setAttribute('aria-hidden', 'true');
  var head = el('div', 'map-panel-head');
  var title = el('h2', 'map-panel-title', 'Search results');
  title.id = 'map-panel-title';
  var tools = el('div', 'map-panel-tools');
  var closeBtn = button('', 'map-panel-close', function () { close(true); });
  closeBtn.setAttribute('aria-label', 'Close panel');
  closeBtn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>';
  head.appendChild(title);
  head.appendChild(tools);
  head.appendChild(closeBtn);
  var scroller = el('div', 'map-panel-body');
  var slotTop = el('div', 'map-panel-slot');
  var results = el('section', 'panel-results');
  results.setAttribute('aria-live', 'polite');
  scroller.appendChild(slotTop);
  scroller.appendChild(results);
  var slotBottom = el('div', 'map-panel-footer');
  panel.appendChild(grip);
  panel.appendChild(head);
  panel.appendChild(scroller);
  panel.appendChild(slotBottom);
  panel.setAttribute('aria-labelledby', 'map-panel-title');

  var reopen = button('Results', 'map-panel-reopen', function () { open(); });
  reopen.hidden = true;
  body.appendChild(reopen);

  var mounted = false;       // the assistant keeps the panel useful without results
  var isOpen = false;
  var userClosed = false;
  var lastAreaKey = null;
  var lastDetail = null;
  var showAllRows = false;

  // ---- open / close / layout ----------------------------------------------------

  var sheet = 'half';        // narrow screens only

  function sheetHeights() {
    var h = body.clientHeight;
    return { peek: Math.min(112, h * 0.3), half: Math.round(h * 0.48), full: h - 8, total: h };
  }

  function applySheet(state, animate) {
    if (!narrow.matches) { panel.style.transform = ''; panel.style.height = ''; return; }
    sheet = state;
    var hs = sheetHeights();
    panel.style.height = hs.full + 'px';
    panel.classList.toggle('is-animating', !!animate && !reduceMotion.matches);
    panel.style.transform = 'translateY(' + (hs.full - hs[state]) + 'px)';
    panel.dataset.sheet = state;
    mapApi.setPadding({ right: 0, bottom: hs[state] });
  }

  function layout(refit) {
    if (narrow.matches) {
      applySheet(sheet, false);
    } else {
      panel.style.transform = '';
      panel.style.height = '';
      mapApi.setPadding({ right: 0, bottom: 0 });
    }
    mapApi.invalidateSize();
    if (refit && mapApi.getScope().area) mapApi.fitArea();
  }

  function syncReopen() {
    var hasContent = mounted || !!mapApi.getScope().area;
    reopen.hidden = isOpen || !hasContent;
  }

  function open(opts) {
    opts = opts || {};
    userClosed = false;
    if (!isOpen) {
      isOpen = true;
      panel.hidden = false;
      document.body.classList.add('has-map-panel');
      if (narrow.matches) sheet = opts.sheet || 'half';
      layout(opts.fit !== false);
    } else if (opts.sheet && narrow.matches) {
      applySheet(opts.sheet, true);
    }
    syncReopen();
  }

  function close(byUser) {
    if (!isOpen) return;
    isOpen = false;
    if (byUser) userClosed = true;
    panel.hidden = true;
    document.body.classList.remove('has-map-panel');
    layout(false);
    syncReopen();
  }

  window.addEventListener('resize', function () { if (isOpen) layout(false); });
  narrow.addEventListener('change', function () { if (isOpen) layout(true); });

  // Sheet dragging: the grip and header move the sheet; release snaps it.
  (function () {
    var startY = 0, startOffset = 0, dragging = false, lastY = 0, lastT = 0, velocity = 0, onGrip = false;
    function offsetNow() {
      var m = /translateY\(([-\d.]+)px\)/.exec(panel.style.transform);
      return m ? Number(m[1]) : 0;
    }
    function down(e) {
      if (!narrow.matches || e.target.closest('button, a, select, details, input, textarea')) return;
      dragging = true;
      onGrip = e.currentTarget === grip;
      startY = lastY = e.clientY;
      velocity = 0;
      lastT = performance.now();
      startOffset = offsetNow();
      panel.classList.remove('is-animating');
      e.currentTarget.setPointerCapture(e.pointerId);
    }
    function move(e) {
      if (!dragging) return;
      var hs = sheetHeights();
      var offset = Math.max(0, Math.min(hs.full - hs.peek, startOffset + e.clientY - startY));
      panel.style.transform = 'translateY(' + offset + 'px)';
      var now = performance.now();
      velocity = (e.clientY - lastY) / Math.max(1, now - lastT);
      lastY = e.clientY;
      lastT = now;
    }
    function up() {
      if (!dragging) return;
      dragging = false;
      // A tap on the grip toggles between half and full instead of dragging.
      if (Math.abs(lastY - startY) < 5) {
        applySheet(onGrip ? (sheet === 'full' ? 'half' : 'full') : sheet, true);
        return;
      }
      var hs = sheetHeights();
      var visible = hs.full - offsetNow();
      var states = ['peek', 'half', 'full'];
      var target = states.reduce(function (best, s) {
        return Math.abs(hs[s] - visible) < Math.abs(hs[best] - visible) ? s : best;
      }, 'half');
      if (velocity > 0.6) target = states[Math.max(0, states.indexOf(target) - 1)];
      else if (velocity < -0.6) target = states[Math.min(2, states.indexOf(target) + 1)];
      applySheet(target, true);
    }
    [grip, head].forEach(function (node) {
      node.addEventListener('pointerdown', down);
      node.addEventListener('pointermove', move);
      node.addEventListener('pointerup', up);
      node.addEventListener('pointercancel', up);
    });
  })();

  // ---- chips ------------------------------------------------------------------------

  function placeName(place) {
    return place ? (place.name_en || place.name_zh_hant) : 'Selected point';
  }

  function codeLabel(c) {
    return c.exact ? mapApi.siteCode(c.text) : '“' + c.text + '”';
  }

  function radiusMenu(current, cls) {
    var group = el('div', cls);
    group.setAttribute('role', 'group');
    group.setAttribute('aria-label', 'Search radius');
    RADII.forEach(function (km) {
      var b = button(mapApi.formatKm(km), '', function () { mapApi.setRadius(km, { fit: true }); });
      b.setAttribute('aria-pressed', Math.abs(km - current) < 1e-9 ? 'true' : 'false');
      group.appendChild(b);
    });
    if (RADII.every(function (km) { return Math.abs(km - current) > 1e-9; })) {
      var custom = button(mapApi.formatKm(current), 'is-custom');
      custom.setAttribute('aria-pressed', 'true');
      custom.disabled = true;
      group.appendChild(custom);
    }
    return group;
  }

  function chip(label, removeLabel, onRemove, cls) {
    var c = el('span', 'chip' + (cls ? ' ' + cls : ''));
    c.appendChild(el('span', 'chip-label', label));
    if (onRemove) {
      var x = button('', 'chip-remove', onRemove);
      x.setAttribute('aria-label', removeLabel);
      x.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 7l10 10M17 7 7 17"/></svg>';
      c.appendChild(x);
    }
    return c;
  }

  function renderChips(detail) {
    chips.textContent = '';
    var scope = detail.scope;
    if (scope.area) {
      var name = placeName(scope.area.place);
      chips.appendChild(chip(name, 'Remove place ' + name, function () { mapApi.clearArea(); }, 'chip-place'));
      var radius = el('details', 'chip chip-radius');
      var summary = el('summary', '', mapApi.formatKm(scope.area.radius_km));
      summary.setAttribute('aria-label', 'Search radius ' + mapApi.formatKm(scope.area.radius_km) + ', change');
      radius.appendChild(summary);
      radius.appendChild(radiusMenu(scope.area.radius_km, 'chip-menu'));
      chips.appendChild(radius);
    }
    if (scope.code && scope.code.source === 'chip') {
      var label = codeLabel(scope.code);
      chips.appendChild(chip(label, 'Remove drawing filter ' + label,
                             function () { mapApi.setCode(null); }, 'chip-code'));
    }
    if (scope.area) {
      chips.appendChild(el('span', 'chip chip-count', detail.loading || !detail.result ? 'Counting…'
        : detail.result.matched_total.toLocaleString() + ' sign' + (detail.result.matched_total === 1 ? '' : 's')));
    }
    chips.hidden = !chips.children.length;
  }

  document.addEventListener('pointerdown', function (e) {
    chips.querySelectorAll('details[open]').forEach(function (d) {
      if (!d.contains(e.target)) d.open = false;
    });
  });

  // ---- results ---------------------------------------------------------------------

  function sourceLink(text, href) {
    var a = el('a', '', text);
    a.href = href;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    return a;
  }

  function placeSource(place) {
    var url = place && place.source && place.source.url;
    if (!url) return null;
    if (/^https:\/\/www\.map\.gov\.hk\/gs\/api\//.test(url)) return sourceLink('Lands Department', url);
    if (/^https:\/\/www\.had\.gov\.hk\//.test(url)) return sourceLink('Home Affairs Department', url);
    return null;
  }

  function drawingRow(code, count, filtered) {
    var sc = mapApi.siteCode(code);
    var entry = window.svgCadSearch && window.svgCadSearch.signName(code);
    var hasDrawing = mapApi.hasIcon(code);
    var li = el('li', 'drawing-row');
    var thumb = el('span', 'drawing-thumb');
    if (hasDrawing) {
      var img = el('img');
      img.src = 'map-icons/' + sc + '.svg';
      img.alt = '';
      img.loading = 'lazy';
      thumb.appendChild(img);
    }
    li.appendChild(thumb);
    var text = el('span', 'drawing-text');
    text.appendChild(el('strong', '', entry ? entry.name_en : sc));
    text.appendChild(el('span', '', entry ? sc + ' · ' + entry.name_zh_hant : (hasDrawing ? 'Drawing available' : 'No drawing available')));
    li.appendChild(text);
    li.appendChild(el('span', 'drawing-count', count.toLocaleString()));
    var actions = el('span', 'drawing-actions');
    if (!filtered) {
      var f = button('Show only', 'drawing-filter', function () { mapApi.setCode(code); });
      f.setAttribute('aria-label', 'Show only ' + sc);
      actions.appendChild(f);
    }
    if (hasDrawing) {
      [['SVG', 'svgs/' + sc + '.svg'], ['DXF', 'dxfs/' + sc + '.dxf']].forEach(function (pair) {
        var a = el('a', 'drawing-download', pair[0]);
        a.href = pair[1];
        a.setAttribute('download', '');
        a.setAttribute('aria-label', 'Download ' + sc + ' ' + pair[0]);
        actions.appendChild(a);
      });
    }
    li.appendChild(actions);
    return li;
  }

  function renderResults(detail) {
    results.textContent = '';
    var scope = detail.scope, area = scope.area;
    if (!area) return;
    var intro = el('header', 'result-head');
    intro.appendChild(el('p', 'result-kicker', 'Search area'));
    intro.appendChild(el('h3', 'result-place', placeName(area.place)));
    var sub = [];
    if (area.place && area.place.name_zh_hant && area.place.name_zh_hant !== area.place.name_en) sub.push(area.place.name_zh_hant);
    if (area.place && area.place.kind === 'district_center') sub.push('District centre point, not a boundary');
    else if (!area.place || area.place.kind === 'map_point') sub.push(area.latitude.toFixed(5) + ', ' + area.longitude.toFixed(5));
    if (sub.length) intro.appendChild(el('p', 'result-sub', sub.join(' · ')));
    var share = button('Copy link', 'result-share', function () {
      var done = function () { share.textContent = 'Link copied'; setTimeout(function () { share.textContent = 'Copy link'; }, 1600); };
      if (navigator.clipboard) navigator.clipboard.writeText(location.href).then(done, function () {});
    });
    intro.appendChild(share);
    results.appendChild(intro);

    results.appendChild(radiusMenu(area.radius_km, 'radius-picker'));

    var count = el('div', 'result-count');
    var result = detail.result;
    count.appendChild(el('strong', '', detail.loading || !result ? '…' : result.matched_total.toLocaleString()));
    count.appendChild(el('span', '', 'surveyed sign' + (result && result.matched_total === 1 ? '' : 's') +
      ' within ' + mapApi.formatKm(area.radius_km)));
    results.appendChild(count);

    if (scope.code) {
      var only = el('p', 'result-filter');
      only.appendChild(document.createTextNode((scope.code.exact ? 'Only ' : 'Codes containing ') + codeLabel(scope.code) + ' · '));
      only.appendChild(button('Show all drawings', 'link-button', function () { mapApi.setCode(null); }));
      results.appendChild(only);
    }

    if (detail.loading || !result) {
      results.appendChild(el('p', 'result-loading', 'Counting surveyed signs…'));
      return;
    }
    if (!result.data_complete) {
      results.appendChild(el('p', 'result-warning',
        'Some map data could not be loaded, so this count may be low. Change the radius to retry.'));
    }

    var codes = Object.keys(result.code_counts).sort(function (a, b) {
      return result.code_counts[b] - result.code_counts[a] || (a < b ? -1 : 1);
    });
    if (codes.length) {
      var breakdown = el('div', 'result-breakdown');
      var h = el('h4', '', 'By drawing ');
      h.appendChild(el('span', '', '(' + codes.length.toLocaleString() + ')'));
      breakdown.appendChild(h);
      var ul = el('ul', 'drawing-list');
      var filtered = !!(scope.code && scope.code.exact);
      codes.slice(0, showAllRows ? codes.length : BREAKDOWN_ROWS).forEach(function (c) {
        ul.appendChild(drawingRow(c, result.code_counts[c], filtered));
      });
      breakdown.appendChild(ul);
      if (codes.length > BREAKDOWN_ROWS) {
        breakdown.appendChild(button(showAllRows ? 'Show fewer' : 'Show all ' + codes.length.toLocaleString(),
          'show-more', function () { showAllRows = !showAllRows; renderResults(lastDetail); }));
      }
      results.appendChild(breakdown);
    } else {
      results.appendChild(el('p', 'result-empty', 'No surveyed signs in this area. Try a larger radius.'));
    }

    var notes = el('details', 'result-notes');
    notes.appendChild(el('summary', '', 'About these numbers'));
    notes.appendChild(el('p', '', 'Counts are surveyed records, not necessarily unique physical signs. ' +
      'Road-marking locations are not in the survey data.'));
    var src = el('p', '', 'Sources: ');
    src.appendChild(sourceLink('Transport Department survey',
      'https://data.gov.hk/en-data/dataset/hk-td-tis_16-traffic-aids-drawings-v2'));
    var ps = placeSource(area.place);
    if (ps) { src.appendChild(document.createTextNode(' · place from ')); src.appendChild(ps); }
    notes.appendChild(src);
    results.appendChild(notes);
  }

  // ---- wiring -------------------------------------------------------------------------

  window.addEventListener('svgcad:scope-changed', function (e) {
    var detail = e.detail;
    lastDetail = detail;
    renderChips(detail);
    var area = detail.scope.area;
    if (area) {
      var key = area.latitude.toFixed(5) + ',' + area.longitude.toFixed(5);
      if (key !== lastAreaKey) { showAllRows = false; userClosed = false; }
      lastAreaKey = key;
      renderResults(detail);
      if (!userClosed) open({ fit: true });
    } else {
      lastAreaKey = null;
      renderResults(detail);
      if (!mounted) close(false);
    }
    syncReopen();
  });

  // Names arrive after the first render on a cold load; redraw once they do.
  if (window.svgCadSearch) window.svgCadSearch.namesReady().then(function () {
    if (lastDetail && lastDetail.result) renderResults(lastDetail);
  });
  mapApi.iconsReady().then(function () {
    if (lastDetail && lastDetail.result) renderResults(lastDetail);
  });

  window.svgCadPanel = {
    mount: function (node, opts) {
      var slot = (opts && opts.slot) || 'top';
      (slot === 'tools' ? tools : slot === 'bottom' ? slotBottom : slotTop).appendChild(node);
      mounted = true;
      syncReopen();
    },
    open: open,
    close: function () { close(true); },
    isOpen: function () { return isOpen; },
    setTitle: function (text) { title.textContent = text; },
    setReopenLabel: function (text) { reopen.textContent = text; },
    scrollToTop: function () { scroller.scrollTop = 0; }
  };
})();
