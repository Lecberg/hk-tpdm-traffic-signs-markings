(function () {
  'use strict';

  if (!window.svgCadMap) return;

  fetch('runtime-config.json', { cache: 'no-store' })
    .then(function (response) { if (!response.ok) throw new Error('config'); return response.json(); })
    .then(function (config) {
      if (config.api_enabled === true && config.api_version === 1) start();
    }).catch(function () { /* The public static edition needs no API. */ });

  function start() {
    var isMap = !!window.svgCadMap;
    var language = sessionStorage.getItem('svgcad_language') === 'zh-Hant' ? 'zh-Hant' : 'en';
    var generation = 0;
    var controller = null;
    var uploadId = null;
    var activeCode = null;
    var pendingApplied = false;
    var lastFocus = null;
    var words = {
      en: { open: 'Assistant', close: 'Close', title: 'Traffic sign assistant',
        search: 'Find signs', searchHint: 'Code or sourced description', find: 'Find',
        places: 'Find a place', placeHint: 'Place name', near: 'Signs near map point or centre',
        radius: 'Radius (km)', query: 'Count signs', upload: 'Convert an SVG',
        convert: 'Convert', chat: 'Ask the assistant', send: 'Send', reset: 'Reset',
        noChat: 'Chat needs a configured model service. Search and conversion still work.',
        privacy: 'Chat messages and tool results go to the configured model service.',
        codeOnly: 'Code only; no sourced description', noResults: 'No sourced match. Try a code.',
        applied: 'Applied to the page', pending: 'Open map', selected: 'Map centre',
        error: 'Request failed. Please retry.', busy: 'Working…',
        source: 'Source', showGallery: 'Show these in gallery',
        reviewed: 'sourced bilingual labels', results: 'result(s)',
        sourceChecked: 'Source checked; human review pending',
        placeMissing: 'No place found. Try a more specific name or use a map point.',
        placeUnavailable: 'The place lookup service is unavailable. Try again or use a map point.',
        placeBusy: 'Place lookup is busy. Try again shortly.',
        placeLimited: 'Only the first 10 places are shown. Refine the name to see others.',
        locationPoint: 'Location point, not a guaranteed entrance',
        landsSource: 'Lands Department',
        hadSource: 'Home Affairs Department',
        placeGuide: 'Map points may not mark entrances; district points mark centres.',
        selectPlace: 'Select',
        placeCount: 'Showing {shown} of {total} places',
        externalSearch: 'Unlisted names are sent to the Lands Department for lookup.',
        choosePlace: 'Choose a place', placesFound: 'place(s)',
        records: 'surveyed records', incomplete: 'incomplete data',
        showing: 'showing first', chooseSvg: 'Choose an SVG file',
        downloadDxf: 'Download DXF', converted: 'Converted. Download expires in one hour.',
        uploadOnly: 'Upload for chat', uploaded: 'SVG uploaded for this session.',
        ready: 'Ready', resetDone: 'Reset', provider: 'Provider',
        signsTab: 'Signs', mapTab: 'Map', convertTab: 'Convert', chatTab: 'Chat',
        configure: 'Configure API', setupIntro: 'Chat needs a configured model service.',
        setupCopy: 'Copy .env.example to .env in this project folder.',
        setupChoose: 'Set AI_PROVIDER and its matching key. Custom also needs CUSTOM_API_BASE_URL and CUSTOM_MODEL.',
        setupRestart: 'Run this command in the project folder, then refresh this page:',
        setupPrivate: 'Put keys in .env, not in this page.',
        checkChat: 'Could not check chat. Check that the backend is running.',
        drawingCodes: 'drawing codes', filterCodes: 'Filter drawing codes',
        showAll: 'Show all', showLess: 'Show less', noCodes: 'No matching codes',
        centrePoint: 'District centre point, not a boundary',
        unverified: 'not yet validated', validated: 'live test passed', experimental: 'experimental',
        noMatches: 'No checked match was found', clarify: 'Give a code, place, or map point.',
        help: 'Search signs, count signs on the map, or convert an SVG.',
        limits: 'The count uses all matching records. The list may show fewer.',
        askSign: 'Ask about this drawing', latest: 'Latest reply',
        chatHistory: 'Chat history' },
      'zh-Hant': { open: '助手', close: '關閉', title: '交通標誌助手',
        search: '搜尋標誌', searchHint: '編號或有來源的描述', find: '搜尋',
        places: '搜尋地點', placeHint: '地點名稱', near: '查詢地圖選點或中心附近標誌',
        radius: '半徑（公里）', query: '統計標誌', upload: '轉換 SVG',
        convert: '轉換', chat: '詢問助手', send: '發送', reset: '重設',
        noChat: '聊天需要設定模型服務。搜尋和轉換仍可使用。',
        privacy: '聊天內容和工具結果會傳送至設定的模型服務。',
        codeOnly: '只有編號，沒有附來源的描述', noResults: '找不到有來源的結果，請嘗試編號。',
        applied: '已套用到頁面', pending: '開啟地圖', selected: '地圖中心',
        error: '請求失敗，請重試。', busy: '處理中…',
        source: '來源', showGallery: '在圖庫顯示',
        reviewed: '個有來源的雙語標籤', results: '個結果',
        sourceChecked: '已核對來源；尚待人工審核',
        placeMissing: '找不到地點，請嘗試更具體的名稱或在地圖上選點。',
        placeUnavailable: '地點查詢服務暫時無法使用，請稍後再試或在地圖上選點。',
        placeBusy: '地點查詢繁忙，請稍後再試。',
        placeLimited: '只顯示首 10 個地點，請縮窄搜尋以查看其他結果。',
        locationPoint: '位置參考點，未必是建築物入口',
        landsSource: '地政總署',
        hadSource: '民政事務總署',
        placeGuide: '地圖位置未必是入口；區域位置是中心參考點。',
        selectPlace: '選擇',
        placeCount: '顯示 {shown} / {total} 個地點',
        externalSearch: '未列出的地名會傳送至地政總署查詢。',
        choosePlace: '請選擇地點', placesFound: '個地點',
        records: '個已測量的標誌紀錄', incomplete: '資料不完整',
        showing: '顯示首', chooseSvg: '請選擇 SVG 檔案',
        downloadDxf: '下載 DXF', converted: '轉換完成。下載連結一小時後到期。',
        uploadOnly: '上傳供聊天使用', uploaded: 'SVG 已上傳至此工作階段。',
        ready: '就緒', resetDone: '已重設', provider: '供應商',
        signsTab: '標誌', mapTab: '地圖', convertTab: '轉換', chatTab: '聊天',
        configure: '設定 API', setupIntro: '聊天需要設定模型服務。',
        setupCopy: '在此專案資料夾將 .env.example 複製為 .env。',
        setupChoose: '設定 AI_PROVIDER 及對應金鑰。自訂服務亦需要 CUSTOM_API_BASE_URL 和 CUSTOM_MODEL。',
        setupRestart: '在專案資料夾執行以下指令，然後重新整理頁面：',
        setupPrivate: '請將金鑰填入 .env，不要貼在此頁面。',
        checkChat: '無法檢查聊天狀態，請確認後端正在執行。',
        drawingCodes: '個圖紙編號', filterCodes: '篩選圖紙編號',
        showAll: '顯示全部', showLess: '收起', noCodes: '沒有符合的編號',
        centrePoint: '區域中心參考點，並非邊界',
        unverified: '尚未驗證', validated: '即時測試通過', experimental: '實驗中',
        noMatches: '找不到已核實的結果', clarify: '請提供編號、地點或地圖位置。',
        help: '可搜尋標誌、查詢地圖或轉換 SVG。',
        limits: '數量包括全部符合的紀錄，清單可能只顯示部分。',
        askSign: '詢問這張圖紙', latest: '最新回覆',
        chatHistory: '聊天紀錄' }
    };
    function t(key) { return words[language][key]; }
    function el(tag, cls, text) {
      var item = document.createElement(tag);
      if (cls) item.className = cls;
      if (text != null) item.textContent = text;
      return item;
    }
    function button(text, onClick, cls) {
      var item = el('button', cls, text);
      item.type = 'button';
      item.addEventListener('click', onClick);
      return item;
    }
    function setupChoiceMenu(root, initial, onSelect) {
      var summary = root.querySelector('summary');
      var choices = Array.prototype.slice.call(root.querySelectorAll('button[data-value]'));
      function select(value, notify) {
        var selected = choices.find(function (choice) { return choice.dataset.value === value; });
        if (!selected) return;
        root.dataset.value = value;
        summary.textContent = selected.textContent;
        summary.setAttribute('aria-label', root.dataset.label + ': ' + selected.textContent);
        choices.forEach(function (choice) {
          choice.setAttribute('aria-pressed', choice === selected ? 'true' : 'false');
        });
        if (notify) onSelect(value);
      }
      choices.forEach(function (choice) {
        choice.setAttribute('aria-label', choice.textContent);
        choice.addEventListener('click', function () {
          var changed = root.dataset.value !== choice.dataset.value;
          select(choice.dataset.value, changed);
          root.open = false;
          if (root.contains(document.activeElement)) summary.focus();
        });
      });
      root.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && root.open) {
          event.preventDefault(); event.stopPropagation();
          root.open = false; summary.focus(); return;
        }
        if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp' &&
            event.key !== 'Home' && event.key !== 'End') return;
        event.preventDefault();
        root.open = true;
        var index = choices.indexOf(document.activeElement);
        if (event.key === 'Home') index = 0;
        else if (event.key === 'End') index = choices.length - 1;
        else if (index < 0) index = event.key === 'ArrowDown' ? 0 : choices.length - 1;
        else index = (index + (event.key === 'ArrowDown' ? 1 : -1) + choices.length) % choices.length;
        choices[index].focus();
      });
      document.addEventListener('pointerdown', function (event) {
        if (root.open && !root.contains(event.target)) root.open = false;
      });
      select(initial, false);
    }
    function label(parent, text, control) {
      var holder = el('label', '', text);
      holder.appendChild(control);
      parent.appendChild(holder);
      return holder;
    }
    function input(type, placeholder) {
      var item = el('input');
      item.type = type; item.placeholder = placeholder;
      return item;
    }
    function section(title, parent) {
      var area = el('section');
      area.appendChild(el('h3', '', title));
      parent.appendChild(area);
      return area;
    }
    function status(text) { statusEl.textContent = text; }
    function clearResults(target) { target.textContent = ''; }
    function api(path, options) {
      if (controller) controller.abort();
      controller = new AbortController();
      var signal = controller.signal;
      var opts = Object.assign({ credentials: 'same-origin', signal: signal }, options || {});
      return fetch('/api/' + path, opts).then(function (response) {
        return response.json().then(function (data) {
          if (!response.ok) throw new Error(data.error && data.error.message || 'HTTP ' + response.status);
          return data;
        });
      });
    }
    function jsonPost(path, data) {
      return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' },
                         body: JSON.stringify(data) });
    }
    function run(promise, done) {
      var mine = ++generation;
      status(t('busy'));
      promise.then(function (data) {
        if (mine !== generation) return;
        done(data);
      }).catch(function (error) {
        if (mine !== generation || error.name === 'AbortError') return;
        status(error.message || t('error'));
      });
    }
    window.addEventListener('svgcad:user-action', function () {
      generation++;
      if (controller) controller.abort();
    });
    function safeAsset(path, code, kind) {
      return typeof path === 'string' && path === kind + 's/' + code + '.' + kind ? path : null;
    }
    function showSign(sign, target) {
      if (!sign || !/^(TS|RM)_\d+[A-Z]?$/.test(sign.code)) return;
      var card = el('div', 'assistant-result');
      var svg = safeAsset(sign.downloads && sign.downloads.svg, sign.code, 'svg');
      var dxf = safeAsset(sign.downloads && sign.downloads.dxf, sign.code, 'dxf');
      if (svg) {
        var previewBox = el('div', 'assistant-preview');
        if (sign.category === 'RM') previewBox.classList.add('assistant-preview-marking');
        var preview = el('img'); preview.src = svg; preview.alt = sign.code;
        previewBox.appendChild(preview);
        card.appendChild(previewBox);
      }
      card.appendChild(el('strong', '', sign.code));
      var meta = sign.metadata;
      card.appendChild(el('p', 'assistant-small', meta ?
        (language === 'zh-Hant' ? meta.name_zh_hant : meta.name_en) : t('codeOnly')));
      if (sign.metadata_status === 'source_checked')
        card.appendChild(el('p', 'assistant-small', t('sourceChecked')));
      if (meta && meta.source && /^https:\/\//.test(meta.source.url)) {
        var source = el('a', 'assistant-link', t('source'));
        source.href = meta.source.url; source.target = '_blank'; source.rel = 'noopener noreferrer';
        card.appendChild(source);
      }
      [['SVG', svg], ['DXF', dxf]].forEach(function (pair) {
        if (!pair[1]) return;
        var link = el('a', 'assistant-link', pair[0]);
        link.href = pair[1]; link.download = '';
        card.appendChild(link);
      });
      card.appendChild(button(t('askSign'), function () {
        activeCode = sign.code;
        selectView('chat');
        if (!chatInput.disabled) {
          chatInput.value = language === 'zh-Hant' ? '請顯示圖紙 ' + sign.code : 'Show drawing ' + sign.code;
          chatInput.focus();
        }
      }));
      target.appendChild(card);
    }
    function showSearch(data) {
      clearResults(searchResults);
      searchResults.appendChild(el('p', 'assistant-small', data.matched_total + ' ' + t('results') + '; ' +
        (data.coverage.verified_bilingual + data.coverage.source_checked_bilingual) +
        '/' + data.coverage.total_drawings + ' ' + t('reviewed')));
      if (!data.results.length) searchResults.appendChild(el('p', '', t('noResults')));
      data.results.forEach(function (sign) { showSign(sign, searchResults); });
      status('');
      if (window.svgCadGallery && data.results.length) {
        searchResults.insertBefore(button(t('showGallery'), function () {
          status(window.svgCadGallery.setExactCodes(data.results.map(function (item) { return item.code; }))
            ? t('applied') : t('error'));
        }), searchResults.children[1] || null);
      }
    }
    function placeText(place, stem) {
      return place[stem + (language === 'zh-Hant' ? '_zh_hant' : '_en')] ||
        place[stem + (language === 'zh-Hant' ? '_en' : '_zh_hant')] || '';
    }
    function placeNotice(data, target) {
      if (data.lookup_status === 'unavailable') target.appendChild(el('p', 'assistant-small', t('placeUnavailable')));
      else if (data.lookup_status === 'rate_limited') target.appendChild(el('p', 'assistant-small', t('placeBusy')));
      else if (!(data.results || data.items || []).length)
        target.appendChild(el('p', 'assistant-small', t('placeMissing')));
    }
    function showPlace(place, target, resultTarget) {
      var card = el('div', 'assistant-place');
      var description = el('div', 'assistant-place-description');
      var title = placeText(place, 'name');
      description.appendChild(el('strong', '', title));
      var address = placeText(place, 'address');
      var district = placeText(place, 'district');
      var subtitle = [place.kind === 'district_center' ? t('centrePoint') : '',
        district, address].filter(Boolean).join(' · ');
      if (subtitle) {
        var meta = el('p', 'assistant-small assistant-place-meta', subtitle);
        meta.title = subtitle;
        description.appendChild(meta);
      }
      card.appendChild(description);
      var choose = button(t('selectPlace'), function () {
        var action = { latitude: place.latitude, longitude: place.longitude, radius_km: 0.5 };
        run(jsonPost('map/query', action), function (result) {
          target.querySelectorAll('.assistant-place').forEach(function (item) {
            item.classList.toggle('assistant-place-selected', item === card);
          });
          showMapResult(result, action, resultTarget, true);
        });
      });
      choose.setAttribute('aria-label', t('selectPlace') + ': ' + title);
      card.appendChild(choose); target.appendChild(card);
    }
    function showPlaceSources(items, target) {
      if (!items.length) return;
      var note = el('p', 'assistant-small', t('placeGuide') + ' ' + t('source') + ': ');
      var added = {};
      items.forEach(function (place) {
        var url = place.source && place.source.url;
        var key = /^https:\/\/www\.map\.gov\.hk\/gs\/api\//.test(url) ? 'landsSource' :
          /^https:\/\/www\.had\.gov\.hk\//.test(url) ? 'hadSource' : null;
        if (!key || added[key]) return;
        added[key] = true;
        if (Object.keys(added).length > 1) note.appendChild(document.createTextNode(' · '));
        var link = el('a', '', t(key));
        link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer';
        note.appendChild(link);
      });
      target.appendChild(note);
    }
    function showMapResult(data, action, target, compact) {
      var targetResults = target || mapResults;
      clearResults(targetResults);
      targetResults.appendChild(el('p', '', data.matched_total + ' ' + t('records') +
        (data.data_complete ? '' : ' (' + t('incomplete') + ')') +
        (data.truncated ? '; ' + t('showing') + ' ' + data.returned_records.length : '')));
      var codeTarget = targetResults;
      if (compact && (data.available_drawings || []).length) {
        codeTarget = el('details', 'assistant-place-codes');
        codeTarget.appendChild(el('summary', '', (data.available_drawings || []).length + ' ' + t('drawingCodes')));
        targetResults.appendChild(codeTarget);
      }
      var detailResults = el('div', 'assistant-detail'); codeTarget.appendChild(detailResults);
      var codes = data.available_drawings.filter(function (code) { return /^TS_\d+[A-Z]?$/.test(code); });
      if (codes.length) {
        var filterLabel = el('label', 'assistant-small', t('filterCodes'));
        var filter = input('search', t('filterCodes'));
        filterLabel.appendChild(filter); codeTarget.appendChild(filterLabel);
        var codeList = el('div', 'assistant-code-list'); codeTarget.appendChild(codeList);
        var showAll = false;
        function renderCodes() {
          clearResults(codeList);
          var matches = codes.filter(function (code) {
            return code.toLowerCase().indexOf(filter.value.trim().toLowerCase()) !== -1;
          });
          var visible = showAll || filter.value.trim() ? matches : matches.slice(0, 12);
          visible.forEach(function (code) {
            codeList.appendChild(button(code, function () {
              run(api('signs/' + encodeURIComponent(code)), function (detail) {
                clearResults(detailResults); showSign(detail, detailResults); status(code);
              });
            }));
          });
          if (!matches.length) codeList.appendChild(el('p', 'assistant-small', t('noCodes')));
          if (!filter.value.trim() && matches.length > 12) {
            codeList.appendChild(button((showAll ? t('showLess') : t('showAll')) +
              ' ' + matches.length + ' ' + t('drawingCodes'), function () {
                showAll = !showAll; renderCodes();
              }, 'assistant-more'));
          }
        }
        filter.addEventListener('input', renderCodes); renderCodes();
      }
      if (isMap) {
        var token = generation;
        status(t('busy'));
        window.svgCadMap.ready().then(function (ready) {
          if (token !== generation) return;
          status(ready && window.svgCadMap.applyQuery(action) ? t('applied') : t('error'));
        }).catch(function () { if (token === generation) status(t('error')); });
      } else {
        targetResults.prepend(button(t('pending'), function () {
          sessionStorage.setItem('svgcad_map_action', JSON.stringify({ time: Date.now(), action: action }));
          location.href = 'map.html';
        }));
        status(t('pending'));
      }
    }

    var opener = button(t('open'), function () {
      lastFocus = document.activeElement;
      panel.hidden = false; opener.hidden = true; close.focus();
    }, 'assistant-open');
    document.body.appendChild(opener);
    var panel = el('aside', 'assistant-panel');
    panel.hidden = true; panel.setAttribute('aria-label', t('title'));
    var top = el('div', 'assistant-top');
    top.appendChild(el('h2', '', t('title')));
    var languageSelect = el('details', 'assistant-choice assistant-language-menu');
    languageSelect.dataset.label = 'Language';
    languageSelect.appendChild(el('summary', '', 'English'));
    var languageChoices = el('div', 'assistant-choice-menu');
    languageChoices.setAttribute('role', 'group');
    languageChoices.setAttribute('aria-label', 'Languages');
    [['en', 'English'], ['zh-Hant', '繁體中文']].forEach(function (pair) {
      var option = el('button', '', pair[1]);
      option.type = 'button'; option.dataset.value = pair[0];
      languageChoices.appendChild(option);
    });
    languageSelect.appendChild(languageChoices);
    setupChoiceMenu(languageSelect, language, changeLanguage);
    top.appendChild(languageSelect);
    var close = button(t('close'), function () {
      panel.hidden = true; opener.hidden = false;
      (lastFocus || opener).focus();
    });
    top.appendChild(close); panel.appendChild(top);
    var taskNav = el('div', 'assistant-tasks');
    taskNav.setAttribute('role', 'tablist');
    taskNav.setAttribute('aria-label', t('title'));
    panel.appendChild(taskNav);
    var taskViews = el('div', 'assistant-views'); panel.appendChild(taskViews);
    var viewKeys = ['signs', 'map', 'convert', 'chat'];
    var viewLabels = { signs: 'signsTab', map: 'mapTab', convert: 'convertTab', chat: 'chatTab' };
    var views = {}, tabs = {};
    function selectView(key) {
      viewKeys.forEach(function (name) {
        var selected = name === key;
        tabs[name].setAttribute('aria-selected', selected ? 'true' : 'false');
        tabs[name].tabIndex = selected ? 0 : -1;
        views[name].hidden = !selected;
      });
      if (key === 'chat' && chatResults) scrollToLatest();
      status('');
    }
    viewKeys.forEach(function (key, index) {
      var tab = button(t(viewLabels[key]), function () { selectView(key); }, 'assistant-task');
      tab.id = 'assistant-tab-' + key;
      tab.setAttribute('role', 'tab');
      tab.setAttribute('aria-controls', 'assistant-view-' + key);
      tab.addEventListener('keydown', function (event) {
        var next = event.key === 'ArrowRight' ? index + 1 :
          event.key === 'ArrowLeft' ? index - 1 :
          event.key === 'Home' ? 0 : event.key === 'End' ? viewKeys.length - 1 : -1;
        if (next < 0 && event.key !== 'ArrowLeft') return;
        if (next === -1 && event.key === 'ArrowLeft') next = viewKeys.length - 1;
        if (next >= viewKeys.length) next = 0;
        event.preventDefault(); selectView(viewKeys[next]); tabs[viewKeys[next]].focus();
      });
      tabs[key] = tab; taskNav.appendChild(tab);
      var view = el('div', 'assistant-view');
      if (key === 'chat') view.classList.add('assistant-chat-disabled');
      view.id = 'assistant-view-' + key;
      view.setAttribute('role', 'tabpanel');
      view.setAttribute('aria-labelledby', tab.id);
      views[key] = view; taskViews.appendChild(view);
    });
    var statusEl = el('p', 'assistant-status');
    statusEl.setAttribute('role', 'status'); top.insertAdjacentElement('afterend', statusEl);
    selectView('signs');
    var searchSection = section(t('search'), views.signs);
    var searchRow = el('div', 'assistant-row');
    var searchInput = input('search', t('searchHint'));
    searchInput.setAttribute('aria-label', t('search'));
    searchRow.appendChild(searchInput);
    var searchButton = button(t('find'), function () {
      if (!searchInput.value.trim()) return;
      run(api('signs?q=' + encodeURIComponent(searchInput.value.trim())), showSearch);
    }, 'assistant-primary');
    searchRow.appendChild(searchButton);
    searchSection.appendChild(searchRow);
    var searchResults = el('div', 'assistant-results'); searchSection.appendChild(searchResults);

    var placeSection = section(t('places'), views.map);
    var placeRow = el('div', 'assistant-row');
    var placeInput = input('search', t('placeHint'));
    placeInput.setAttribute('aria-label', t('places')); placeRow.appendChild(placeInput);
    var placeButton = button(t('find'), function () {
      if (!placeInput.value.trim()) return;
      run(api('places?q=' + encodeURIComponent(placeInput.value.trim())), function (data) {
        clearResults(placeResults);
        clearResults(placeMapResults);
        if (data.results.length) placeResults.appendChild(el('p', 'assistant-small',
          t('placeCount').replace('{shown}', data.results.length).replace('{total}', data.matched_total)));
        placeNotice(data, placeResults);
        data.results.forEach(function (place) { showPlace(place, placeResults, placeMapResults); });
        showPlaceSources(data.results, placeResults);
        status('');
      });
    });
    placeRow.appendChild(placeButton);
    placeSection.appendChild(placeRow);
    var placePrivacy = el('p', 'assistant-small', t('externalSearch'));
    placeSection.appendChild(placePrivacy);
    var placeResults = el('div', 'assistant-results'); placeSection.appendChild(placeResults);
    var placeMapResults = el('div', 'assistant-results assistant-place-outcome');
    placeSection.appendChild(placeMapResults);

    var mapSection, radiusLabel, mapButton;
    if (isMap) {
      mapSection = section(t('near'), views.map);
      var radius = input('number', '0.5'); radius.value = '0.5';
      radius.min = '0.01'; radius.max = '5'; radius.step = '0.1';
      radiusLabel = label(mapSection, t('radius'), radius);
      mapButton = button(t('query'), function () {
        var point = window.svgCadMap.currentPoint();
        var action = { latitude: point.latitude, longitude: point.longitude,
                       radius_km: Number(radius.value) };
        run(jsonPost('map/query', action), function (result) { showMapResult(result, action); });
      });
      mapSection.appendChild(mapButton);
    }
    var mapResults = el('div', 'assistant-results');
    (mapSection || placeSection).appendChild(mapResults);
    if (isMap) window.addEventListener('svgcad:scope-cleared', function () {
      clearResults(placeMapResults);
      clearResults(mapResults);
      panel.querySelectorAll('.assistant-place-selected').forEach(function (item) {
        item.classList.remove('assistant-place-selected');
      });
      panel.querySelectorAll('.assistant-place-outcome').forEach(clearResults);
      status('');
    });

    var uploadSection = section(t('upload'), views.convert);
    var fileInput = input('file', ''); fileInput.accept = '.svg,image/svg+xml';
    fileInput.setAttribute('aria-label', 'SVG file');
    fileInput.addEventListener('change', function () { uploadId = null; });
    uploadSection.appendChild(fileInput);
    var options = el('div', 'assistant-options');
    var curve = input('number', ''); curve.value = '0.05'; curve.step = 'any';
    var snap = input('number', ''); snap.value = '0.01'; snap.step = 'any';
    var scale = input('number', ''); scale.value = '1'; scale.step = 'any';
    label(options, 'Curve tolerance', curve); label(options, 'Snap tolerance', snap);
    label(options, 'Scale', scale); uploadSection.appendChild(options);
    function uploadSelected() {
      var form = new FormData(); form.append('file', fileInput.files[0]);
      return api('uploads', { method: 'POST', body: form }).then(function (uploaded) {
        uploadId = uploaded.upload_id;
        return uploaded;
      });
    }
    var uploadButton = button(t('uploadOnly'), function () {
      if (!fileInput.files.length) { status(t('chooseSvg')); return; }
      run(uploadSelected(), function () { status(t('uploaded')); });
    });
    uploadSection.appendChild(uploadButton);
    var convertButton = button(t('convert'), function () {
      if (!fileInput.files.length) { status(t('chooseSvg')); return; }
      run((uploadId ? Promise.resolve() : uploadSelected()).then(function () {
        return jsonPost('conversions', { upload_id: uploadId, curve_tol: Number(curve.value),
          snap_tol: Number(snap.value), scale: Number(scale.value) });
      }), function (data) {
        clearResults(convertResults);
        var link = el('a', 'assistant-link', t('downloadDxf'));
        if (/^\/api\/files\/[A-Za-z0-9_-]+$/.test(data.download_url)) link.href = data.download_url;
        link.download = ''; convertResults.appendChild(link);
        (data.stats.warnings || []).forEach(function (warning) {
          convertResults.appendChild(el('p', 'assistant-small', warning));
        });
        status(t('converted'));
      });
    }, 'assistant-primary');
    uploadSection.appendChild(convertButton);
    var convertResults = el('div', 'assistant-results'); uploadSection.appendChild(convertResults);

    var chatSection = section(t('chat'), views.chat);
    var providerName = '';
    var providerModel = '';
    var providerValidation = '';
    var chatPending = false;
    var chatAvailable = null;
    var queuedMapQuestion = null;
    var providerLine = el('p', 'assistant-small');
    chatSection.appendChild(providerLine);
    function showProvider() {
      if (!providerName) return;
      var names = { openai: 'OpenAI', deepseek: 'DeepSeek', vercel: 'Vercel AI Gateway',
        custom: language === 'zh-Hant' ? '自訂' : 'Custom' };
      providerLine.textContent = t('provider') + ': ' + (names[providerName] || providerName) +
        (providerModel ? ' · ' + providerModel : '') +
        (providerValidation ? ' · ' + (t(providerValidation) || providerValidation) : '');
    }
    var chatSetup = el('div', 'assistant-setup');
    var setupIntro = el('p', '', t('setupIntro')); chatSetup.appendChild(setupIntro);
    var setupDetails = el('details');
    var setupSummary = el('summary', '', t('configure')); setupDetails.appendChild(setupSummary);
    var setupCopy = el('p', '', t('setupCopy')); setupDetails.appendChild(setupCopy);
    var setupChoose = el('p', '', t('setupChoose')); setupDetails.appendChild(setupChoose);
    var providerList = el('ul');
    ['openai → OPENAI_API_KEY', 'deepseek → DEEPSEEK_API_KEY',
      'vercel → AI_GATEWAY_API_KEY + AI_GATEWAY_MODEL',
      'custom → CUSTOM_API_BASE_URL + CUSTOM_MODEL + CUSTOM_API_KEY'].forEach(function (entry) {
      providerList.appendChild(el('li', '', entry));
    });
    setupDetails.appendChild(providerList);
    var setupRestart = el('p', '', t('setupRestart')); setupDetails.appendChild(setupRestart);
    setupDetails.appendChild(el('code', 'assistant-command',
      'docker compose up -d --force-recreate backend'));
    var setupPrivate = el('p', 'assistant-small', t('setupPrivate'));
    setupDetails.appendChild(setupPrivate);
    chatSetup.appendChild(setupDetails); chatSection.appendChild(chatSetup);
    var chatReady = el('div', 'assistant-chat-ready'); chatReady.hidden = true; chatSection.appendChild(chatReady);
    var chatInput = el('textarea'); chatInput.maxLength = 2000;
    chatInput.disabled = true;
    chatInput.setAttribute('aria-label', t('chat'));
    chatReady.appendChild(chatInput);
    function openMapAction(action) {
      var query = { latitude: action.latitude, longitude: action.longitude,
                    radius_km: action.radius_km || 0.5 };
      if (action.code) query.code = action.code;
      if (isMap) {
        window.svgCadMap.ready().then(function (ready) {
          status(ready && window.svgCadMap.applyQuery(query) ? t('applied') : t('error'));
        }).catch(function () { status(t('error')); });
      } else {
        sessionStorage.setItem('svgcad_map_action', JSON.stringify({ time: Date.now(), action: query }));
        location.href = 'map.html';
      }
    }
    function renderTurn(turn) {
      if (!turn || !turn.id) return;
      var existing = chatResults.querySelector('[data-turn-id="' + turn.id + '"]');
      if (existing) existing.remove();
      var entry = el('article', 'assistant-turn');
      entry.dataset.turnId = turn.id;
      entry.appendChild(el('p', 'assistant-question', turn.message));
      entry.appendChild(el('p', 'assistant-answer', turn.status === 'working' ? t('busy') : turn.answer));
      (turn.blocks || []).forEach(function (block) {
        if (block.type === 'signs') {
          if (!block.items.length) entry.appendChild(el('p', 'assistant-small', t('noMatches')));
          block.items.forEach(function (sign) { showSign(sign, entry); });
          if (block.truncated) entry.appendChild(el('p', 'assistant-small', t('limits')));
        } else if (block.type === 'places') {
          placeNotice(block, entry);
          var placeList = el('div', 'assistant-place-list'); entry.appendChild(placeList);
          var placeOutcome = el('div', 'assistant-place-outcome');
          block.items.forEach(function (place) { showPlace(place, placeList, placeOutcome); });
          showPlaceSources(block.items, entry);
          entry.appendChild(placeOutcome);
        } else if (block.type === 'map') {
          entry.appendChild(el('p', 'assistant-small', block.matched_total + ' ' + t('records') +
            (block.truncated ? ' · ' + t('limits') : '') +
            (!block.data_complete ? ' · ' + t('incomplete') : '')));
          var codeList = el('div', 'assistant-code-list');
          (block.available_drawings || []).slice(0, 20).forEach(function (code) {
            codeList.appendChild(button(code, function () {
              api('signs/' + encodeURIComponent(code)).then(function (sign) { showSign(sign, entry); });
            }));
          });
          entry.appendChild(codeList);
          if ((block.available_drawings || []).length > 20)
            entry.appendChild(el('p', 'assistant-small', t('showing') + ' 20 ' + t('drawingCodes')));
        } else if (block.type === 'conversion') {
          if (/^\/api\/files\/[A-Za-z0-9_-]+$/.test(block.download_url || '')) {
            var link = el('a', 'assistant-link', t('downloadDxf'));
            link.href = block.download_url; link.download = ''; entry.appendChild(link);
          }
          (block.stats && block.stats.warnings || []).forEach(function (warning) {
            entry.appendChild(el('p', 'assistant-small', warning));
          });
        } else if (block.type === 'notice') {
          entry.appendChild(el('p', 'assistant-small', block.message));
        } else if (block.type === 'help' || block.type === 'clarify') {
          entry.appendChild(el('p', 'assistant-small', t(block.type)));
        }
      });
      (turn.actions || []).forEach(function (action) {
        if (action.type === 'open_map')
          entry.appendChild(button(t('pending'), function () { openMapAction(action); }));
        if (action.type === 'show_gallery')
          entry.appendChild(button(t('showGallery'), function () {
            if (window.svgCadGallery)
              status(window.svgCadGallery.setExactCodes(action.codes) ? t('applied') : t('error'));
            else {
              sessionStorage.setItem('svgcad_gallery_codes', JSON.stringify(action.codes));
              location.href = 'index.html';
            }
          }));
      });
      chatResults.appendChild(entry);
      scrollToLatest();
    }
    var send = button(t('send'), function () {
      var message = chatInput.value.trim();
      if (!message || chatPending) return;
      var context = { page: isMap ? 'map' : 'gallery' };
      if (isMap) context.map_point = window.svgCadMap.currentPoint();
      if (activeCode) context.active_code = activeCode;
      var request = { turn_id: crypto.randomUUID(), message: message, language: language,
                      context: context, upload_id: uploadId };
      chatPending = true; send.disabled = true; status(t('busy'));
      fetch('/api/chat', { method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request) })
        .then(function (response) { return response.json().then(function (data) {
          if (!response.ok) throw new Error(data.error && data.error.message || t('error'));
          return data;
        }); })
        .then(function (data) {
          renderTurn(data.turn); chatInput.value = ''; status(t('ready'));
        }).catch(function (error) { status(error.message || t('error')); })
        .finally(function () { chatPending = false; send.disabled = false; });
    }, 'assistant-primary');
    send.disabled = true;
    chatReady.appendChild(send);
    var privacy = el('p', 'assistant-small', t('privacy')); chatReady.appendChild(privacy);
    var chatResults = el('div', 'assistant-results assistant-chat-history');
    chatResults.setAttribute('role', 'log');
    chatResults.setAttribute('aria-label', t('chatHistory'));
    chatSection.insertBefore(chatResults, chatReady);
    var latestButton = button(t('latest'), scrollToLatest, 'assistant-latest');
    latestButton.hidden = true;
    chatSection.insertBefore(latestButton, chatReady);
    function updateLatestButton() {
      latestButton.hidden = chatResults.scrollHeight - chatResults.scrollTop - chatResults.clientHeight < 80;
    }
    function scrollToLatest() {
      chatResults.scrollTop = chatResults.scrollHeight;
      updateLatestButton();
    }
    chatResults.addEventListener('scroll', updateLatestButton);
    var mapAskInput = null;
    function sendQueuedMapQuestion() {
      if (!queuedMapQuestion || chatPending || send.disabled || chatReady.hidden) return;
      if (chatInput.value.trim() !== queuedMapQuestion) {
        queuedMapQuestion = null;
        return;
      }
      queuedMapQuestion = null;
      mapAskInput.value = '';
      send.click();
    }
    if (isMap) {
      var mapSearch = document.getElementById('map-search');
      var mapSearchMode = document.getElementById('map-search-mode');
      var mapCodeInput = document.getElementById('filter');
      mapAskInput = document.getElementById('map-ask-input');
      var mapAskSubmit = document.getElementById('map-ask-submit');
      mapSearch.classList.add('assistant-search-enabled');
      mapSearchMode.hidden = false;
      setupChoiceMenu(mapSearchMode, 'codes', function (mode) {
        var asking = mode === 'ask';
        if (asking) window.svgCadMap.clearCodeFilter();
        mapCodeInput.hidden = asking;
        mapAskInput.hidden = !asking;
        mapAskSubmit.hidden = !asking;
        (asking ? mapAskInput : mapCodeInput).focus();
      });
      mapAskSubmit.addEventListener('click', function () {
        var question = mapAskInput.value.trim();
        if (!question) { mapAskInput.focus(); return; }
        if (panel.hidden) opener.click();
        selectView('chat');
        if (chatPending) { status(t('busy')); return; }
        chatInput.value = question;
        if (chatAvailable === false) { status(t('noChat')); return; }
        if (chatAvailable === 'error') { status(t('checkChat')); return; }
        queuedMapQuestion = question;
        if (chatAvailable === null) status(t('busy'));
        sendQueuedMapQuestion();
      });
      mapAskInput.addEventListener('keydown', function (event) {
        if (event.key === 'Enter') { event.preventDefault(); mapAskSubmit.click(); }
      });
    }
    var reset = button(t('reset'), function () {
      if (chatPending) { status(t('busy')); return; }
      jsonPost('session/reset', {}).then(function () {
        uploadId = null;
        activeCode = null;
        [searchResults, placeResults, placeMapResults, mapResults, convertResults, chatResults].forEach(clearResults);
        chatInput.value = '';
        status(t('resetDone'));
      }).catch(function (error) { status(error.message || t('error')); });
    }, 'assistant-reset');
    chatSection.appendChild(reset);
    document.body.appendChild(panel);

    function changeLanguage(value) {
      var oldStatus = statusEl.textContent;
      language = value;
      sessionStorage.setItem('svgcad_language', language);
      opener.textContent = t('open'); close.textContent = t('close');
      top.querySelector('h2').textContent = t('title');
      panel.setAttribute('aria-label', t('title'));
      taskNav.setAttribute('aria-label', t('title'));
      viewKeys.forEach(function (key) { tabs[key].textContent = t(viewLabels[key]); });
      searchSection.querySelector('h3').textContent = t('search');
      searchInput.placeholder = t('searchHint'); placeInput.placeholder = t('placeHint');
      searchInput.setAttribute('aria-label', t('search'));
      placeInput.setAttribute('aria-label', t('places'));
      searchButton.textContent = t('find'); placeButton.textContent = t('find');
      placeSection.querySelector('h3').textContent = t('places');
      placePrivacy.textContent = t('externalSearch');
      if (mapSection) {
        mapSection.querySelector('h3').textContent = t('near');
        radiusLabel.firstChild.textContent = t('radius');
        mapButton.textContent = t('query');
      }
      uploadSection.querySelector('h3').textContent = t('upload');
      uploadButton.textContent = t('uploadOnly');
      convertButton.textContent = t('convert');
      chatSection.querySelector('h3').textContent = t('chat');
      chatInput.setAttribute('aria-label', t('chat'));
      privacy.textContent = t('privacy'); send.textContent = t('send'); reset.textContent = t('reset');
      latestButton.textContent = t('latest');
      chatResults.setAttribute('aria-label', t('chatHistory'));
      setupIntro.textContent = t('setupIntro'); setupSummary.textContent = t('configure');
      setupCopy.textContent = t('setupCopy'); setupChoose.textContent = t('setupChoose');
      setupRestart.textContent = t('setupRestart'); setupPrivate.textContent = t('setupPrivate');
      showProvider();
      if (oldStatus === words.en.noChat || oldStatus === words['zh-Hant'].noChat)
        status(t('noChat'));
    }
    panel.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') close.click();
    });

    fetch('/api/capabilities', { credentials: 'same-origin', cache: 'no-store' })
      .then(function (response) {
        if (!response.ok) throw new Error('capabilities');
        return response.json();
      }).then(function (cap) {
        if (cap.api_version !== 1) throw new Error('API version mismatch');
        var blockedMapQuestion = false;
        chatAvailable = !!cap.chat_available;
        providerName = cap.configured_provider || '';
        providerModel = cap.chat_available ? cap.model || '' : '';
        providerValidation = cap.provider_validation || '';
        showProvider();
        chatInput.disabled = true;
        send.disabled = true;
        chatReady.hidden = !cap.chat_available;
        chatSetup.hidden = !!cap.chat_available;
        views.chat.classList.toggle('assistant-chat-disabled', !cap.chat_available);
        if (cap.chat_available) {
          fetch('/api/session', { credentials: 'same-origin', cache: 'no-store' })
            .then(function (response) { if (!response.ok) throw new Error('session'); return response.json(); })
            .then(function () {
              chatInput.disabled = false; send.disabled = false;
              sendQueuedMapQuestion();
            })
            .catch(function () {
              chatAvailable = 'error';
              queuedMapQuestion = null;
              status(t('error'));
            });
        } else if (queuedMapQuestion) {
          queuedMapQuestion = null;
          blockedMapQuestion = true;
          status(t('noChat'));
        }
        if (!pendingApplied && !blockedMapQuestion) status('');
      }).catch(function () {
        chatAvailable = 'error';
        queuedMapQuestion = null;
        setupIntro.textContent = t('checkChat');
        if (!pendingApplied) status(t('error'));
      });
    function restoreHistory(attempt) {
      fetch('/api/chat/history', { credentials: 'same-origin', cache: 'no-store' })
        .then(function (response) { if (!response.ok) throw new Error('history'); return response.json(); })
        .then(function (data) {
          (data.turns || []).forEach(renderTurn);
          if ((data.turns || []).some(function (turn) { return turn.status === 'working'; }) && attempt < 35)
            setTimeout(function () { restoreHistory(attempt + 1); }, 2000);
        }).catch(function () { /* Search and chat still work without saved history. */ });
    }
    restoreHistory(0);
    if (isMap) {
      try {
        var pending = JSON.parse(sessionStorage.getItem('svgcad_map_action') || 'null');
        sessionStorage.removeItem('svgcad_map_action');
        if (pending && Date.now() - pending.time < 60000) {
          panel.hidden = false; opener.hidden = true;
          selectView('map');
          var token = generation;
          window.svgCadMap.ready().then(function (ready) {
            if (token !== generation) return;
            pendingApplied = ready && window.svgCadMap.applyQuery(pending.action);
            status(pendingApplied ? t('applied') : t('error'));
          }).catch(function () { if (token === generation) status(t('error')); });
        }
      } catch (error) { sessionStorage.removeItem('svgcad_map_action'); }
    }
  }
})();
