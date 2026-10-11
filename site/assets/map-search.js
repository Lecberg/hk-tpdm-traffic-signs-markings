/* The map's one search box.
 *
 * A drawing code ("TS101", "115") filters the map live, as the box always did.
 * Anything else opens suggestions: saved places instantly, verified drawing
 * names, then Lands Department places after a short pause. Picking a place
 * searches around it; picking a drawing filters to its code. Other scripts
 * (the Docker assistant) can add their own suggestions with addProvider().
 */
(function () {
  'use strict';

  if (!window.svgCadMap) return;
  var mapApi = window.svgCadMap;
  var places = window.svgCadPlaces;
  var input = document.getElementById('filter');
  var list = document.getElementById('search-suggestions');
  var shell = document.getElementById('map-search');
  if (!input || !list) return;

  var CODE_LIKE = /^(ts)?[\s_-]?\d+[a-z]?$/i;
  var REMOTE_DELAY = 350;
  var providers = [];
  var options = [];          // currently shown, in order
  var active = -1;
  var typingTimer = null, remoteTimer = null;
  var remoteState = null;    // {query, status, results}
  var pendingEnter = false;
  var queryToken = 0;

  // ---- verified drawing names ------------------------------------------------

  var names = {};            // site code -> entry
  var nameList = [];
  var namesReady = fetch('sign-names.json')
    .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(function (entries) {
      nameList = entries;
      entries.forEach(function (e) { names[e.code] = e; });
      return true;
    })
    .catch(function (err) { console.warn('Sign names unavailable:', err.message); return false; });

  function normalize(value) {
    return String(value || '').toLowerCase().replace(/\s+/g, ' ').trim();
  }

  function searchNames(query) {
    var term = normalize(query);
    if (!term) return [];
    var exact = [], partial = [];
    nameList.forEach(function (e) {
      var fields = [e.name_en, e.name_zh_hant].concat(e.aliases_en || [], e.aliases_zh_hant || []).map(normalize);
      if (fields.indexOf(term) !== -1) exact.push(e);
      else if (fields.some(function (f) { return f.indexOf(term) !== -1; })) partial.push(e);
    });
    return exact.concat(partial);
  }

  // ---- suggestions -------------------------------------------------------------

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function placeOption(place, group) {
    return { kind: 'place', group: group, place: place,
             label: places.label(place, 'en'),
             secondary: [place.name_zh_hant !== place.name_en ? place.name_zh_hant : '',
                         places.detail(place, 'en')].filter(Boolean).join(' · ') };
  }

  function build(text) {
    var opts = [];
    providers.forEach(function (provider) {
      (provider(text) || []).forEach(function (o) { opts.push(Object.assign({ group: 'Assistant' }, o)); });
    });
    // A provider marks its option primary when the text reads as a question;
    // primary options go first so Enter picks them.
    opts.sort(function (a, b) { return (b.primary ? 1 : 0) - (a.primary ? 1 : 0); });

    var local = places ? places.searchLocal(text).slice(0, 5) : [];
    local.forEach(function (p) { opts.push(placeOption(p, 'Places')); });

    searchNames(text).slice(0, 4).forEach(function (e) {
      opts.push({ kind: 'drawing', group: 'Drawings', entry: e, label: e.name_en,
                  secondary: e.code + (e.name_zh_hant ? ' · ' + e.name_zh_hant : '') });
    });

    if (remoteState && remoteState.query === text) {
      var seen = {};
      local.forEach(function (p) { seen[normalize(p.name_en)] = true; });
      if (remoteState.status === 'loading') {
        opts.push({ kind: 'status', group: 'More places', label: 'Searching the Lands Department…' });
      } else if (remoteState.status === 'unavailable') {
        opts.push({ kind: 'status', group: 'More places', label: 'Place search is unavailable right now' });
      } else {
        remoteState.results.forEach(function (p) {
          if (!seen[normalize(p.name_en)]) opts.push(placeOption(p, 'More places'));
        });
        if (!remoteState.results.length && !local.length && opts.length === 0) {
          opts.push({ kind: 'status', group: 'More places', label: 'No places found' });
        }
      }
    }
    return opts;
  }

  function render() {
    list.textContent = '';
    var selectable = 0, lastGroup = null;
    options.forEach(function (o, i) {
      if (o.group !== lastGroup) {
        list.appendChild(el('div', 'suggest-group', o.group)).setAttribute('role', 'presentation');
        lastGroup = o.group;
      }
      var row = el('div', 'suggest-option' + (o.kind === 'status' ? ' is-status' : ''));
      row.id = 'suggest-' + i;
      if (o.kind === 'status') {
        row.setAttribute('role', 'presentation');
      } else {
        row.setAttribute('role', 'option');
        row.setAttribute('aria-selected', i === active ? 'true' : 'false');
        row.dataset.index = i;
        selectable++;
      }
      row.classList.add('kind-' + o.kind);
      row.appendChild(el('span', 'suggest-label', o.label));
      if (o.secondary) row.appendChild(el('span', 'suggest-secondary', o.secondary));
      list.appendChild(row);
    });
    var open = options.length > 0;
    list.hidden = !open;
    input.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (active >= 0 && options[active]) input.setAttribute('aria-activedescendant', 'suggest-' + active);
    else input.removeAttribute('aria-activedescendant');
    return selectable;
  }

  function firstSelectable(from, step) {
    for (var i = from; i >= 0 && i < options.length; i += step) {
      if (options[i].kind !== 'status') return i;
    }
    return -1;
  }

  function show(text) {
    options = build(text);
    active = firstSelectable(0, 1);
    render();
    if (pendingEnter && remoteState && remoteState.status !== 'loading') {
      pendingEnter = false;
      if (active >= 0) choose(options[active]);
    }
  }

  // Also cancels a queued or running Lands Department lookup, so a late
  // answer can't reopen the list after a choice was made.
  function close() {
    clearTimeout(remoteTimer);
    queryToken++;
    options = [];
    active = -1;
    pendingEnter = false;
    render();
  }

  function lookupRemote(text) {
    if (input.value.trim() !== text) return;
    var token = ++queryToken;
    remoteState = { query: text, status: 'loading', results: [] };
    show(text);
    places.searchRemote(text).then(function (res) {
      if (token !== queryToken || res.status === 'aborted') return;
      remoteState = { query: text, status: res.status, results: res.results };
      if (input.value.trim() === text) show(text);
    });
  }

  // ---- input handling ------------------------------------------------------------

  function onTextChanged() {
    var text = input.value.trim();
    clearTimeout(remoteTimer);
    if (!text) {
      mapApi.setCode(null, { onlySource: 'box', push: false });
      remoteState = null;
      close();
      return;
    }
    if (CODE_LIKE.test(text)) {
      mapApi.setCode(text, { source: 'box', push: false });
      remoteState = null;
      close();
      return;
    }
    // The box no longer holds a code, so it no longer filters by one.
    mapApi.setCode(null, { onlySource: 'box', push: false });
    if (!remoteState || remoteState.query !== text) remoteState = null;
    show(text);
    if (places && text.length >= 2) {
      remoteTimer = setTimeout(function () { lookupRemote(text); }, REMOTE_DELAY);
    }
  }

  input.addEventListener('input', function () {
    clearTimeout(typingTimer);
    typingTimer = setTimeout(onTextChanged, 120);
  });

  input.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (!options.length) { if (input.value.trim()) onTextChanged(); return; }
      e.preventDefault();
      var step = e.key === 'ArrowDown' ? 1 : -1;
      var next = firstSelectable(active + step, step);
      if (next >= 0) { active = next; render(); scrollActive(); }
    } else if (e.key === 'Enter') {
      var text = input.value.trim();
      if (!text) return;
      e.preventDefault();
      clearTimeout(typingTimer);
      if (CODE_LIKE.test(text)) { onTextChanged(); return; }
      if (!options.length) onTextChanged();
      if (active >= 0 && options[active]) {
        choose(options[active]);
      } else if (places) {
        // Nothing local matched: ask the Lands Department now and take its
        // first answer.
        pendingEnter = true;
        clearTimeout(remoteTimer);
        if (!remoteState || remoteState.query !== text || remoteState.status !== 'loading') lookupRemote(text);
      }
    } else if (e.key === 'Escape') {
      if (options.length) { e.preventDefault(); close(); }
    }
  });

  function scrollActive() {
    var row = document.getElementById('suggest-' + active);
    if (row) row.scrollIntoView({ block: 'nearest' });
  }

  list.addEventListener('mousedown', function (e) { e.preventDefault(); });   // keep focus in the box
  list.addEventListener('click', function (e) {
    var row = e.target.closest('[role="option"]');
    if (row) choose(options[Number(row.dataset.index)]);
  });

  document.addEventListener('pointerdown', function (e) {
    if (options.length && !shell.contains(e.target)) close();
  });
  input.addEventListener('focus', function () {
    var text = input.value.trim();
    if (text && !CODE_LIKE.test(text)) show(text);
  });

  function choose(o) {
    if (!o || o.kind === 'status') return;
    clearTimeout(typingTimer);
    if (o.kind === 'place') {
      var scope = mapApi.getScope();
      mapApi.setArea({ latitude: o.place.latitude, longitude: o.place.longitude,
                       radius_km: scope.area ? scope.area.radius_km : 0.5, place: o.place });
    } else if (o.kind === 'drawing') {
      mapApi.setCode(o.entry.code, { source: 'chip' });
    } else if (o.onSelect) {
      o.onSelect(input.value.trim());
    }
    input.value = '';
    remoteState = null;
    close();
  }

  // When something else clears or commits the code, the box should stop
  // showing a stale code.
  window.addEventListener('svgcad:scope-changed', function (e) {
    var c = e.detail.scope.code;
    if ((!c || c.source !== 'box') && CODE_LIKE.test(input.value.trim())) input.value = '';
  });

  window.svgCadSearch = {
    addProvider: function (fn) { providers.push(fn); },
    namesReady: function () { return namesReady; },
    signName: function (c) { return names[mapApi.siteCode(c)] || null; },
    focus: function () { input.focus(); }
  };
})();
