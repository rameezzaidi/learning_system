(function () {
  var root = document.getElementById("chat"); if (!root) return;
  var ME = parseInt(root.dataset.me, 10), ACTIVE = root.dataset.active, IS_GROUP = !!root.dataset.group;
  var msgsEl = document.getElementById("msgs");
  var lastId = 0, seenAt = null, lastDay = "", sending = false;
  function csrf() { var m = document.cookie.match(/csrftoken=([^;]+)/); return m ? m[1] : (document.querySelector("[name=csrfmiddlewaretoken]") || {}).value; }
  function esc(t) { var d = document.createElement("div"); d.textContent = t; return d.innerHTML; }
  function linkify(t) { return esc(t).replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>'); }
  function ini(n) { return n; }

  // ---------- message rendering ----------
  function avatarHtml(m) { return m.avatar ? '<span class="avatar sm has-img"><img src="' + esc(m.avatar) + '" alt=""></span>' : '<span class="avatar sm">' + esc(m.initials || "?") + "</span>"; }
  function render(m, pending) {
    var frag = document.createDocumentFragment();
    if (m.day !== lastDay) { lastDay = m.day; var s = document.createElement("div"); s.className = "day-sep"; s.innerHTML = "<span>" + esc(m.day) + "</span>"; frag.appendChild(s); }
    var row = document.createElement("div"); row.className = "msg-row " + (m.mine ? "mine" : "theirs") + (pending ? " pending" : ""); row.dataset.id = m.id || ""; row.dataset.ts = m.ts || "";
    var inner = "";
    if (!m.mine && IS_GROUP) inner += avatarHtml(m);
    inner += '<div class="bub">';
    if (!m.mine && IS_GROUP) inner += '<div class="bub-name">' + esc(m.sender) + "</div>";
    if (m.file) {
      inner += m.is_image ? '<a class="bub-img" href="' + esc(m.file) + '" target="_blank" rel="noopener"><img src="' + esc(m.file) + '" alt="' + esc(m.file_name) + '" loading="lazy"></a>'
        : '<a class="bub-file" href="' + esc(m.file) + '" target="_blank" rel="noopener" download>📎 <span>' + esc(m.file_name) + "</span></a>";
    }
    if (m.body) inner += '<div class="bub-text">' + linkify(m.body) + "</div>";
    inner += '<div class="bub-meta">' + esc(m.at) + (m.mine ? '<i class="tick"></i>' : "") + "</div></div>";
    row.innerHTML = inner; frag.appendChild(row); return frag;
  }
  function atBottom() { return msgsEl.scrollHeight - msgsEl.scrollTop - msgsEl.clientHeight < 90; }
  function toBottom(smooth) { msgsEl.scrollTo({ top: msgsEl.scrollHeight, behavior: smooth ? "smooth" : "auto" }); }
  function append(list, force) {
    var stick = force || atBottom();
    list.forEach(function (m) { if (m.id && msgsEl.querySelector('[data-id="' + m.id + '"]')) return; msgsEl.appendChild(render(m)); if (m.id > lastId) lastId = m.id; });
    if (stick) toBottom(!force);
    updateSeen();
  }
  function updateSeen() {
    if (IS_GROUP) return;
    var rows = msgsEl.querySelectorAll(".msg-row.mine");
    rows.forEach(function (r) {
      var seen = seenAt && r.dataset.ts && new Date(r.dataset.ts) <= new Date(seenAt);
      r.classList.toggle("seen", !!seen);
    });
  }

  if (ACTIVE && msgsEl) {
    var init = JSON.parse(document.getElementById("msgs-data").textContent || "[]");
    if (!init.length) { msgsEl.innerHTML = '<div class="msgs-empty"><b>Say hello 👋</b><span>Your messages appear here.</span></div>'; }
    else append(init, true);
    root.classList.add("ready");
    // seen time for direct chats comes with the poll
    var poll = function () {
      if (document.hidden) return;
      fetch(root.dataset.uMessages + "?after=" + lastId, { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (d) {
        seenAt = d.seen || seenAt;
        if (d.messages.length) { var e = msgsEl.querySelector(".msgs-empty"); if (e) e.remove(); append(d.messages); }
        updateSeen();
      }).catch(function () {});
    };
    poll(); setInterval(poll, 2500);
    document.addEventListener("visibilitychange", function () { if (!document.hidden) poll(); });

    // ---------- composer ----------
    var form = document.getElementById("composer"), body = document.getElementById("body"), fileIn = document.getElementById("fileInput");
    var chip = document.getElementById("fileChip"), fname = document.getElementById("fileName"), sendBtn = document.getElementById("sendBtn");
    function grow() { body.style.height = "auto"; body.style.height = Math.min(body.scrollHeight, 140) + "px"; }
    body.addEventListener("input", grow);
    body.addEventListener("keydown", function (e) { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); } });
    fileIn.addEventListener("change", function () { if (fileIn.files[0]) { fname.textContent = fileIn.files[0].name; chip.hidden = false; } });
    document.getElementById("fileClear").addEventListener("click", function () { fileIn.value = ""; chip.hidden = true; });
    form.addEventListener("submit", function (e) {
      e.preventDefault(); if (sending) return;
      var text = body.value.trim(), f = fileIn.files[0];
      if (!text && !f) return;
      sending = true; sendBtn.disabled = true;
      var fd = new FormData(); fd.append("body", text); if (f) fd.append("file", f);
      var now = new Date(), tmp = { id: 0, mine: true, body: text, file: "", file_name: f ? f.name : "", is_image: false, at: ("0" + now.getHours()).slice(-2) + ":" + ("0" + now.getMinutes()).slice(-2), day: lastDay || "Today", ts: "" };
      var empty = msgsEl.querySelector(".msgs-empty"); if (empty) empty.remove();
      msgsEl.appendChild(render(tmp, true)); var pend = msgsEl.lastElementChild; toBottom(true);
      body.value = ""; grow(); fileIn.value = ""; chip.hidden = true;
      fetch(root.dataset.uSend, { method: "POST", body: fd, credentials: "same-origin", headers: { "X-CSRFToken": csrf() } })
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
        .then(function (res) {
          if (pend && pend.parentNode) pend.remove();
          if (!res.ok) { alert(res.d.error || "Could not send."); body.value = text; grow(); return; }
          append([res.d.message], true);
        }).catch(function () { if (pend && pend.parentNode) pend.classList.add("failed"); })
        .finally(function () { sending = false; sendBtn.disabled = false; body.focus(); });
    });

    // ---------- emoji ----------
    var pop = document.getElementById("emojiPop"), EM = "😀 😁 😂 🤣 😊 😍 😘 😎 🤔 😅 😢 😭 😡 👍 👎 👏 🙏 💪 🎉 🔥 ❤️ 💯 ✅ ❌ ⭐ 📚 ✏️ 📝 🎓 🏆 😴 🤝".split(" ");
    pop.innerHTML = EM.map(function (e) { return '<button type="button">' + e + "</button>"; }).join("");
    document.getElementById("emojiBtn").addEventListener("click", function (e) { e.stopPropagation(); pop.hidden = !pop.hidden; });
    pop.addEventListener("click", function (e) { var b = e.target.closest("button"); if (!b) return; var p = body.selectionStart || body.value.length; body.value = body.value.slice(0, p) + b.textContent + body.value.slice(p); body.focus(); grow(); });
    document.addEventListener("click", function (e) { if (!pop.hidden && !e.target.closest(".emoji-wrap")) pop.hidden = true; });
    if (!matchMedia("(max-width: 900px)").matches) body.focus();
  }

  // ---------- chat list: filter + live refresh ----------
  var items = document.getElementById("chatItems"), filt = document.getElementById("chatFilter");
  if (filt) filt.addEventListener("input", function () { var q = filt.value.toLowerCase(); items.querySelectorAll(".cl-item").forEach(function (a) { a.hidden = q && a.dataset.name.indexOf(q) < 0; }); });
  function refreshList() {
    if (document.hidden) return;
    fetch(root.dataset.uList, { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (d) {
      var total = 0;
      d.conversations.forEach(function (c) {
        var a = items.querySelector('[data-id="' + c.id + '"]'); if (!a) return;
        var un = String(c.id) === String(ACTIVE) ? 0 : c.unread; total += un;
        var b = a.querySelector(".cl-unread"); b.textContent = un; b.hidden = !un; a.classList.toggle("unread", !!un);
        a.querySelector(".cl-prev").textContent = c.preview || "No messages yet"; a.querySelector(".cl-time").textContent = c.time; a.dataset.ts = c.ts;
      });
      var arr = Array.prototype.slice.call(items.querySelectorAll(".cl-item")).sort(function (x, y) { return (new Date(y.dataset.ts || 0)) - (new Date(x.dataset.ts || 0)); });
      arr.forEach(function (a) { items.appendChild(a); });
      var nb = document.querySelector(".chat-badge"); if (nb) { nb.textContent = total; nb.hidden = !total; }
      var known = d.conversations.some(function (c) { return !items.querySelector('[data-id="' + c.id + '"]'); });
      if (known) location.reload();
    }).catch(function () {});
  }
  setInterval(refreshList, 6000);

  // ---------- new chat modal ----------
  var modal = document.getElementById("newModal"), plist = document.getElementById("pList"), psearch = document.getElementById("pSearch");
  var chosen = {}, timer = null, startBtn = document.getElementById("pStart"), grp = document.getElementById("pGroup"), count = document.getElementById("pCount");
  function ids() { return Object.keys(chosen); }
  function sync() { var n = ids().length; startBtn.disabled = !n; grp.hidden = n < 2; count.textContent = n ? n + " selected" + (n > 1 ? " · group chat" : "") : "Select one person for a direct chat, or several for a group."; }
  function loadPeople() {
    fetch(root.dataset.uPeople + "?q=" + encodeURIComponent(psearch.value), { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (d) {
      plist.innerHTML = d.people.length ? "" : '<div class="cl-empty"><span>No one found.</span></div>';
      d.people.forEach(function (p) {
        var l = document.createElement("label"); l.className = "p-item";
        l.innerHTML = '<input type="checkbox" value="' + p.id + '"' + (chosen[p.id] ? " checked" : "") + ">" + (p.avatar ? '<span class="avatar has-img"><img src="' + esc(p.avatar) + '" alt=""></span>' : '<span class="avatar">' + esc(p.initials) + "</span>") + '<div><b>' + esc(p.name) + "</b><small>" + esc(p.role) + "</small></div>";
        l.querySelector("input").addEventListener("change", function (e) { if (e.target.checked) chosen[p.id] = 1; else delete chosen[p.id]; sync(); });
        plist.appendChild(l);
      });
    });
  }
  function open() { modal.hidden = false; document.body.classList.add("modal-open"); chosen = {}; sync(); psearch.value = ""; loadPeople(); setTimeout(function () { psearch.focus(); }, 50); }
  function close() { modal.hidden = true; document.body.classList.remove("modal-open"); }
  ["newChat", "newChat2"].forEach(function (id) { var b = document.getElementById(id); if (b) b.addEventListener("click", open); });
  document.getElementById("mClose").addEventListener("click", close);
  modal.addEventListener("click", function (e) { if (e.target === modal) close(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !modal.hidden) close(); });
  psearch.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(loadPeople, 220); });
  startBtn.addEventListener("click", function () {
    var fd = new FormData(); ids().forEach(function (i) { fd.append("users", i); }); fd.append("title", document.getElementById("pTitle").value);
    startBtn.disabled = true;
    fetch(root.dataset.uNew, { method: "POST", body: fd, credentials: "same-origin", headers: { "X-CSRFToken": csrf() } })
      .then(function (r) { return r.json(); }).then(function (d) { if (d.url) location.href = d.url; else { alert(d.error || "Could not start chat."); startBtn.disabled = false; } });
  });
})();
