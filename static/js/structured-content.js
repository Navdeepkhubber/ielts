/* IELTSBand structured-content v2 renderer. Loaded after app.js. */
(function () {
  "use strict";

  function esc2(value) {
    return String(value == null ? "" : value).replace(/[&<>\"']/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
    });
  }

  async function contentV2(mockId, testName) {
    try {
      var data = await api(`/api/mocks/${encodeURIComponent(mockId)}/tests/${encodeURIComponent(testName)}/content`);
      return data && data.schema_version === 2 ? data : null;
    } catch (_) { return null; }
  }

  function sectionOf(content, type) {
    return (content && content.sections || []).find(function (s) { return s.type === type; }) || null;
  }

  function pageImage(mockId, page, alt) {
    return `<img class="structured-page-image" src="/api/mocks/${encodeURIComponent(mockId)}/page?page=${page}" alt="${esc2(alt || `Book page ${page}`)}" loading="lazy">`;
  }

  function inlineGaps(text, prefix, from, to) {
    return esc2(text).replace(/\b(\d{1,2})\s*(?:[.…·]{3,}|_{3,})/g, function (match, n) {
      var q = Number(n);
      if (q < from || q > to) return match;
      return `<span class="inline-q"><span class="inline-qnum">${q}</span><input class="inline-input" data-inline-q="${q}" data-prefix="${prefix}" autocomplete="off" spellcheck="false" aria-label="Answer for question ${q}"></span>`;
    });
  }

  function renderBlock(block, prefix, range) {
    var body = inlineGaps(block.text || "", prefix, range[0], range[1]);
    switch (block.type) {
      case "heading": return `<h4 class="structured-heading">${body}</h4>`;
      case "question_group_heading": return `<h5 class="structured-q-heading">${body}</h5>`;
      case "instruction": return `<div class="structured-instruction">${body}</div>`;
      case "option": return `<div class="structured-option">${body}</div>`;
      case "bullet": return `<div class="structured-bullet">${body}</div>`;
      case "question_line": return `<div class="structured-question-line">${body}</div>`;
      default: return `<p class="structured-paragraph">${body}</p>`;
    }
  }

  function renderPages(mockId, pages, prefix, range) {
    var text = (pages || []).map(function (page) {
      return `<article class="structured-page-text" data-pdf-page="${page.pdf_page}">${(page.blocks || []).map(function (b) { return renderBlock(b, prefix, range); }).join("")}</article>`;
    }).join("");
    var images = (pages || []).map(function (page) { return pageImage(mockId, page.pdf_page, `Book page ${page.pdf_page}`); }).join("");
    return `<div class="structured-text-view">${text}</div><div class="structured-book-view">${images}</div>`;
  }

  function viewToggle2() {
    return `<div class="view-toggle structured-view-toggle"><button class="vt-btn active" data-structured-view="text">Text</button><button class="vt-btn" data-structured-view="book">Book view</button></div>`;
  }

  function wireStructuredToggle(container) {
    var tabs = container.querySelector(".structured-view-toggle");
    if (!tabs) return;
    tabs.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-structured-view]");
      if (!btn) return;
      var mode = btn.dataset.structuredView;
      tabs.querySelectorAll(".vt-btn").forEach(function (b) { b.classList.toggle("active", b === btn); });
      container.querySelectorAll(".structured-text-view").forEach(function (el) { el.style.display = mode === "text" ? "" : "none"; });
      container.querySelectorAll(".structured-book-view").forEach(function (el) { el.style.display = mode === "book" ? "" : "none"; });
    });
  }

  function wireStructuredInline(container) {
    container.querySelectorAll(".inline-input").forEach(function (inp) {
      var q = inp.dataset.inlineQ, prefix = inp.dataset.prefix;
      var sheet = document.getElementById(`${prefix}-${q}`);
      if (!sheet) return;
      inp.addEventListener("input", function () { sheet.value = inp.value; sheet.dispatchEvent(new Event("input")); });
      sheet.addEventListener("input", function () { if (document.activeElement !== inp) inp.value = sheet.value; });
      inp.addEventListener("focus", function () { syncNavCurrent(prefix, q); });
    });
  }

  function groupsFor(items) {
    return (items || []).map(function (item, i) {
      var r = item.question_range || [1, 10];
      return { label: `Passage ${item.number || i + 1}`, from: r[0], to: r[1] };
    });
  }

  async function startReadingV2(mockId, testName) {
    loading("Preparing reading section…");
    var cfg = await api(`/api/mocks/${encodeURIComponent(mockId)}/tests/${encodeURIComponent(testName)}`);
    var rcfg = cfg.reading;
    if (!rcfg) return startReading(mockId, testName);

    /* Check content before creating an attempt, so old v1 mocks fall back
       without creating a second attempt. */
    var content = await contentV2(mockId, testName);
    var section = sectionOf(content, "reading");
    if (!section) return startReading(mockId, testName);

    var totalSeconds = rcfg.duration_minutes * 60;
    var attempt = await api("/api/attempts/start", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mock_id: mockId, test_name: testName, section: "reading", time_allowed_seconds: totalSeconds })
    });

    var groups = groupsFor(section.passages);
    var material = section.passages.map(function (p, i) {
      var range = p.question_range || [groups[i].from, groups[i].to];
      var pages = (p.body_pages || []).concat(p.question_pages || []);
      return `<section class="structured-passage"><div class="structured-passage-head"><span>Reading Passage ${p.number || i + 1}</span><span class="structured-type">${esc2((p.question_types || []).join(" · "))}</span></div>${renderPages(mockId, pages, "ans", range)}</section>`;
    }).join("");

    app.innerHTML = `${examBarHtml("Reading", { mockId })}${viewToggle2()}<div class="exam-shell structured-exam-shell"><div class="exam-material">${material}</div><div class="exam-answers"><h3>Answer sheet</h3>${answerSheetHtml(groups, "ans")}<div class="submit-area"><button class="btn btn-primary" id="submitBtn">Submit reading</button></div></div></div>${navBarHtml(groups, "ans")}`;
    examInProgress = true;
    window._navPrefix = "ans";
    document.body.classList.add("has-exam-navbar");
    wireAnswerSheet(app);
    wireStructuredInline(app);
    wireStructuredToggle(app);
    syncNavAnswered("ans");
    document.getElementById("answeredCount").textContent = `0 / ${groups.reduce(function (n, g) { return n + g.to - g.from + 1; }, 0)} answered`;

    var doSubmit = function (auto) { submitSection({ attemptId: attempt.attempt_id, mockId: mockId, testName: testName, section: "reading", prefix: "ans", label: "Reading", auto: auto, groups: groups }); };
    document.getElementById("submitBtn").addEventListener("click", function () {
      var left = unansweredCount("ans");
      if (left > 0) confirmModal({ title: "Submit with blanks?", body: `${left} question${left === 1 ? " is" : "s are"} still unanswered. Blank answers are marked wrong.`, confirmLabel: "Submit anyway", onConfirm: function () { doSubmit(false); } });
      else doSubmit(false);
    });
    startTimer(totalSeconds, function (r) { tickTimer(r, 300); }, function () { doSubmit(true); });
  }

  routes.startReading = function (d) { startReadingV2(d.mock, d.test); };
  routes.startListening = function (d) { startListening(d.mock, d.test); };
})();
