(function () {
  "use strict";

  var BATCH = 60;        // cards appended per scroll step
  var SWAP_MS = 120;     // grid fade-out before a tab change rebuilds it
  var STAGGER_MS = 30;   // per-column delay of the card reveal
  var STAGGER_MAX = 4;   // …capped so a batch never chains longer than this
  var TO_TOP_AT = 600;   // scroll distance that reveals the back-to-top button

  var grid = document.getElementById("grid");
  var searchBox = document.getElementById("search");
  var countEl = document.getElementById("count");
  var emptyEl = document.getElementById("empty");
  var sentinel = document.getElementById("sentinel");
  var header = document.querySelector(".site-header");
  var topSentinel = document.querySelector(".top-sentinel");
  var toTop = document.getElementById("to-top");
  var tabsNav = document.querySelector(".tabs");
  var indicator = document.querySelector(".tab-indicator");
  var tabs = Array.prototype.slice.call(document.querySelectorAll(".tab"));

  var hasIO = "IntersectionObserver" in window;

  var all = [];       // full manifest
  var filtered = [];  // current filter/search result
  var rendered = 0;   // how many of `filtered` are in the DOM
  var cat = "ALL";
  var swapToken = 0;  // guards overlapping tab/search rebuilds

  // Deep links: index.html?cat=TS|RM&q=115 preselects a tab and search.
  var params = new URLSearchParams(location.search);
  var paramCat = (params.get("cat") || "").toUpperCase();
  if (paramCat === "TS" || paramCat === "RM") {
    cat = paramCat;
    tabs.forEach(function (t) {
      var active = t.dataset.cat === cat;
      t.classList.toggle("active", active);
      t.setAttribute("aria-selected", String(active));
    });
  }
  if (params.get("q")) searchBox.value = params.get("q");

  fetch("index.json")
    .then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then(function (data) {
      all = data;
      grid.setAttribute("aria-busy", "false");
      apply(true);
    })
    .catch(function (err) {
      grid.setAttribute("aria-busy", "false");
      emptyEl.hidden = false;
      emptyEl.textContent = "Could not load the sign index (" + err.message + ").";
    });

  function normalize(s) {
    return s.toUpperCase().replace(/[\s_-]+/g, "");
  }

  // `immediate` skips the crossfade — used for the first paint and for search,
  // where fading on every keystroke would read as flicker.
  function apply(immediate) {
    var q = normalize(searchBox.value);
    filtered = all.filter(function (e) {
      if (cat !== "ALL" && e.cat !== cat) return false;
      return !q || normalize(e.code).indexOf(q) !== -1;
    });

    var token = ++swapToken;

    function rebuild() {
      if (token !== swapToken) return;   // a newer change superseded this one
      grid.textContent = "";
      rendered = 0;
      emptyEl.hidden = filtered.length !== 0;
      emptyEl.textContent = "No signs match your search.";
      countEl.textContent =
        filtered.length.toLocaleString() +
        (filtered.length === 1 ? " drawing" : " drawings");
      renderMore();
      requestAnimationFrame(function () { grid.classList.remove("is-swapping"); });
    }

    if (immediate) {
      grid.classList.remove("is-swapping");
      rebuild();
      return;
    }
    grid.classList.add("is-swapping");
    setTimeout(rebuild, SWAP_MS);
  }

  function renderMore() {
    var frag = document.createDocumentFragment();
    var start = rendered;
    var end = Math.min(rendered + BATCH, filtered.length);
    var fresh = [];
    for (var i = start; i < end; i++) {
      var el = card(filtered[i]);
      el.style.transitionDelay = ((i - start) % STAGGER_MAX) * STAGGER_MS + "ms";
      fresh.push(el);
      frag.appendChild(el);
    }
    rendered = end;
    grid.appendChild(frag);

    // Observe only once the cards are in the document: an observer never
    // reports a target still sitting in a detached fragment as visible.
    fresh.forEach(function (el) {
      if (revealObserver) revealObserver.observe(el);
      else el.classList.add("in");
    });
  }

  function card(e) {
    var el = document.createElement("div");
    el.className = "card";
    el.dataset.cat = e.cat;

    var thumb = document.createElement("div");
    thumb.className = "thumb";
    var img = document.createElement("img");
    img.loading = "lazy";
    img.decoding = "async";
    img.src = e.svg;
    img.alt = e.code;
    thumb.appendChild(img);

    var code = document.createElement("div");
    code.className = "card-code";
    code.textContent = e.code;

    var actions = document.createElement("div");
    actions.className = "card-actions";
    actions.appendChild(link(e.svg, "SVG", "dl"));
    actions.appendChild(link(e.dxf, "DXF", "dl dxf"));

    el.appendChild(thumb);
    el.appendChild(code);
    el.appendChild(actions);
    return el;
  }

  function link(href, label, cls) {
    var a = document.createElement("a");
    a.className = cls;
    a.href = href;
    a.textContent = label;
    a.setAttribute("download", "");
    return a;
  }

  // ---- reveal on scroll ----------------------------------------------------

  // Cards start at opacity 0 (style.css) and fade/rise in as they reach the
  // viewport. Each card is released as soon as it has played.
  var revealObserver = hasIO && new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (!entry.isIntersecting) return;
      entry.target.classList.add("in");
      revealObserver.unobserve(entry.target);
    });
  }, { rootMargin: "0px 0px 60px 0px" });

  // ---- infinite scroll -----------------------------------------------------

  if (hasIO) {
    new IntersectionObserver(function (entries) {
      if (entries[0].isIntersecting && rendered < filtered.length) renderMore();
    }, { rootMargin: "800px" }).observe(sentinel);

    // Condense the header once the page leaves the very top.
    new IntersectionObserver(function (entries) {
      header.classList.toggle("scrolled", !entries[0].isIntersecting);
    }).observe(topSentinel);
  }

  // ---- back to top ---------------------------------------------------------

  var ticking = false;
  window.addEventListener("scroll", function () {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(function () {
      toTop.classList.toggle("show", window.scrollY > TO_TOP_AT);
      ticking = false;
    });
  }, { passive: true });

  toTop.addEventListener("click", function () {
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  // ---- tabs ----------------------------------------------------------------

  // The accent pill is one element that slides between tabs, so switching
  // categories reads as a single continuous movement.
  function moveIndicator() {
    var active = tabsNav.querySelector(".tab.active");
    if (!active) return;
    indicator.style.width = active.offsetWidth + "px";
    indicator.style.transform = "translateX(" + active.offsetLeft + "px)";
  }

  moveIndicator();
  requestAnimationFrame(function () { tabsNav.classList.remove("no-anim"); });

  if ("ResizeObserver" in window) {
    new ResizeObserver(moveIndicator).observe(tabsNav);
  } else {
    window.addEventListener("resize", moveIndicator);
  }

  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      if (cat === tab.dataset.cat) return;
      cat = tab.dataset.cat;
      tabs.forEach(function (t) {
        var active = t === tab;
        t.classList.toggle("active", active);
        t.setAttribute("aria-selected", String(active));
      });
      moveIndicator();
      apply(false);
    });
  });

  // ---- search --------------------------------------------------------------

  var debounce;
  searchBox.addEventListener("input", function () {
    clearTimeout(debounce);
    debounce = setTimeout(function () { apply(true); }, 120);
  });
})();
