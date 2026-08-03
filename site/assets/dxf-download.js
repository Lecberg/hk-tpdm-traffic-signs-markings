(function () {
  "use strict";

  // GitHub Pages gzips only a whitelist of content types, and DXF is not on
  // it: the files go out as image/vnd.dxf with no content-encoding, so
  // TS_2714 costs a visitor 924 KB. The .dxf.gz built next to it is ~8x
  // smaller. Pages gives no way to set response headers, so this fetches the
  // compressed file and inflates it here instead.
  //
  // All of it sits on top of a link that already works. Without
  // DecompressionStream - or if the fetch, the inflate, or anything else
  // fails - the browser follows the original href and pulls the plain .dxf,
  // which is exactly what it did before.
  if (typeof DecompressionStream !== "function") return;
  if (!window.fetch || !window.Blob || !window.URL || !URL.createObjectURL) return;

  var BUSY = "is-downloading";

  document.addEventListener("click", function (ev) {
    if (ev.defaultPrevented || ev.button !== 0) return;
    // Modified clicks mean "open in a new tab" or "save as". Those are the
    // browser's to handle; intercepting them would break both.
    if (ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.altKey) return;

    var a = ev.target && ev.target.closest && ev.target.closest("a[download]");
    if (!a) return;

    var href = a.getAttribute("href") || "";
    if (href.slice(-4).toLowerCase() !== ".dxf") return;
    if (a.classList.contains(BUSY)) return;

    ev.preventDefault();
    a.classList.add(BUSY);

    var name = href.split("/").pop();

    fetch(href + ".gz")
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.arrayBuffer();
      })
      .then(function (buf) {
        var bytes = new Uint8Array(buf);
        // If a host ever serves these with Content-Encoding: gzip the browser
        // will have inflated the body already and the magic number is gone.
        // Inflating a second time would throw, so only do it when the bytes
        // really are still compressed.
        if (bytes.length > 1 && bytes[0] === 0x1f && bytes[1] === 0x8b) {
          return new Response(
            new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"))
          ).arrayBuffer();
        }
        return buf;
      })
      .then(function (out) {
        a.classList.remove(BUSY);
        save(new Blob([out], { type: "image/vnd.dxf" }), name);
      })
      .catch(function () {
        a.classList.remove(BUSY);
        window.location.href = href;   // let the plain file through
      });
  });

  function save(blob, name) {
    var url = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = url;
    link.download = name;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    // Revoked late on purpose: Safari cancels an in-flight download if the
    // object URL is released in the same tick as the click.
    setTimeout(function () { URL.revokeObjectURL(url); }, 60000);
  }
})();
