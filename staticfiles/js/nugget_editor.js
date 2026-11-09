/* Nugget editor: formatting toolbar + live preview (same grammar as nuggets/md.py), subject tools (maths / Urdu),
   and the AI coach panel. No dependencies. */
(function () {
  var form = document.getElementById("nf"); if (!form) return;
  var $ = function (id) { return document.getElementById(id); };
  var expl = $("id_explanation"), pts = $("id_key_points"), cards = $("id_cards_text"), qs = $("id_questions_text"), course = $("id_course");
  var fields = [expl, pts, cards, qs], last = expl, kinds = {};
  try { kinds = JSON.parse(form.dataset.kinds || "{}"); } catch (e) {}
  fields.forEach(function (f) { f.addEventListener("focus", function () { last = f; }); });
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; }
  function fire(f) { f.dispatchEvent(new Event("input", { bubbles: true })); }
  function insert(f, text, caret) {
    f.focus(); var s = f.selectionStart, e = f.selectionEnd, v = f.value;
    f.value = v.slice(0, s) + text + v.slice(e); var pos = s + (caret === undefined ? text.length : caret); f.setSelectionRange(pos, pos); fire(f);
  }
  function wrap(f, pre, post, ph) {
    f.focus(); var s = f.selectionStart, e = f.selectionEnd, sel = f.value.slice(s, e) || ph;
    f.value = f.value.slice(0, s) + pre + sel + post + f.value.slice(e); f.setSelectionRange(s + pre.length, s + pre.length + sel.length); fire(f);
  }
  function linePrefix(f, pre, numbered) {
    f.focus(); var s = f.selectionStart, e = f.selectionEnd, v = f.value;
    var a = v.lastIndexOf("\n", s - 1) + 1, b = v.indexOf("\n", e); if (b < 0) b = v.length;
    var n = 0, block = v.slice(a, b).split("\n").map(function (l) { n++; return (numbered ? n + ". " : pre) + l.replace(/^(\s*[-*•]\s+|\s*\d+[.)]\s+|#{1,3}\s+|>\s?)/, ""); }).join("\n");
    f.value = v.slice(0, a) + block + v.slice(b); f.setSelectionRange(a, a + block.length); fire(f);
  }
  function btn(bar, label, title, fn, cls) {
    var b = el("button", "ed-btn" + (cls ? " " + cls : ""), label); b.type = "button"; b.title = title;
    b.addEventListener("mousedown", function (e) { e.preventDefault(); }); b.addEventListener("click", fn); bar.appendChild(b); return b;
  }

  /* ---------- formatting toolbar + preview for the explanation ---------- */
  var bar = el("div", "ed-bar ne-bar");
  btn(bar, "H", "Heading", function () { linePrefix(expl, "## "); }, "b");
  btn(bar, "B", "Bold (**text**)", function () { wrap(expl, "**", "**", "important word"); }, "b");
  btn(bar, "I", "Italic (*text*)", function () { wrap(expl, "*", "*", "text"); }, "i");
  btn(bar, "• List", "Bullet list", function () { linePrefix(expl, "- "); });
  btn(bar, "1. List", "Numbered list", function () { linePrefix(expl, "", true); });
  btn(bar, "❝ Note", "Quote / remember box", function () { linePrefix(expl, "> "); });
  btn(bar, "Example", "Insert an example block", function () { insert(expl, (expl.value && !/\n$/.test(expl.value) ? "\n\n" : "") + "## Example\n", undefined); });
  expl.parentNode.insertBefore(bar, expl);
  var prev = el("div", "ne-prev"); prev.appendChild(el("div", "ne-prev-h", "Live preview — this is how students see it"));
  var prevBody = el("div", "ng-expl"); prev.appendChild(prevBody);
  var after = expl.nextSibling; while (after && !(after.classList && after.classList.contains("help"))) after = after.nextSibling;
  expl.parentNode.insertBefore(prev, after ? after.nextSibling : null);

  function esc(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#x27;"); }
  function inline(s) { return s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/(^|[^*])\*(?!\s)(.+?)(?<!\s)\*(?!\*)/g, "$1<em>$2</em>"); }
  function render(text) {
    var saved = []; text = esc(text || "").replace(/\r\n/g, "\n").replace(/\$[^$\n]+\$/g, function (m) { saved.push(m); return "\u0000" + (saved.length - 1) + "\u0000"; });
    var out = [], para = [], items = [], kind = "", m;
    function fp() { if (para.length) { out.push("<p>" + para.map(inline).join("<br>") + "</p>"); para = []; } }
    function fl() { if (items.length) { out.push("<" + kind + ">" + items.map(function (i) { return "<li>" + inline(i) + "</li>"; }).join("") + "</" + kind + ">"); items = []; } kind = ""; }
    text.split("\n").forEach(function (raw) {
      var line = raw.replace(/\s+$/, "");
      if (!line.trim()) { fp(); fl(); }
      else if ((m = line.match(/^(#{1,3})\s+(.+)$/))) { fp(); fl(); var h = m[1].length + 2; out.push("<h" + h + ">" + inline(m[2]) + "</h" + h + ">"); }
      else if ((m = line.match(/^\s*[-*•]\s+(.+)$/)) || (m = line.match(/^\s*\d+[.)]\s+(.+)$/))) { fp(); var w = /^\s*\d/.test(line) ? "ol" : "ul"; if (kind && kind !== w) fl(); kind = w; items.push(m[1]); }
      else if ((m = line.match(/^&gt;\s?(.+)$/))) { fp(); fl(); out.push("<blockquote>" + inline(m[1]) + "</blockquote>"); }
      else { fl(); para.push(line); }
    });
    fp(); fl();
    return out.join("").replace(/\u0000(\d+)\u0000/g, function (_, i) { return saved[+i]; });
  }
  var timer;
  function paint() {
    prevBody.innerHTML = render(expl.value) || '<p class="muted">Start typing to see the preview…</p>';
    if (window.renderMathInElement && expl.value.indexOf("$") >= 0) window.renderMathInElement(prevBody, { delimiters: [{ left: "$$", right: "$$", display: true }, { left: "$", right: "$", display: false }], throwOnError: false });
  }
  expl.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(paint, 120); });
  window.addEventListener("load", paint); paint();

  /* ---------- subject tools: change with the chosen course ---------- */
  var MATH = [["a/b", "\\frac{}{}"], ["x²", "^{2}"], ["xⁿ", "^{}"], ["√", "\\sqrt{}"], ["π", "\\pi"], ["×", "\\times"], ["÷", "\\div"], ["±", "\\pm"],
    ["≤", "\\le"], ["≥", "\\ge"], ["≠", "\\ne"], ["≈", "\\approx"], ["°", "^{\\circ}"], ["θ", "\\theta"], ["Δ", "\\Delta"], ["∞", "\\infty"], ["→", "\\rightarrow"]];
  var UR = ["ا آ ب پ ت ٹ ث ج چ ح خ", "د ڈ ذ ر ڑ ز ژ س ش ص ض", "ط ظ ع غ ف ق ک گ ل م ن", "ں و ہ ھ ء ی ے ئ ؤ ۔ ، ؟", "َ ُ ِ ّ ً ٰ ْ ﷽ ﷺ ﴿ ﴾ ( ) :"];
  var tools = el("div", "ne-tools"); expl.closest(".field").parentNode.insertBefore(tools, expl.closest(".field"));
  function mathInsert(f, snip) {
    var inside = (f.value.slice(0, f.selectionStart).split("$").length - 1) % 2 === 1, i = snip.indexOf("{}");
    insert(f, inside ? snip : "$" + snip + "$", i >= 0 ? (inside ? 0 : 1) + i + 1 : (inside ? snip.length : snip.length + 1));
  }
  function setTools() {
    var kind = kinds[course.value] || "general"; tools.innerHTML = "";
    fields.forEach(function (f) { var u = kind === "urdu"; f.setAttribute("dir", u ? "rtl" : "ltr"); f.classList.toggle("urs", u); });
    if (kind === "math") {
      var b = el("div", "ed-bar"); b.appendChild(el("span", "ed-count", "Maths: click a symbol — formulas go between $ signs")); b.firstChild.style.marginLeft = "0"; b.firstChild.style.width = "100%";
      MATH.forEach(function (m) { btn(b, m[0], m[1], function () { mathInsert(last, m[1]); }); }); tools.appendChild(b);
    } else if (kind === "urdu") {
      var holder = el("div", "ed-kb"); holder.hidden = true;
      UR.forEach(function (row) { var r = el("div", "ed-kbrow"); row.split(" ").forEach(function (ch) { var k = el("button", "ed-key", ch); k.type = "button"; k.addEventListener("mousedown", function (e) { e.preventDefault(); }); k.addEventListener("click", function () { insert(last, ch); }); r.appendChild(k); }); holder.appendChild(r); });
      var t = el("button", "btn ghost sm", "Urdu keyboard · اردو کی بورڈ"); t.type = "button"; t.onclick = function () { holder.hidden = !holder.hidden; };
      tools.appendChild(t); tools.appendChild(holder);
    }
  }
  course.addEventListener("change", setTools); setTools();

  /* ---------- AI coach ---------- */
  var go = $("ai-go"), out = $("ai-out"), undo = null;
  function val(id) { var e = $(id); return e ? e.value : ""; }
  function append(f, lines) { var v = f.value.replace(/\s+$/, ""); f.value = (v ? v + "\n" : "") + lines.join("\n"); fire(f); f.scrollTop = f.scrollHeight; }
  function section(title, items, cls) {
    if (!items || !items.length) return null; var s = el("div", "ai-sec " + (cls || "")); s.appendChild(el("h4", "", title)); var ul = el("ul");
    items.forEach(function (i) { var li = el("li"); if (i.area) { li.appendChild(el("b", "", i.area + ": ")); li.appendChild(document.createTextNode(i.tip)); } else li.textContent = i; ul.appendChild(li); });
    s.appendChild(ul); return s;
  }
  function action(label, fn) { var b = el("button", "btn ghost sm block", label); b.type = "button"; b.onclick = function () { fn(b); }; return b; }
  go.addEventListener("click", function () {
    if (!course.value) { out.hidden = false; out.textContent = "Choose a course first."; return; }
    go.disabled = true; var old = go.innerHTML; go.textContent = "Reading your draft…"; out.hidden = true;
    var fd = new FormData(); fd.append("course", course.value);
    ["topic", "title", "explanation", "key_points", "video_url", "cards_text", "questions_text"].forEach(function (n) { fd.append(n, val("id_" + n)); });
    fetch(form.dataset.suggest, { method: "POST", body: fd, headers: { "X-CSRFToken": form.querySelector("[name=csrfmiddlewaretoken]").value } })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }).then(function (j) {
        out.innerHTML = ""; out.hidden = false;
        var head = el("div", "ai-head"), sc = el("div", "ai-score", j.score + "/10"); sc.className += j.score >= 8 ? " hi" : j.score >= 6 ? " mid" : " lo";
        var tx = el("div"); tx.appendChild(el("b", "", j.summary)); tx.appendChild(el("small", "muted", j.source === "ai" ? "AI review" : "Rule-based review (add a Gemini key in .env for smarter AI feedback)"));
        head.append(sc, tx); out.appendChild(head);
        if (j.error) out.appendChild(el("p", "ai-err", j.error));
        [section("What works", j.strengths, "good"), section("How to make it better", j.improvements)].forEach(function (s) { if (s) out.appendChild(s); });
        var acts = el("div", "ai-acts");
        if (j.improved_explanation) acts.appendChild(action("✎ Use the improved explanation", function (b) { undo = expl.value; expl.value = j.improved_explanation; fire(expl); b.textContent = "✓ Applied — "; var u = el("a", "", "undo"); u.href = "#"; u.onclick = function (e) { e.preventDefault(); expl.value = undo; fire(expl); b.textContent = "✎ Use the improved explanation"; }; b.appendChild(u); }));
        if (j.extra_key_points && j.extra_key_points.length) acts.appendChild(action("+ Add " + j.extra_key_points.length + " key points", function (b) { append(pts, j.extra_key_points); b.textContent = "✓ Added"; b.disabled = true; }));
        if (j.extra_card_lines && j.extra_card_lines.length) acts.appendChild(action("+ Add " + j.extra_card_lines.length + " flashcards", function (b) { append(cards, j.extra_card_lines); b.textContent = "✓ Added"; b.disabled = true; }));
        if (j.extra_question_lines && j.extra_question_lines.length) acts.appendChild(action("+ Add " + j.extra_question_lines.length + " quiz questions", function (b) { append(qs, j.extra_question_lines); b.textContent = "✓ Added"; b.disabled = true; }));
        if (acts.children.length) { out.appendChild(el("h4", "", "One-click fixes")); out.appendChild(acts); }
      }).catch(function () { out.hidden = false; out.textContent = "Could not get suggestions. Check your connection and try again."; })
      .then(function () { go.disabled = false; go.innerHTML = old; });
  });
})();
