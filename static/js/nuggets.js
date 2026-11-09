(function () {
  var root = document.getElementById("ng"); if (!root) return;
  var tabs = root.querySelectorAll(".ng-tabs button"), panes = root.querySelectorAll(".ng-pane");
  function go(name) {
    tabs.forEach(function (t) { t.classList.toggle("on", t.dataset.tab === name); });
    panes.forEach(function (p) { p.hidden = p.dataset.pane !== name; });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  tabs.forEach(function (t) { t.onclick = function () { go(t.dataset.tab); }; });
  root.addEventListener("click", function (e) { var g = e.target.closest("[data-go]"); if (g) go(g.dataset.go); });

  // flashcards
  var box = document.getElementById("ng-cards");
  if (box) {
    var all = JSON.parse(box.dataset.cards || "[]"), queue = all.slice(), known = 0, flipped = false;
    var card = document.createElement("div"); card.className = "fcard"; var face = document.createElement("div"); face.className = "fface"; card.appendChild(face);
    var btns = document.createElement("div"); btns.className = "game-btns";
    var again = document.createElement("button"), got = document.createElement("button"), st = document.createElement("p"); st.className = "muted"; st.style.textAlign = "center";
    again.type = got.type = "button"; again.className = "btn ghost"; got.className = "btn"; again.textContent = "Need practice"; got.textContent = "I know this";
    btns.appendChild(again); btns.appendChild(got); box.append(st, card, btns);
    var show = function () {
      if (!queue.length) { card.hidden = btns.hidden = true; st.textContent = "🎉 You went through all " + all.length + " cards."; return; }
      flipped = false; face.textContent = queue[0][0]; card.classList.remove("back"); st.textContent = known + " / " + all.length + " known · tap the card to flip";
    };
    card.onclick = function () { if (!queue.length) return; flipped = !flipped; face.textContent = queue[0][flipped ? 1 : 0]; card.classList.toggle("back", flipped); };
    got.onclick = function () { queue.shift(); known++; show(); };
    again.onclick = function () { queue.push(queue.shift()); show(); };
    show();
  }

  // only the questions missed last time
  var onlyBtn = document.getElementById("ng-only-missed");
  if (onlyBtn) onlyBtn.onclick = function () {
    var on = onlyBtn.dataset.on !== "1"; onlyBtn.dataset.on = on ? "1" : "";
    root.querySelectorAll(".ng-q").forEach(function (q) { q.hidden = on && !q.classList.contains("missed"); });
    onlyBtn.textContent = on ? "Show all questions" : onlyBtn.dataset.label;
  };
  if (onlyBtn) onlyBtn.dataset.label = onlyBtn.textContent;

  // tutor
  var tut = document.getElementById("ng-tutor");
  if (tut) {
    var body = tut.querySelector(".ng-tutor-b"), tog = document.getElementById("tutor-toggle"), log = document.getElementById("tutor-log"),
        tf = document.getElementById("tutor-form"), ti = document.getElementById("tutor-in"), note = document.getElementById("tutor-note"), hist = [];
    tog.onclick = function () { var open = body.hidden; body.hidden = !open; tog.setAttribute("aria-expanded", open ? "true" : "false"); if (open) ti.focus(); };
    function bubble(text, who) { var b = document.createElement("div"); b.className = "tb " + who; b.textContent = text; log.appendChild(b); log.scrollTop = log.scrollHeight; return b; }
    tf.addEventListener("submit", function (e) {
      e.preventDefault(); var q = ti.value.trim(); if (!q) return; ti.value = ""; bubble(q, "me"); var wait = bubble("Thinking…", "bot wait");
      var fd = new FormData(); fd.append("message", q); fd.append("history", JSON.stringify(hist));
      fetch(tut.dataset.url, { method: "POST", body: fd, headers: { "X-CSRFToken": tf.querySelector("[name=csrfmiddlewaretoken]").value } })
        .then(function (r) { return r.json().then(function (j) { return [r.ok, j]; }); }).then(function (x) {
          wait.classList.remove("wait"); var ok = x[0], j = x[1];
          wait.textContent = ok ? j.answer : (j.error || "Something went wrong.");
          if (ok) { hist.push({ role: "student", text: q }, { role: "tutor", text: j.answer }); note.textContent = (j.source === "ai" ? "AI tutor" : "Lesson search (no AI key set)") + " · " + j.left + " questions left this hour"; }
          log.scrollTop = log.scrollHeight;
        }).catch(function () { wait.classList.remove("wait"); wait.textContent = "Could not reach the tutor. Try again."; });
    });
  }

  // quick check
  var form = document.getElementById("ng-form"), out = document.getElementById("ng-result");
  if (form) form.addEventListener("submit", function (e) {
    e.preventDefault();
    var fd = new FormData(form), btn = document.getElementById("ng-submit"); btn.disabled = true;
    fetch(root.dataset.check, { method: "POST", body: fd, headers: { "X-CSRFToken": form.querySelector("[name=csrfmiddlewaretoken]").value } })
      .then(function (r) { return r.json(); }).then(function (j) {
        form.querySelectorAll(".ng-q").forEach(function (q, i) {
          var r = j.results[i]; if (!r) return;
          q.querySelectorAll(".ng-opt").forEach(function (o, k) { o.classList.toggle("ok", k === r.answer); o.classList.toggle("bad", k === r.picked && !r.ok); o.querySelector("input").disabled = true; });
          var fb = q.querySelector(".ng-fb"); fb.hidden = false; fb.textContent = (r.ok ? "✓ Correct. " : "✗ Not quite. ") + (r.why || ""); fb.className = "ng-fb " + (r.ok ? "ok" : "bad");
        });
        out.hidden = false; out.className = "ng-result " + (j.pass ? "good" : "retry");
        out.innerHTML = "";
        var h = document.createElement("h3"), p = document.createElement("p");
        h.textContent = j.total ? (j.pass ? "🎉 Mastered!" : "Almost there") : "✓ Done";
        p.textContent = j.total ? ("You scored " + j.correct + " / " + j.total + " (" + Math.round(j.pct) + "%). " + (j.pass ? "This nugget is complete." : "You need " + root.dataset.pass + "% — read it again and retry.")) : "Marked as complete.";
        out.append(h, p);
        if (j.xp) { var xp = document.createElement("p"); xp.className = "ng-xp"; xp.textContent = "+" + j.xp + " XP · 🔥 " + j.streak + "-day streak" + (j.event === "mastered" && j.next_review ? " · revision on " + j.next_review : ""); out.appendChild(xp); }
        (j.new_badges || []).forEach(function (b) { var d = document.createElement("div"); d.className = "ng-newbadge"; d.textContent = b.emoji + " New badge: " + b.name + " — " + b.text; out.appendChild(d); });
        if (j.event === "forgot") { var f = document.createElement("p"); f.textContent = "No problem — we will ask again tomorrow."; out.appendChild(f); }
        if (!j.pass && j.total) { var b = document.createElement("a"); b.className = "btn"; b.href = location.href; b.textContent = "Try again"; out.appendChild(b); }
        else { var n = document.createElement("a"); n.className = "btn"; n.href = "/nuggets/"; n.textContent = "Back to my nuggets"; out.appendChild(n); }
        btn.hidden = true; out.scrollIntoView({ behavior: "smooth", block: "center" });
      }).catch(function () { btn.disabled = false; out.hidden = false; out.textContent = "Could not save. Please try again."; });
  });
})();
