/* Docker edition only: the natural-language search agent.
 *
 * On the map it lives inside the results panel (map-panel.js) and the search
 * box (map-search.js): "Ask the assistant" is one more suggestion, the agent's
 * turns sit above the results, and a finished search applies itself to the
 * map. On the gallery it only hands sentences over to the map.
 *
 * The public site ships runtime-config.json with api_enabled false, so none
 * of this runs there.
 */
(function () {
  'use strict';

  var onMap = !!(window.svgCadMap && window.svgCadPanel && window.svgCadSearch);
  var onGallery = !onMap && !!window.svgCadGallery;
  if (!onMap && !onGallery) return;

  fetch('runtime-config.json', { cache: 'no-store' })
    .then(function (r) { if (!r.ok) throw new Error('config'); return r.json(); })
    .then(function (config) {
      if (config.api_enabled !== true || config.api_version !== 1) return null;
      return fetch('/api/capabilities', { credentials: 'same-origin', cache: 'no-store' })
        .then(function (r) { if (!r.ok) throw new Error('capabilities'); return r.json(); });
    })
    .then(function (cap) {
      if (!cap) return;
      if (cap.api_version !== 1) throw new Error('API version mismatch');
      var enabled = !!(cap.features && cap.features.search_agent);
      if (onMap) startMap(enabled); else if (enabled) startGallery();
    })
    .catch(function () { /* The public static edition needs no API. */ });

  // A request reads as a question for the agent rather than a place name.
  function looksLikeSentence(text) {
    return text.trim().split(/\s+/).length >= 3 ||
      /\b(near|nearby|within|around|metres?|meters?|km|kilomet(re|er)s?)\b|附近|公里|米內/i.test(text);
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function button(text, onClick, cls) {
    var b = el('button', cls, text);
    b.type = 'button';
    b.addEventListener('click', onClick);
    return b;
  }

  // ---- gallery: hand sentences over to the map --------------------------------

  function startGallery() {
    var box = document.getElementById('search');
    if (!box) return;
    var ask = button('Ask on the map →', function () { go(); }, 'gallery-ask');
    ask.hidden = !looksLikeSentence(box.value);   // the visitor may have typed already
    box.insertAdjacentElement('afterend', ask);
    function go() {
      var text = box.value.trim();
      if (text) location.href = 'map.html?ask=' + encodeURIComponent(text.slice(0, 2000));
    }
    box.addEventListener('input', function () { ask.hidden = !looksLikeSentence(box.value); });
    box.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && looksLikeSentence(box.value)) { e.preventDefault(); go(); }
    });
  }

  // ---- map: the agent inside the results panel ----------------------------------

  function startMap(agentEnabled) {
    var mapApi = window.svgCadMap, panelApi = window.svgCadPanel;
    var language = sessionStorage.getItem('svgcad_language') === 'zh-Hant' ? 'zh-Hant' : 'en';
    var zh = function () { return language === 'zh-Hant'; };
    var turns = [], busy = false, waiting = false;
    var words = {
      en: { title: 'Map assistant', reopen: 'Assistant', records: 'surveyed records',
        incomplete: 'Incomplete data', selected: 'Selected point', choosePlace: 'Choose a place',
        chooseDrawing: 'Choose a drawing', codeOnly: 'Code only; no sourced description',
        centrePoint: 'District centre point, not a boundary', select: 'Select', source: 'Source',
        showing: 'showing first', busy: 'Working…', error: 'Request failed. Please retry.',
        limits: 'The count uses all matching records. The list may show fewer.',
        placeGuide: 'Map points may not mark entrances; district points mark centres.',
        lands: 'Lands Department', had: 'Home Affairs Department',
        privacy: 'Requests and search results go to the configured model service.',
        noAgent: 'The assistant needs a configured model service. Map search still works.',
        request: 'Ask the assistant', refine: 'Continue or refine', run: 'Run search',
        placeholder: 'Find signs near a place, or ask for a drawing…', examples: 'Examples',
        about: 'LangGraph · session memory', reset: 'New session',
        memory: 'Search settings stay in this session. Restarting the backend clears them.',
        pickAbove: 'Choose a result above, or a numbered pin on the map.',
        emptyTitle: 'Ask in your own words.',
        emptyBody: 'Try “stop signs near Mong Kok within 500 metres”, then refine it.',
        askLabel: 'Ask the assistant', showOnMap: 'Show on map', viewDrawings: 'View drawings' },
      'zh-Hant': { title: '地圖助手', reopen: '助手', records: '個已測量的標誌紀錄',
        incomplete: '資料不完整', selected: '已選位置', choosePlace: '請選擇地點',
        chooseDrawing: '選擇圖紙', codeOnly: '只有編號，沒有附來源的描述',
        centrePoint: '區域中心參考點，並非邊界', select: '選擇', source: '來源',
        showing: '顯示首', busy: '處理中…', error: '請求失敗，請重試。',
        limits: '數量包括全部符合的紀錄，清單可能只顯示部分。',
        placeGuide: '地圖位置未必是入口；區域位置是中心參考點。',
        lands: '地政總署', had: '民政事務總署',
        privacy: '搜尋內容和結果會傳送至設定的模型服務。',
        noAgent: '助手需要設定模型服務。地圖搜尋仍可使用。',
        request: '詢問助手', refine: '繼續或調整搜尋', run: '執行搜尋',
        placeholder: '搜尋某地點附近的標誌，或查詢圖紙…', examples: '例子',
        about: 'LangGraph · 工作階段記憶', reset: '新工作階段',
        memory: '搜尋設定只保留在此工作階段，重新啟動後端會清除。',
        pickAbove: '請選擇上方結果，或地圖上的編號標記。',
        emptyTitle: '用你自己的話提問。',
        emptyBody: '例如「旺角 500 米內的停車標誌」，然後再調整。',
        askLabel: '詢問助手', showOnMap: '在地圖顯示', viewDrawings: '查看圖紙' }
    };
    function t(key) { return words[language][key]; }
    function placeText(place, stem) {
      return place[stem + (zh() ? '_zh_hant' : '_en')] || place[stem + (zh() ? '_en' : '_zh_hant')] || '';
    }
    function safeAsset(path, code, kind) {
      return typeof path === 'string' && path === kind + 's/' + code + '.' + kind ? path : null;
    }

    // -- panel header tools: language and a fresh session --
    var tools = el('div', 'assistant-tools');
    var langMenu = el('details', 'assistant-choice assistant-language-menu');
    langMenu.dataset.label = 'Language';
    langMenu.appendChild(el('summary'));
    var langList = el('div', 'assistant-choice-menu');
    langList.setAttribute('role', 'group');
    [['en', 'English'], ['zh-Hant', '繁體中文']].forEach(function (pair) {
      var b = button(pair[1], function () {
        langMenu.open = false;
        if (pair[0] !== language) setLanguage(pair[0]);
      });
      b.dataset.value = pair[0];
      langList.appendChild(b);
    });
    langMenu.appendChild(langList);
    var resetBtn = button('', function () {
      if (busy) return;
      fetch('/api/session/reset', { method: 'POST', credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) throw new Error('reset'); })
        .then(function () { turns = []; mapApi.clearChoicePins(); render(); feedback.textContent = ''; })
        .catch(function () { feedback.textContent = t('error'); });
    }, 'assistant-reset');
    tools.appendChild(langMenu);
    tools.appendChild(resetBtn);
    document.addEventListener('pointerdown', function (e) {
      if (langMenu.open && !langMenu.contains(e.target)) langMenu.open = false;
    });

    // -- agent section (above the results) and composer (panel footer) --
    var section = el('section', 'assistant-agent');
    section.setAttribute('aria-label', 'Map assistant');
    var historyEl = el('div', 'assistant-agent-history');
    historyEl.setAttribute('role', 'log');
    historyEl.setAttribute('aria-label', 'Assistant searches');
    section.appendChild(historyEl);

    var composer = el('div', 'assistant-agent-composer');
    var composerLabel = el('label', 'assistant-agent-composer-label');
    composerLabel.htmlFor = 'assistant-agent-input';
    var row = el('div', 'assistant-agent-compose-row');
    var input = el('textarea');
    input.id = 'assistant-agent-input';
    input.rows = 2;
    input.maxLength = 2000;
    var run = button('', function () { send(input.value); }, 'assistant-primary');
    row.appendChild(input);
    row.appendChild(run);
    var feedback = el('p', 'assistant-agent-feedback');
    feedback.setAttribute('role', 'status');
    var meta = el('div', 'assistant-agent-composer-meta');
    var examples = el('details', 'assistant-agent-examples');
    var examplesSummary = el('summary');
    examples.appendChild(examplesSummary);
    var exampleList = el('div');
    ['Stop signs near Mong Kok within 500 metres', 'Show drawing RM1001', 'Make it 1 kilometre'].forEach(function (text) {
      exampleList.appendChild(button(text, function () { input.value = text; examples.open = false; input.focus(); }));
    });
    examples.appendChild(exampleList);
    var about = el('details', 'assistant-agent-about');
    var aboutSummary = el('summary');
    var aboutMemory = el('p');
    var aboutPrivacy = el('p');
    about.appendChild(aboutSummary);
    about.appendChild(aboutMemory);
    about.appendChild(aboutPrivacy);
    meta.appendChild(examples);
    meta.appendChild(about);
    composer.appendChild(composerLabel);
    composer.appendChild(row);
    composer.appendChild(feedback);
    composer.appendChild(meta);
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(input.value); }
    });

    panelApi.mount(tools, { slot: 'tools' });
    panelApi.mount(section, { slot: 'top' });
    panelApi.mount(composer, { slot: 'bottom' });

    // -- the search box offers the assistant as a suggestion --
    window.svgCadSearch.addProvider(function (text) {
      if (!agentEnabled || waiting) return [];
      return [{ kind: 'ask', group: t('askLabel'), label: '“' + text.slice(0, 120) + '”',
                secondary: t('request'), primary: looksLikeSentence(text),
                onSelect: function (value) { send(value); } }];
    });

    function setLanguage(value) {
      language = value;
      sessionStorage.setItem('svgcad_language', language);
      applyWords();
      render();
    }

    function applyWords() {
      langMenu.querySelector('summary').textContent = language === 'zh-Hant' ? '繁體中文' : 'English';
      langList.querySelectorAll('button').forEach(function (b) {
        b.setAttribute('aria-pressed', b.dataset.value === language ? 'true' : 'false');
      });
      panelApi.setTitle(t('title'));
      panelApi.setReopenLabel(t('reopen'));
      resetBtn.textContent = t('reset');
      run.textContent = t('run');
      input.placeholder = t('placeholder');
      input.setAttribute('aria-label', t('request'));
      examplesSummary.textContent = t('examples');
      aboutSummary.textContent = agentEnabled ? t('about') : t('noAgent');
      aboutMemory.textContent = t('memory');
      aboutPrivacy.textContent = t('privacy');
    }

    function updateControls() {
      input.disabled = !agentEnabled || busy || waiting;
      run.disabled = input.disabled;
      exampleList.querySelectorAll('button').forEach(function (b) { b.disabled = input.disabled; });
      historyEl.querySelectorAll('button[data-agent-choice]').forEach(function (b) {
        b.disabled = busy || b.dataset.agentActive !== 'true';
      });
      section.setAttribute('aria-busy', busy ? 'true' : 'false');
      composer.classList.toggle('is-waiting', waiting);
      composerLabel.textContent = turns.length ? t('refine') : t('request');
    }

    // -- rendering --------------------------------------------------------------

    function render() {
      historyEl.textContent = '';
      waiting = turns.some(function (turn) { return turn.status === 'waiting'; });
      if (!turns.length) {
        var empty = el('div', 'assistant-agent-empty');
        empty.appendChild(el('h4', '', t('emptyTitle')));
        empty.appendChild(el('p', '', agentEnabled ? t('emptyBody') : t('noAgent')));
        historyEl.appendChild(empty);
      } else {
        historyEl.appendChild(renderTurn(turns[turns.length - 1], true));
        if (turns.length > 1) {
          var previous = el('details', 'assistant-agent-previous');
          previous.appendChild(el('summary', '', (zh() ? '之前的搜尋' : 'Previous searches') + ' (' + (turns.length - 1) + ')'));
          turns.slice(0, -1).reverse().forEach(function (turn) {
            var saved = el('details', 'assistant-agent-saved');
            var summary = el('summary');
            summary.appendChild(el('span', '', turn.message));
            var mapBlock = (turn.blocks || []).find(function (b) { return b.type === 'map'; });
            if (mapBlock) summary.appendChild(el('small', '', mapBlock.matched_total.toLocaleString() + ' ' + t('records')));
            saved.appendChild(summary);
            saved.appendChild(renderTurn(turn, false));
            previous.appendChild(saved);
          });
          historyEl.appendChild(previous);
        }
      }
      if (waiting) feedback.textContent = t('pickAbove');
      updateControls();
      showPins();
    }

    function renderTurn(turn, latest) {
      var entry = el('article', 'assistant-agent-turn');
      entry.dataset.agentTurn = turn.id;
      var top = el('div', 'assistant-agent-turn-top');
      top.appendChild(el('span', 'assistant-agent-kicker', latest ? (zh() ? '目前搜尋' : 'Latest search') : (zh() ? '之前的結果' : 'Saved result')));
      var statuses = zh() ?
        { complete: '完成', waiting: '等待選擇', working: '處理中', failed: '未完成', cancelled: '已取消' } :
        { complete: 'Complete', waiting: 'Your choice', working: 'Working', failed: 'Failed', cancelled: 'Cancelled' };
      var badge = el('span', 'assistant-agent-badge', statuses[turn.status] || turn.status);
      badge.dataset.status = turn.status;
      top.appendChild(badge);
      entry.appendChild(top);
      entry.appendChild(el('p', 'assistant-agent-question', turn.message));

      var card = el('div', 'assistant-agent-result-card');
      entry.appendChild(card);
      var mapBlock = (turn.blocks || []).find(function (b) { return b.type === 'map'; });
      var scope = turn.search || {};
      if (mapBlock) {
        card.appendChild(el('h4', '', placeText(scope.place || {}, 'name') || t('selected')));
        var scopeRow = el('div', 'assistant-agent-scope');
        scopeRow.appendChild(el('span', '', scope.radius_km + ' km'));
        scopeRow.appendChild(el('span', '', scope.drawing && scope.drawing.code || (zh() ? '全部交通標誌' : 'All traffic signs')));
        card.appendChild(scopeRow);
        var count = el('div', 'assistant-agent-count');
        count.appendChild(el('strong', '', mapBlock.matched_total.toLocaleString()));
        count.appendChild(el('span', '', t('records')));
        card.appendChild(count);
        if (!mapBlock.data_complete) card.appendChild(el('p', 'assistant-agent-warning', t('incomplete')));
        var actions = el('div', 'assistant-agent-actions');
        renderActions(turn, actions);
        card.appendChild(actions);
      } else if (!turn.pending) {
        card.appendChild(el('p', 'assistant-agent-answer', turn.answer));
      }

      if (turn.pending && turn.status === 'waiting') {
        card.appendChild(el('h4', '', turn.pending.kind === 'place' ? t('choosePlace') : t('chooseDrawing')));
        var list = el('ol', 'assistant-agent-choices');
        turn.pending.choices.forEach(function (choice) {
          var li = el('li', 'assistant-agent-choice');
          var text = el('div', 'assistant-agent-choice-text');
          var item = choice.item || {};
          text.appendChild(el('strong', '', turn.pending.kind === 'place' ? placeText(item, 'name') : choice.label));
          var extra = turn.pending.kind === 'place' ?
            [placeText(item, 'district'), placeText(item, 'address'), item.kind === 'district_center' ? t('centrePoint') : ''].filter(Boolean).join(' · ') :
            (item.metadata && placeText(item.metadata, 'name') || t('codeOnly'));
          if (extra) text.appendChild(el('span', '', extra));
          li.appendChild(text);
          var choose = button(t('select'), function () { resume(turn, choice); });
          choose.setAttribute('aria-label', t('select') + ': ' + choice.label);
          choose.dataset.agentChoice = 'true';
          choose.dataset.agentActive = 'true';
          li.appendChild(choose);
          list.appendChild(li);
        });
        card.appendChild(list);
        if (turn.pending.kind === 'place') card.appendChild(placeSources(turn.pending.choices.map(function (c) { return c.item || {}; })));
        var cancel = button(zh() ? '取消搜尋' : 'Cancel search', function () {
          request('cancel', { turn_id: turn.id, interrupt_id: turn.pending.interrupt_id });
        }, 'assistant-agent-cancel');
        cancel.dataset.agentChoice = 'true';
        cancel.dataset.agentActive = 'true';
        card.appendChild(cancel);
      }

      var seen = {};
      var drawings = el('div', 'assistant-agent-drawings');
      (turn.blocks || []).forEach(function (block) {
        if (block.type === 'signs') block.items.forEach(function (sign) {
          if (seen[sign.code]) return;
          seen[sign.code] = true;
          showDrawing(sign, drawings);
        });
        else if (block.type === 'notice') card.appendChild(el('p', 'assistant-agent-warning', block.message));
      });
      if (drawings.children.length) card.appendChild(drawings);

      if (mapBlock) {
        var notes = el('details', 'assistant-agent-data-notes');
        notes.appendChild(el('summary', '', zh() ? '資料說明' : 'Data notes'));
        notes.appendChild(el('p', '', zh() ? '紀錄數量並非獨立路牌數量。' : 'Counts are surveyed records, not necessarily unique physical signs.'));
        if (mapBlock.truncated) notes.appendChild(el('p', '', t('limits')));
        card.appendChild(notes);
      } else if (!turn.pending) {
        var drawingActions = el('div', 'assistant-agent-actions');
        renderActions(turn, drawingActions);
        card.appendChild(drawingActions);
      }

      if ((turn.trace || []).length) {
        var trace = el('details', 'assistant-agent-trace');
        trace.appendChild(el('summary', '', (zh() ? '執行步驟' : 'How it ran') + ' · ' + turn.trace.length + (zh() ? ' 步' : ' steps')));
        var steps = el('ol');
        turn.trace.forEach(function (step) {
          var li = el('li');
          li.appendChild(el('code', '', step.node));
          li.appendChild(el('span', '', step.detail));
          steps.appendChild(li);
        });
        trace.appendChild(steps);
        entry.appendChild(trace);
      }
      return entry;
    }

    function placeSources(items) {
      var note = el('p', 'assistant-agent-sources', t('placeGuide') + ' ' + t('source') + ': ');
      var added = {};
      items.forEach(function (place) {
        var url = place.source && place.source.url;
        var key = /^https:\/\/www\.map\.gov\.hk\/gs\/api\//.test(url) ? 'lands' :
          /^https:\/\/www\.had\.gov\.hk\//.test(url) ? 'had' : null;
        if (!key || added[key]) return;
        added[key] = true;
        if (Object.keys(added).length > 1) note.appendChild(document.createTextNode(' · '));
        var link = el('a', '', t(key));
        link.href = url;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        note.appendChild(link);
      });
      return note;
    }

    function mapActionOf(turn) {
      return (turn.actions || []).find(function (a) { return a.type === 'open_map'; });
    }

    function applyTurn(turn) {
      var action = mapActionOf(turn);
      if (!action) return false;
      return mapApi.applyQuery({
        latitude: action.latitude, longitude: action.longitude,
        radius_km: action.radius_km || 0.5, code: action.code || null,
        place: (turn.search && turn.search.place) || null
      });
    }

    function renderActions(turn, target) {
      (turn.actions || []).slice().sort(function (a, b) {
        return (a.type === 'open_map' ? 0 : 1) - (b.type === 'open_map' ? 0 : 1);
      }).forEach(function (action) {
        if (action.type === 'open_map') {
          target.appendChild(button(t('showOnMap'), function () { applyTurn(turn); }, 'assistant-primary'));
        } else if (action.type === 'show_gallery') {
          target.appendChild(button(t('viewDrawings'), function () {
            sessionStorage.setItem('svgcad_gallery_codes', JSON.stringify(action.codes));
            location.href = 'index.html';
          }));
        }
      });
    }

    function showDrawing(sign, target) {
      if (!sign || !/^(TS|RM)_\d+[A-Z]?$/.test(sign.code)) return;
      var card = el('div', 'assistant-agent-drawing');
      var svg = safeAsset(sign.downloads && sign.downloads.svg, sign.code, 'svg');
      var dxf = safeAsset(sign.downloads && sign.downloads.dxf, sign.code, 'dxf');
      if (svg) {
        var preview = el('div', 'assistant-agent-thumbnail');
        if (sign.category === 'RM') preview.classList.add('is-marking');
        var img = el('img');
        img.src = svg;
        img.alt = sign.code;
        preview.appendChild(img);
        card.appendChild(preview);
      }
      var detail = el('div', 'assistant-agent-drawing-detail');
      detail.appendChild(el('strong', '', sign.metadata ? placeText(sign.metadata, 'name') : sign.code));
      detail.appendChild(el('span', '', sign.metadata ? sign.code : t('codeOnly')));
      var links = el('div', 'assistant-agent-downloads');
      [['SVG', svg], ['DXF', dxf]].forEach(function (pair) {
        if (!pair[1]) return;
        var a = el('a', 'assistant-link', pair[0]);
        a.href = pair[1];
        a.download = '';
        links.appendChild(a);
      });
      if (sign.metadata && sign.metadata.source && /^https:\/\//.test(sign.metadata.source.url)) {
        var src = el('a', 'assistant-agent-source', t('source'));
        src.href = sign.metadata.source.url;
        src.target = '_blank';
        src.rel = 'noopener noreferrer';
        links.appendChild(src);
      }
      detail.appendChild(links);
      card.appendChild(detail);
      target.appendChild(card);
    }

    // Pending place choices double as numbered pins on the map.
    function showPins() {
      var turn = turns.find(function (x) { return x.status === 'waiting' && x.pending && x.pending.kind === 'place'; });
      if (!turn) { mapApi.clearChoicePins(); return; }
      mapApi.showChoicePins(turn.pending.choices.map(function (choice) {
        var item = choice.item || {};
        return { id: choice.id, label: choice.label, latitude: item.latitude, longitude: item.longitude };
      }), function (pin) {
        var choice = turn.pending.choices.find(function (c) { return c.id === pin.id; });
        if (choice) resume(turn, choice);
      });
    }

    // -- requests -------------------------------------------------------------------

    function context() {
      var ctx = { page: 'map', map_point: mapApi.currentPoint() };
      var scope = mapApi.getScope();
      if (scope.area) {
        // What is on screen now, so "make it 1 km" refines that even after
        // the chips were changed by hand.
        ctx.scope = { latitude: scope.area.latitude, longitude: scope.area.longitude,
                      radius_km: scope.area.radius_km,
                      code: scope.code && scope.code.exact ? scope.code.text : null,
                      place: scope.area.place ? scope.area.place.name_en : null };
      }
      return ctx;
    }

    function send(text) {
      var message = String(text || '').trim();
      if (!message || busy || waiting || !agentEnabled) return;
      panelApi.open({ fit: false, sheet: 'half' });
      request('search', { message: message, language: language, context: context() });
    }

    function resume(turn, choice) {
      request('resume', { turn_id: turn.id, interrupt_id: turn.pending.interrupt_id, choice_id: choice.id });
    }

    function request(operation, payload) {
      if (busy) return;
      busy = true;
      updateControls();
      feedback.textContent = t('busy');
      payload.request_id = crypto.randomUUID();
      fetch('/api/agent/' + operation, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
      }).then(function (r) {
        return r.json().then(function (data) {
          if (!r.ok) throw new Error(data.error && data.error.message || t('error'));
          return data;
        });
      }).then(function (data) {
        var index = turns.findIndex(function (turn) { return turn.id === data.turn.id; });
        if (index < 0) turns.push(data.turn); else turns[index] = data.turn;
        turns = turns.slice(-8);
        input.value = '';
        feedback.textContent = data.turn.status === 'waiting' ? t('pickAbove') : '';
        busy = false;
        render();
        panelApi.scrollToTop();
        if (data.turn.status === 'complete') applyTurn(data.turn);
      }).catch(function (error) {
        feedback.textContent = error.message;
      }).finally(function () {
        busy = false;
        updateControls();
      });
    }

    applyWords();
    render();

    fetch('/api/agent/history', { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('history'); return r.json(); })
      .then(function (data) {
        turns = data.turns || [];
        render();
        if (turns.length) panelApi.open({ fit: false });
      })
      .catch(function () { /* Map search works without saved history. */ })
      .then(function () {
        // ?ask= comes from the gallery. Drop it from the URL before sending so
        // a reload can't send the same question twice.
        var params = new URLSearchParams(location.search);
        var ask = params.get('ask');
        if (params.get('agent') === '1') panelApi.open({ fit: false });
        if (ask) {
          params.delete('ask');
          var query = params.toString();
          window.history.replaceState(window.history.state, '', location.pathname + (query ? '?' + query : '') + location.hash);
          send(ask);
        }
      });
  }
})();
