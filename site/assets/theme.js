/* Theme switching, shared by the gallery and the map.
 *
 * Loaded as a blocking script in <head> so the stored theme is applied before
 * first paint (a deferred script would flash the light theme first). The
 * stylesheet also honours prefers-color-scheme on its own, so the site still
 * follows the OS with JavaScript disabled.
 */
(function () {
  'use strict';

  var root = document.documentElement;
  var media = window.matchMedia('(prefers-color-scheme: dark)');

  function stored() {
    try { return localStorage.getItem('theme'); } catch (e) { return null; }
  }

  root.dataset.theme = stored() || (media.matches ? 'dark' : 'light');

  // Follow the OS while the visitor hasn't made an explicit choice.
  media.addEventListener('change', function (e) {
    if (stored()) return;
    root.dataset.theme = e.matches ? 'dark' : 'light';
  });

  document.addEventListener('DOMContentLoaded', function () {
    var btn = document.getElementById('theme-toggle');
    if (!btn) return;

    function sync() {
      var dark = root.dataset.theme === 'dark';
      btn.setAttribute('aria-pressed', String(dark));
      var label = dark ? 'Switch to light theme' : 'Switch to dark theme';
      btn.setAttribute('aria-label', label);
      btn.title = label;
    }

    sync();

    btn.addEventListener('click', function () {
      root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem('theme', root.dataset.theme); } catch (e) {}
      sync();
    });
  });
})();
