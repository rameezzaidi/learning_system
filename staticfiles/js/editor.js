/* Subject-aware question editor.
   Reads data-kind on #qform: math | english | urdu | general, and adds the right tools above every [data-ed] field. */
(function () {
  var form = document.getElementById("qform");
  if (!form) return;
  var kind = form.dataset.kind || "general";
  var fields = [].slice.call(form.querySelectorAll("[data-ed]"));
  var last = fields[0];
  fields.forEach(function (f) { f.addEventListener("focus", function () { last = f; }); });

  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; }
  function insert(field, text, caret) {
    field.focus();
    var s = field.selectionStart, e = field.selectionEnd, v = field.value;
    field.value = v.slice(0, s) + text + v.slice(e);
    var pos = s + (caret === undefined ? text.length : caret);
    field.setSelectionRange(pos, pos);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  }
  function bar(field) { var b = el("div", "ed-bar"); b.dataset.kind = kind; field.parentNode.insertBefore(b, field); return b; }
  function button(bar, label, title, fn, cls) {
    var b = el("button", "ed-btn" + (cls ? " " + cls : ""), label); b.type = "button"; b.title = title || label;
    b.addEventListener("mousedown", function (e) { e.preventDefault(); });   // keep focus + caret in the field
    b.addEventListener("click", fn); bar.appendChild(b); return b;
  }

  /* ---------------------------------------------------------------- MATHS */
  var MATH = [
    ["a/b", "Fraction", "\\frac{}{}"], ["x²", "Square", "^{2}"], ["xⁿ", "Power", "^{}"], ["x₁", "Subscript", "_{}"],
    ["√", "Square root", "\\sqrt{}"], ["∛", "Cube root", "\\sqrt[3]{}"], ["π", "Pi", "\\pi"], ["×", "Multiply", "\\times"],
    ["÷", "Divide", "\\div"], ["±", "Plus-minus", "\\pm"], ["≤", "Less or equal", "\\le"], ["≥", "Greater or equal", "\\ge"],
    ["≠", "Not equal", "\\ne"], ["≈", "Approximately", "\\approx"], ["∞", "Infinity", "\\infty"], ["°", "Degree", "^{\\circ}"],
    ["θ", "Theta", "\\theta"], ["α", "Alpha", "\\alpha"], ["β", "Beta", "\\beta"], ["Δ", "Delta", "\\Delta"],
    ["Σ", "Sum", "\\sum_{i=1}^{n}"], ["∫", "Integral", "\\int_{a}^{b}"], ["( )", "Brackets", "\\left(  \\right)"],
    ["|x|", "Absolute value", "\\left|  \\right|"], ["→", "Arrow", "\\rightarrow"], ["∠", "Angle", "\\angle"],
    ["△", "Triangle", "\\triangle"], ["∥", "Parallel", "\\parallel"], ["⊥", "Perpendicular", "\\perp"]
  ];
  var MATH_EXAMPLES = [
    ["Solve for x", "Solve for $x$: $2x + 5 = 15$"],
    ["Simplify a fraction", "Simplify: $\\frac{12}{18}$"],
    ["Quadratic equation", "Find the roots of $x^{2} - 5x + 6 = 0$"],
    ["Area of a circle", "Find the area of a circle of radius $7$ cm. (Use $\\pi = \\frac{22}{7}$)"],
    ["Pythagoras", "In a right triangle the sides are $3$ cm and $4$ cm. Find the hypotenuse using $c^{2} = a^{2} + b^{2}$."],
    ["Square root", "Evaluate: $\\sqrt{144} + \\sqrt{81}$"]
  ];
  function mathInsert(field, snip) {
    var before = field.value.slice(0, field.selectionStart), inside = (before.split("$").length - 1) % 2 === 1;
    var text = inside ? snip : "$" + snip + "$", off = inside ? 0 : 1;
    var i = snip.indexOf("{}"), caret = i >= 0 ? off + i + 1 : (inside ? snip.length : snip.length + 1);
    insert(field, text, caret);
  }
  function mathTools() {
    // ONE toolbar (above the question text) that works on whichever box has the cursor: question, options, explanation.
    var main = fields[0], b = bar(main); b.classList.add("math");
    MATH.forEach(function (m) { button(b, m[0], m[1] + "  " + m[2], function () { mathInsert(last || main, m[2]); }); });
    var sel = el("select", "ed-sel"); sel.appendChild(new Option("Insert example…", ""));
    MATH_EXAMPLES.forEach(function (x, i) { sel.appendChild(new Option(x[0], i)); });
    sel.addEventListener("change", function () {
      if (sel.value !== "") { main.setSelectionRange(main.value.length, main.value.length); insert(main, (main.value ? "\n" : "") + MATH_EXAMPLES[sel.value][1]); sel.value = ""; }
    });
    b.appendChild(sel);
    b.appendChild(el("span", "ed-count", "works on the box you are typing in"));
    fields.forEach(function (f) {
      var prev = el("div", "ed-prev"); prev.hidden = true; f.parentNode.insertBefore(prev, f.nextSibling);
      function render() {
        prev.hidden = f.value.indexOf("$") < 0; if (prev.hidden) return;
        prev.textContent = f.value;
        if (window.renderMathInElement) window.renderMathInElement(prev, { delimiters: [{ left: "$$", right: "$$", display: true }, { left: "$", right: "$", display: false }], throwOnError: false });
      }
      f.addEventListener("input", render); window.addEventListener("load", render);
    });
    form.insertBefore(el("p", "ed-tip", "Maths editor: use the buttons to add fractions, powers, roots and symbols. Formulas sit between $ signs and a live preview appears under the box."), form.firstChild);
  }

  /* -------------------------------------------------------------- ENGLISH */
  var EN_TEMPLATES = [
    ["Fill in the blank", "Fill in the blank: She ____ to school every day."],
    ["Choose the correct word", "Choose the correct word: He is ____ than his brother."],
    ["Correct the sentence", "Correct the sentence: They was playing in the garden."],
    ["Synonym", "Choose the synonym (word with the same meaning) of “happy”."],
    ["Antonym", "Choose the antonym (opposite) of “brave”."],
    ["Active → Passive", "Change into passive voice: The teacher praised the student."],
    ["Direct → Indirect", "Change into indirect speech: He said, “I am tired.”"],
    ["Punctuation", "Add the correct punctuation: where are you going said ali"],
    ["Reading comprehension", "Read the passage and answer the question.\n\nPassage: …………\n\nQuestion: …………"]
  ];
  function englishTools() {
    fields.forEach(function (f) { f.setAttribute("spellcheck", "true"); f.setAttribute("lang", "en"); f.setAttribute("autocapitalize", "sentences"); });
    var main = fields[0], b = bar(main); b.classList.add("english");
    var tgt = function () { return last || main; };
    button(b, "____", "Insert a blank", function () { insert(tgt(), "____"); });
    button(b, "“ ”", "Quotation marks", function () { insert(tgt(), "“”", 1); });
    button(b, "’", "Apostrophe", function () { insert(tgt(), "’"); });
    button(b, "…", "Ellipsis", function () { insert(tgt(), "…"); });
    var sel = el("select", "ed-sel"); sel.appendChild(new Option("English templates…", ""));
    EN_TEMPLATES.forEach(function (x, i) { sel.appendChild(new Option(x[0], i)); });
    sel.addEventListener("change", function () {
      if (sel.value !== "") { main.setSelectionRange(main.value.length, main.value.length); insert(main, (main.value ? "\n" : "") + EN_TEMPLATES[sel.value][1]); sel.value = ""; }
    });
    b.appendChild(sel);
    var wc = el("span", "ed-count"); b.appendChild(wc);
    var upd = function () { var n = (main.value.trim().match(/\S+/g) || []).length; wc.textContent = n + " word" + (n === 1 ? "" : "s"); };
    main.addEventListener("input", upd); upd();
    form.insertBefore(el("p", "ed-tip", "English editor: spell-check is on. Use the templates for common question styles (fill in the blank, synonym, passive voice, comprehension…)."), form.firstChild);
  }

  /* ------------------------------------------------------- URDU / ISLAMIAT */
  var UR_ROWS = [
    "ا آ ب پ ت ٹ ث ج چ ح خ", "د ڈ ذ ر ڑ ز ژ س ش ص ض", "ط ظ ع غ ف ق ک گ ل م ن", "ں و ہ ھ ء ی ے ئ ؤ ۔ ، ؟",
    "َ ُ ِ ّ ً ٰ ْ ﷽ ﷺ ﴿ ﴾ ( ) :"
  ];
  function urduTools() {
    fields.forEach(function (f) { f.setAttribute("dir", "rtl"); f.setAttribute("lang", "ur"); f.classList.add("urs"); f.setAttribute("spellcheck", "false"); });
    var holder = el("div", "ed-kb"); holder.hidden = false;
    UR_ROWS.forEach(function (row) {
      var r = el("div", "ed-kbrow");
      row.split(" ").forEach(function (ch) {
        var k = el("button", "ed-key", ch); k.type = "button";
        k.addEventListener("mousedown", function (e) { e.preventDefault(); });
        k.addEventListener("click", function () { insert(last || fields[0], ch); });
        r.appendChild(k);
      });
      holder.appendChild(r);
    });
    var space = el("button", "ed-key wide", "space — خالی جگہ"); space.type = "button";
    space.addEventListener("mousedown", function (e) { e.preventDefault(); });
    space.addEventListener("click", function () { insert(last || fields[0], " "); });
    var back = el("button", "ed-key wide", "⌫"); back.type = "button";
    back.addEventListener("mousedown", function (e) { e.preventDefault(); });
    back.addEventListener("click", function () {
      var f = last || fields[0]; f.focus(); var s = f.selectionStart, e = f.selectionEnd;
      if (s === e && s > 0) { s -= 1; } f.value = f.value.slice(0, s) + f.value.slice(e); f.setSelectionRange(s, s); f.dispatchEvent(new Event("input", { bubbles: true }));
    });
    var last_row = el("div", "ed-kbrow"); last_row.appendChild(space); last_row.appendChild(back); holder.appendChild(last_row);
    var toggle = el("button", "btn ghost sm", "Urdu keyboard · اردو کی بورڈ"); toggle.type = "button";
    toggle.addEventListener("click", function () { holder.hidden = !holder.hidden; });
    var wrap = el("div", "ed-kbwrap"); wrap.appendChild(toggle); wrap.appendChild(holder);
    form.insertBefore(wrap, form.firstChild);
    form.insertBefore(el("p", "ed-tip", "Urdu editor: type with your Urdu keyboard or the on-screen keyboard. Boxes are right-to-left."), form.firstChild);
  }

  if (kind === "math") mathTools();
  else if (kind === "english") englishTools();
  else if (kind === "urdu") urduTools();
})();
