(function () {
  "use strict";

  var BATCH = 60; // cards appended per scroll step

  var grid = document.getElementById("grid");
  var searchBox = document.getElementById("search");
  var countEl = document.getElementById("count");
  var emptyEl = document.getElementById("empty");
  var sentinel = document.getElementById("sentinel");
  var tabs = Array.prototype.slice.call(document.querySelectorAll(".tab"));

  var all = [];       // full manifest
  var filtered = [];  // current filter/search result
  var rendered = 0;   // how many of `filtered` are in the DOM
  var cat = "ALL";

  fetch("index.json")
    .then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then(function (data) {
      all = data;
      grid.setAttribute("aria-busy", "false");
      apply();
    })
    .catch(function (err) {
      grid.setAttribute("aria-busy", "false");
      emptyEl.hidden = false;
      emptyEl.textContent = "Could not load the sign index (" + err.message + ").";
    });

  function normalize(s) {
    return s.toUpperCase().replace(/[\s_-]+/g, "");
  }

  function apply() {
    var q = normalize(searchBox.value);
    filtered = all.filter(function (e) {
      if (cat !== "ALL" && e.cat !== cat) return false;
      return !q || normalize(e.code).indexOf(q) !== -1;
    });
    grid.textContent = "";
    rendered = 0;
    emptyEl.hidden = filtered.length !== 0;
    emptyEl.textContent = "No signs match your search.";
    countEl.textContent =
      filtered.length.toLocaleString() +
      (filtered.length === 1 ? " drawing" : " drawings");
    renderMore();
  }

  function renderMore() {
    var frag = document.createDocumentFragment();
    var end = Math.min(rendered + BATCH, filtered.length);
    for (var i = rendered; i < end; i++) frag.appendChild(card(filtered[i]));
    rendered = end;
    grid.appendChild(frag);
  }

  function card(e) {
    var el = document.createElement("div");
    el.className = "card";

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

  new IntersectionObserver(function (entries) {
    if (entries[0].isIntersecting && rendered < filtered.length) renderMore();
  }, { rootMargin: "800px" }).observe(sentinel);

  var debounce;
  searchBox.addEventListener("input", function () {
    clearTimeout(debounce);
    debounce = setTimeout(apply, 120);
  });

  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      cat = tab.dataset.cat;
      tabs.forEach(function (t) {
        var active = t === tab;
        t.classList.toggle("active", active);
        t.setAttribute("aria-selected", String(active));
      });
      apply();
    });
  });
})();
