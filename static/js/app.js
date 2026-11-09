(function () {
  var root = document.documentElement, body = document.body;

  // ---------- Mobile drawer (overlay, ESC, swipe, scroll-lock) ----------
  var btn = document.getElementById("menuBtn");
  var side = document.getElementById("sidebar");
  var scrim = document.getElementById("scrim");
  function setNav(open) {
    if (!side) return;
    side.classList.toggle("open", open);
    body.classList.toggle("nav-open", open);
    if (btn) { btn.setAttribute("aria-expanded", open ? "true" : "false"); btn.setAttribute("aria-label", open ? "Close menu" : "Open menu"); }
  }
  if (btn && side) {
    btn.addEventListener("click", function () { setNav(!side.classList.contains("open")); });
    if (scrim) scrim.addEventListener("click", function () { setNav(false); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") setNav(false); });
    side.addEventListener("click", function (e) { if (e.target.closest("a[href]")) setNav(false); });
    window.addEventListener("resize", function () { if (window.innerWidth > 980) setNav(false); });
    var sx = null;
    document.addEventListener("touchstart", function (e) { sx = e.touches[0].clientX; }, { passive: true });
    document.addEventListener("touchend", function (e) {
      if (sx === null) return;
      var dx = e.changedTouches[0].clientX - sx;
      if (side.classList.contains("open") && dx < -60) setNav(false);
      else if (!side.classList.contains("open") && sx < 18 && dx > 70 && window.innerWidth <= 980) setNav(true);
      sx = null;
    }, { passive: true });
    var act = side.querySelector(".nav a.active");
    if (act && act.scrollIntoView) { try { act.scrollIntoView({ block: "center" }); } catch (e) {} }
  }

  // ---------- Notification bell: close on outside click / ESC ----------
  var bell = document.getElementById("bell");
  if (bell) {
    document.addEventListener("click", function (e) { if (bell.open && !bell.contains(e.target)) bell.open = false; });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") bell.open = false; });
  }

  // ---------- Topbar shadow on scroll ----------
  var top = document.querySelector(".topbar");
  if (top) {
    var tick = false;
    window.addEventListener("scroll", function () {
      if (tick) return; tick = true;
      requestAnimationFrame(function () { top.classList.toggle("scrolled", window.scrollY > 4); tick = false; });
    }, { passive: true });
  }

  // ---------- Every table scrolls inside its card on small screens ----------
  document.querySelectorAll(".content table").forEach(function (t) {
    if (t.closest(".table-wrap, .tw, .rc-table-wrap, .paper, .paper-wrap")) return;
    var w = document.createElement("div"); w.className = "table-wrap";
    t.parentNode.insertBefore(w, t); w.appendChild(t);
  });
  function edges() {
    document.querySelectorAll(".table-wrap, .rc-table-wrap").forEach(function (w) {
      w.classList.toggle("fade-r", w.scrollWidth > w.clientWidth + 2 && w.scrollLeft + w.clientWidth < w.scrollWidth - 2);
    });
  }
  document.querySelectorAll(".table-wrap, .rc-table-wrap").forEach(function (w) { w.addEventListener("scroll", edges, { passive: true }); });
  window.addEventListener("resize", edges); window.addEventListener("load", edges); edges();

  // ---------- Pagination for every long table ----------
  function paginate(table) {
    var tb = table.tBodies[0]; if (!tb) return;
    var rows = Array.prototype.slice.call(tb.rows);
    if (table.hasAttribute("data-nopage") || rows.length <= 10) return;
    if (table.tBodies[0].querySelector("input:not([type=hidden]), select, textarea")) return;             // entry forms keep every row
    var wrap = table.closest(".table-wrap, .tw") || table.parentNode;
    var next = wrap.nextElementSibling;
    if (next && (next.classList.contains("pager") || next.classList.contains("pager-n"))) return;   // already server-paged
    var size = parseInt(table.getAttribute("data-page-size") || "10", 10), page = 1;
    var bar = document.createElement("div"); bar.className = "tpg";
    wrap.parentNode.insertBefore(bar, wrap.nextSibling);
    function draw() {
      var pages = Math.max(1, Math.ceil(rows.length / size)); if (page > pages) page = pages;
      var a = (page - 1) * size, b = Math.min(rows.length, a + size);
      rows.forEach(function (r, i) { r.hidden = !(i >= a && i < b); });
      var nums = [], i;
      for (i = 1; i <= pages; i++) if (i === 1 || i === pages || Math.abs(i - page) <= 1) nums.push(i); else if (nums[nums.length - 1] !== 0) nums.push(0);
      bar.innerHTML = '<span class="tpg-info">Showing <b>' + (a + 1) + '–' + b + '</b> of <b>' + rows.length + '</b></span>' +
        '<span class="tpg-ctl"><label class="tpg-size">Rows <select aria-label="Rows per page">' +
        [10, 25, 50, 100].map(function (n) { return '<option' + (n === size ? ' selected' : '') + '>' + n + '</option>'; }).join("") + '</select></label>' +
        '<button type="button" class="pg' + (page === 1 ? ' off' : '') + '" data-go="' + (page - 1) + '" aria-label="Previous page">&lsaquo;</button>' +
        nums.map(function (n) { return n ? '<button type="button" class="pg' + (n === page ? ' on' : '') + '" data-go="' + n + '">' + n + '</button>' : '<span class="pg gap">…</span>'; }).join("") +
        '<button type="button" class="pg' + (page === pages ? ' off' : '') + '" data-go="' + (page + 1) + '" aria-label="Next page">&rsaquo;</button></span>';
    }
    bar.addEventListener("click", function (e) {
      var g = e.target.closest("[data-go]"); if (!g || g.classList.contains("off")) return;
      page = parseInt(g.getAttribute("data-go"), 10); draw(); wrap.scrollIntoView({ block: "nearest", behavior: "smooth" });
    });
    bar.addEventListener("change", function (e) { if (e.target.tagName === "SELECT") { size = parseInt(e.target.value, 10); page = 1; draw(); } });
    draw();
  }
  document.querySelectorAll(".content table").forEach(paginate);

  // ---------- Live theme preview on the settings page ----------
  var form = document.getElementById("settingsForm");
  if (!form) return;

  function contrast(hex) {
    var h = hex.replace("#", "");
    var r = parseInt(h.substr(0, 2), 16), g = parseInt(h.substr(2, 2), 16), b = parseInt(h.substr(4, 2), 16);
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.62 ? "#0b1220" : "#ffffff";
  }
  function val(name) {
    var el = form.querySelector('[name="' + name + '"]:checked') || form.querySelector('[name="' + name + '"]');
    return el ? el.value : "";
  }
  function apply() {
    root.setAttribute("data-theme", val("theme"));
    root.setAttribute("data-font", val("font_style"));
    root.setAttribute("data-radius", val("radius"));
    root.setAttribute("data-sidebar", val("sidebar_style"));
    var custom = form.querySelector('[name="use_custom_colors"]').checked;
    document.getElementById("customColors").style.opacity = custom ? 1 : .45;
    if (custom) {
      var p = val("custom_primary");
      root.style.setProperty("--primary", p);
      root.style.setProperty("--accent", val("custom_accent"));
      root.style.setProperty("--on-primary", contrast(p));
    } else {
      ["--primary", "--accent", "--on-primary"].forEach(function (v) { root.style.removeProperty(v); });
    }
  }
  form.addEventListener("input", apply);
  form.addEventListener("change", apply);
  apply();
})();
