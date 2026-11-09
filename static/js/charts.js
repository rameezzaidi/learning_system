/* EduPulse mini chart kit — dependency-free SVG charts.
   <div class="chart" data-chart='{"type":"bar","labels":[...],"values":[...]}'></div>
   types: donut | bar | hbar | line.  Optional: colors[], max, unit, center, sub, ref (reference line), height */
(function () {
  var NS = "http://www.w3.org/2000/svg";
  var PAL = ["var(--primary)", "#8b5cf6", "#10b981", "#f59e0b", "#f43f5e", "#06b6d4", "#64748b"];
  function el(n, a, p) { var e = document.createElementNS(NS, n); for (var k in a) e.setAttribute(k, a[k]); if (p) p.appendChild(e); return e; }
  function h(t, c, p) { var e = document.createElement(t); if (c) e.className = c; if (p) p.appendChild(e); return e; }
  function col(d, i) { return (d.colors && d.colors[i]) || PAL[i % PAL.length]; }
  function fmt(v, d) { var u = d.unit || ""; return (Math.round(v * 10) / 10) + u; }
  function nice(max) { if (max <= 10) return 10; var p = Math.pow(10, Math.floor(Math.log10(max))); return Math.ceil(max / p) * p; }
  function later(fn) { requestAnimationFrame(function () { requestAnimationFrame(fn); }); }

  function legend(root, d) {
    var l = h("div", "ch-legend", root);
    d.labels.forEach(function (t, i) {
      var it = h("span", "", l); var dot = h("i", "", it); dot.style.background = col(d, i);
      it.appendChild(document.createTextNode(t + " · " + fmt(d.values[i], d)));
    });
  }

  function donut(root, d) {
    var total = d.values.reduce(function (a, b) { return a + b; }, 0);
    var wrap = h("div", "ch-donut", root);
    var S = 180, R = 70, C = 2 * Math.PI * R;
    var svg = el("svg", { viewBox: "0 0 " + S + " " + S, role: "img", "aria-label": d.title || "chart" }, wrap);
    el("circle", { cx: 90, cy: 90, r: R, fill: "none", "stroke-width": 22, class: "ch-track" }, svg);
    var off = 0;
    d.values.forEach(function (v, i) {
      if (!total || v <= 0) return;
      var len = v / total * C;
      var c = el("circle", { cx: 90, cy: 90, r: R, fill: "none", "stroke-width": 22, "stroke-dasharray": "0 " + C, "stroke-dashoffset": -off, transform: "rotate(-90 90 90)", class: "ch-seg" }, svg);
      c.style.stroke = col(d, i);
      c.style.transitionDelay = (i * 90) + "ms";
      (function (c, len) { later(function () { c.setAttribute("stroke-dasharray", Math.max(len - 2, 0.1) + " " + C); }); })(c, len);
      off += len;
    });
    var t = h("div", "ch-center", wrap);
    t.innerHTML = "<b>" + (d.center != null ? d.center : total) + "</b><span>" + (d.sub || "Total") + "</span>";
    legend(root, d);
  }

  function bar(root, d) {
    var n = d.values.length, H = d.height || 220, W = Math.max(n * 56 + 50, root.clientWidth || 520), padL = 34, padB = 34, padT = 22;
    var max = d.max || nice(Math.max.apply(null, d.values.concat([d.ref || 0])));
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, preserveAspectRatio: "xMidYMid meet", role: "img", "aria-label": d.title || "chart" }, root);
    var ph = H - padB - padT;
    for (var g = 0; g <= 4; g++) {
      var y = padT + ph - ph * g / 4;
      el("line", { x1: padL, x2: W - 6, y1: y, y2: y, class: "ch-grid" }, svg);
      var tx = el("text", { x: padL - 8, y: y + 4, "text-anchor": "end", class: "ch-axis" }, svg); tx.textContent = Math.round(max * g / 4);
    }
    var slot = (W - padL - 6) / n, bw = Math.min(46, slot * .55);
    d.values.forEach(function (v, i) {
      var x = padL + slot * i + (slot - bw) / 2, bh = ph * Math.min(v, max) / max;
      var r = el("rect", { x: x, y: padT + ph, width: bw, height: 0, rx: 7, class: "ch-bar" }, svg);
      r.style.fill = col(d, d.single ? 0 : i); r.style.transitionDelay = (i * 70) + "ms";
      (function (r, bh) { later(function () { r.setAttribute("y", padT + ph - bh); r.setAttribute("height", Math.max(bh, 1)); }); })(r, bh);
      var vt = el("text", { x: x + bw / 2, y: padT + ph - bh - 7, "text-anchor": "middle", class: "ch-val" }, svg); vt.textContent = fmt(v, d);
      var lt = el("text", { x: x + bw / 2, y: H - 12, "text-anchor": "middle", class: "ch-axis" }, svg);
      var s = d.labels[i]; lt.textContent = s.length > 11 ? s.slice(0, 10) + "…" : s;
      var tt = el("title", {}, r); tt.textContent = d.labels[i] + ": " + fmt(v, d);
    });
    if (d.ref) {
      var ry = padT + ph - ph * d.ref / max;
      el("line", { x1: padL, x2: W - 6, y1: ry, y2: ry, class: "ch-ref" }, svg);
      var rt = el("text", { x: padL + 4, y: ry - 5, "text-anchor": "start", class: "ch-reft" }, svg); rt.textContent = (d.refLabel || "Pass") + " " + d.ref;
    }
  }

  function hbar(root, d) {
    var max = d.max || nice(Math.max.apply(null, d.values));
    var box = h("div", "ch-hbar", root);
    d.values.forEach(function (v, i) {
      var row = h("div", "ch-row", box);
      var lab = h("span", "ch-lab", row); lab.textContent = d.labels[i]; lab.title = d.labels[i];
      var tr = h("div", "ch-trk", row); var f = h("i", "", tr); f.style.background = col(d, d.single ? 0 : i); f.style.transitionDelay = (i * 60) + "ms";
      var val = h("b", "", row); val.textContent = fmt(v, d);
      (function (f, v) { later(function () { f.style.width = Math.min(100, v * 100 / max) + "%"; }); })(f, v);
    });
  }

  function line(root, d) {
    var n = d.values.length, H = d.height || 220, W = Math.max(n * 56 + 50, root.clientWidth || 520), padL = 34, padB = 32, padT = 18;
    var max = d.max || nice(Math.max.apply(null, d.values));
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": d.title || "chart" }, root);
    var ph = H - padB - padT, pw = W - padL - 14;
    for (var g = 0; g <= 4; g++) {
      var y = padT + ph - ph * g / 4;
      el("line", { x1: padL, x2: W - 8, y1: y, y2: y, class: "ch-grid" }, svg);
      var tx = el("text", { x: padL - 8, y: y + 4, "text-anchor": "end", class: "ch-axis" }, svg); tx.textContent = Math.round(max * g / 4);
    }
    var pts = d.values.map(function (v, i) { return [padL + (n === 1 ? pw / 2 : pw * i / (n - 1)), padT + ph - ph * v / max]; });
    var path = pts.map(function (p, i) { return (i ? "L" : "M") + p[0] + " " + p[1]; }).join(" ");
    var area = el("path", { d: path + " L" + pts[n - 1][0] + " " + (padT + ph) + " L" + pts[0][0] + " " + (padT + ph) + " Z", class: "ch-area" }, svg);
    var ln = el("path", { d: path, class: "ch-line", fill: "none" }, svg);
    var L = ln.getTotalLength ? ln.getTotalLength() : 600;
    ln.style.strokeDasharray = L; ln.style.strokeDashoffset = L; area.style.opacity = 0;
    later(function () { ln.style.strokeDashoffset = 0; area.style.opacity = 1; });
    pts.forEach(function (p, i) {
      var c = el("circle", { cx: p[0], cy: p[1], r: 4.5, class: "ch-dot" }, svg);
      var tt = el("title", {}, c); tt.textContent = d.labels[i] + ": " + fmt(d.values[i], d);
      var lt = el("text", { x: p[0], y: H - 10, "text-anchor": "middle", class: "ch-axis" }, svg); lt.textContent = d.labels[i].length > 10 ? d.labels[i].slice(0, 9) + "…" : d.labels[i];
    });
  }

  function render(node) {
    if (node.dataset.done) return;
    var d; try { d = JSON.parse(node.getAttribute("data-chart")); } catch (e) { return; }
    node.dataset.done = "1"; node.innerHTML = "";
    if (!d.values || !d.values.length || !d.values.some(function (v) { return v > 0; }) && d.type === "donut") {
      var e = h("div", "ch-empty", node); e.textContent = d.empty || "No data yet."; return;
    }
    ({ donut: donut, bar: bar, hbar: hbar, line: line }[d.type] || bar)(node, d);
  }
  function init() { document.querySelectorAll(".chart[data-chart]").forEach(render); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
