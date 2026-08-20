/* Cambridge IELTS 21 v3 renderer.
 *
 * This is intentionally separate from the legacy content/OCR renderer.
 * It consumes only content files with content_schema === ieltsband.content.v3
 * and leaves the existing exam engine, timers, scoring and progress flow in
 * app.js intact.
 */
(function () {
  "use strict";

  const CAMBRIDGE_SCHEMA = "ieltsband.content.v3";
  let originalStartReading = null;
  let originalStartListening = null;
  let originalStartWriting = null;

  async function fetchV3(mockId, testName) {
    try {
      const content = await api(`/api/mocks/${encodeURIComponent(mockId)}/tests/${encodeURIComponent(testName)}/content`);
      return content && content.content_schema === CAMBRIDGE_SCHEMA ? content : null;
    } catch (_) {
      return null;
    }
  }

  const typeLabels = {
    table_completion: "Table completion",
    notes_completion: "Notes completion",
    form_completion: "Form completion",
    sentence_completion: "Sentence completion",
    summary_completion: "Summary completion",
    flow_chart: "Flow-chart completion",
    multiple_choice: "Multiple choice",
    multiple_choice_multiple: "Multiple choice · choose multiple",
    matching: "Matching",
    paragraph_matching: "Matching information to paragraphs",
    true_false_not_given: "TRUE / FALSE / NOT GIVEN",
    yes_no_not_given: "YES / NO / NOT GIVEN",
    diagram_labeling: "Diagram labelling",
    map_labeling: "Map labelling"
  };

  function pageUrl(mockId, page) {
    return `/api/mocks/${encodeURIComponent(mockId)}/page?page=${encodeURIComponent(page)}`;
  }

  function audioUrl(mockId, testName, file) {
    return `/api/mocks/${encodeURIComponent(mockId)}/tests/${encodeURIComponent(testName)}/audio?file=${encodeURIComponent(file)}`;
  }

  function safePageImages(mockId, pages, label) {
    return (pages || []).map(p =>
      `<img class="c21-book-page" src="${pageUrl(mockId, p.pdf_page || p)}" alt="${esc(label || "Cambridge IELTS page")}" loading="lazy">`
    ).join("");
  }

  function renderBlocks(blocks) {
    return (blocks || []).map(block => {
      const text = esc(block.text || "");
      switch (block.type) {
        case "heading": return `<h3 class="c21-heading">${text}</h3>`;
        case "subheading": return `<h4 class="c21-subheading">${text}</h4>`;
        case "bullet": return `<div class="c21-bullet">${text}</div>`;
        case "table": return `<pre class="c21-preserved">${text}</pre>`;
        default: return `<p class="c21-paragraph">${text}</p>`;
      }
    }).join("");
  }

  function answerInputs(range, prefix, mode) {
    const [from, to] = range;
    const out = [];
    for (let q = from; q <= to; q++) {
      out.push(`
        <div class="c21-answer-row">
          <span class="c21-answer-number">${q}</span>
          <input type="text" id="${prefix}-${q}" class="c21-answer-input"
                 autocomplete="off" spellcheck="false"
                 aria-label="Answer for question ${q}"
                 placeholder="${mode === "multiple_choice_multiple" ? "Letters, e.g. A, C" : "Your answer"}">
        </div>`);
    }
    return out.join("");
  }

  function wireAnswerInputs(prefix) {
    document.querySelectorAll(`.c21-answer-input[id^="${prefix}-"]`).forEach(input => {
      input.addEventListener("input", () => {
        const counter = document.getElementById("answeredCount");
        const all = [...document.querySelectorAll(`.c21-answer-input[id^="${prefix}-"]`)];
        const count = all.filter(x => x.value.trim()).length;
        if (counter) counter.textContent = `${count} / ${all.length} answered`;
        if (typeof syncNavAnswered === "function") syncNavAnswered(prefix);
      });
      input.addEventListener("focus", () => {
        if (typeof syncNavCurrent === "function") syncNavCurrent(prefix, input.id.split("-")[1]);
      });
    });
  }

  function c21GroupHtml(mockId, group, prefix) {
    const type = group.question_type || "question_group";
    const range = group.question_range || [1, 1];
    const title = typeLabels[type] || type.replaceAll("_", " ");
    const pages = group.source_pages || [];
    const source = group.raw_text || "";
    const questions = group.questions || [];

    return `
      <section class="c21-question-group" data-from="${range[0]}" data-to="${range[1]}">
        <div class="c21-group-head">
          <div>
            <div class="c21-group-range">Questions ${range[0]}–${range[1]}</div>
            <div class="c21-group-type">${esc(title)}</div>
          </div>
          <button class="c21-page-btn" type="button" data-pages='${esc(JSON.stringify(pages))}'>Book page</button>
        </div>
        <div class="c21-semantic-source">${renderRawText(source)}</div>
        <div class="c21-question-controls">
          ${questions.map(q => `
            <div class="c21-question-ref">
              <span>Question ${q.number}</span>
              <span class="c21-status ${q.text_status === "source_page_bound" ? "bound" : "ready"}">
                ${q.text_status === "source_page_bound" ? "source-page verified" : "text available"}
              </span>
            </div>`).join("")}
          ${answerInputs(range, prefix, type)}
        </div>
        <div class="c21-page-view" hidden></div>
      </section>`;
  }

  function renderRawText(text) {
    const lines = String(text || "").split(/\n+/).map(x => x.trim()).filter(Boolean);
    return lines.map(line => {
      if (/^(A|B|C|D|E|F|G|H)\.?\s+/.test(line)) {
        return `<div class="c21-option"><span class="c21-option-letter">${esc(line[0])}</span><span>${esc(line.slice(1).trim())}</span></div>`;
      }
      if (/^(Questions?|PART|SECTION)\b/i.test(line)) {
        return `<div class="c21-structural-line">${esc(line)}</div>`;
      }
      if (/^(Complete|Choose|Write|Look at|Do the following|Match|Which)\b/i.test(line)) {
        return `<div class="c21-instruction">${esc(line)}</div>`;
      }
      return `<p>${esc(line)}</p>`;
    }).join("");
  }

  function wireBookButtons(container, mockId) {
    container.querySelectorAll(".c21-page-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        let pages = [];
        try { pages = JSON.parse(btn.dataset.pages || "[]"); } catch (_) {}
        const group = btn.closest(".c21-question-group");
        const viewer = group?.querySelector(".c21-page-view");
        if (!viewer) return;
        if (!viewer.hidden) { viewer.hidden = true; btn.textContent = "Book page"; return; }
        viewer.innerHTML = safePageImages(mockId, pages, "Cambridge IELTS 21 source page");
        viewer.hidden = false;
        btn.textContent = "Hide page";
      });
    });
  }

  function c21GroupsForSection(section, prefixLabel) {
    const groups = [];
    const items = section?.parts || section?.passages || [];
    items.forEach(item => {
      (item.question_groups || []).forEach(group => {
        const r = group.question_range;
        groups.push({
          label: `${prefixLabel} ${item.number || ""}`.trim(),
          from: r[0], to: r[1]
        });
      });
    });
    return groups;
  }

  function uniqueRanges(groups) {
    const seen = new Set();
    return groups.filter(g => {
      const key = `${g.from}-${g.to}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  async function startReadingV3(mockId, testName) {
    const content = await fetchV3(mockId, testName);
    if (!content) return originalStartReading(mockId, testName);

    loading("Preparing Cambridge 21 reading…");
    const cfg = await api(`/api/mocks/${encodeURIComponent(mockId)}/tests/${encodeURIComponent(testName)}`);
    const rcfg = cfg.reading;
    const section = content.sections.find(s => s.type === "reading");
    if (!section || !rcfg) return originalStartReading(mockId, testName);

    const totalSeconds = (section.duration_minutes || rcfg.duration_minutes || 60) * 60;
    const attempt = await api("/api/attempts/start", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mock_id: mockId, test_name: testName, section: "reading", time_allowed_seconds: totalSeconds })
    });

    const groups = uniqueRanges(c21GroupsForSection(section, "Passage"));
    const passagesHtml = section.passages.map(p => `
      <section class="c21-passage">
        <header class="c21-passage-head">
          <span>Reading Passage ${p.number}</span>
          <strong>${esc(p.title || "")}</strong>
        </header>
        <div class="c21-passage-body">
          ${p.body_pages.map(page => `
            <article class="c21-page-text">
              ${renderBlocks(page.blocks || [{ type: "paragraph", text: page.text || "" }])}
            </article>`).join("")}
        </div>
        <div class="c21-question-groups">
          ${(p.question_groups || []).map(g => c21GroupHtml(mockId, g, "c21r")).join("")}
        </div>
      </section>`).join("");

    app.innerHTML = `${examBarHtml("Reading · Cambridge 21", { mockId })}
      <div class="c21-exam-shell">
        <div class="c21-main-column">${passagesHtml}</div>
        <aside class="c21-answer-column">
          <h3>Answer sheet</h3>
          <p class="c21-answer-note">Use the question group on the left as the source of truth. Some layouts are preserved as source-page text because scanned tables/forms cannot safely be flattened.</p>
          ${answerSheetHtml(groups, "c21r")}
          <button class="btn btn-primary" id="submitBtn">Submit reading</button>
        </aside>
      </div>
      ${navBarHtml(groups, "c21r")}`;

    examInProgress = true;
    window._navPrefix = "c21r";
    document.body.classList.add("has-exam-navbar");
    wireAnswerInputs("c21r");
    wireBookButtons(app, mockId);
    syncNavAnswered("c21r");
    document.getElementById("answeredCount").textContent = `0 / ${groups.reduce((n, g) => n + g.to - g.from + 1, 0)} answered`;

    const doSubmit = auto => submitSection({
      attemptId: attempt.attempt_id, mockId, testName,
      section: "reading", prefix: "c21r", label: "Reading", auto, groups
    });
    document.getElementById("submitBtn").addEventListener("click", () => {
      const left = unansweredCount("c21r");
      if (left > 0) {
        confirmModal({
          title: "Submit with blanks?",
          body: `${left} question${left === 1 ? " is" : "s are"} still unanswered. Blank answers are marked wrong.`,
          confirmLabel: "Submit anyway",
          onConfirm: () => doSubmit(false)
        });
      } else doSubmit(false);
    });
    startTimer(totalSeconds, r => tickTimer(r, 300), () => doSubmit(true));
  }

  async function startListeningV3(mockId, testName) {
    const content = await fetchV3(mockId, testName);
    if (!content) return originalStartListening(mockId, testName);

    loading("Preparing Cambridge 21 listening…");
    const cfg = await api(`/api/mocks/${encodeURIComponent(mockId)}/tests/${encodeURIComponent(testName)}`);
    const lcfg = cfg.listening;
    const section = content.sections.find(s => s.type === "listening");
    if (!section || !lcfg) return originalStartListening(mockId, testName);

    const totalSeconds = (section.duration_minutes || lcfg.duration_minutes || 40) * 60;
    const attempt = await api("/api/attempts/start", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mock_id: mockId, test_name: testName, section: "listening", time_allowed_seconds: totalSeconds })
    });

    const groups = uniqueRanges(c21GroupsForSection(section, "Part"));
    const partsHtml = section.parts.map((part, i) => {
      const oldPart = lcfg.parts[i] || {};
      const files = oldPart.files || (oldPart.file ? [oldPart.file] : []);
      return `<section class="c21-listening-part">
        <div class="c21-listening-head">
          <div><span>Part ${part.number}</span><strong>${esc(part.title || "")}</strong></div>
          <button class="btn btn-primary c21-play" data-files='${esc(JSON.stringify(files))}' data-index="${i}">▶ Play once</button>
        </div>
        <div class="c21-audio-status" id="c21-audio-${i}">Not started</div>
        ${(part.question_groups || []).map(g => c21GroupHtml(mockId, g, "c21l")).join("")}
      </section>`;
    }).join("");

    app.innerHTML = `${examBarHtml("Listening · Cambridge 21", { mockId })}
      <div class="c21-exam-shell">
        <div class="c21-main-column">${partsHtml}</div>
        <aside class="c21-answer-column">
          <h3>Answer sheet</h3>
          <p class="c21-answer-note">The recording is controlled separately from the question sheet. Start each part once, as in the exam.</p>
          ${answerSheetHtml(groups, "c21l")}
          <button class="btn btn-primary" id="submitBtn">Submit listening</button>
        </aside>
      </div>
      ${navBarHtml(groups, "c21l")}`;

    examInProgress = true;
    window._navPrefix = "c21l";
    document.body.classList.add("has-exam-navbar");
    wireAnswerInputs("c21l");
    wireBookButtons(app, mockId);
    syncNavAnswered("c21l");
    document.getElementById("answeredCount").textContent = `0 / ${groups.reduce((n, g) => n + g.to - g.from + 1, 0)} answered`;

    document.querySelectorAll(".c21-play").forEach(btn => {
      btn.addEventListener("click", () => {
        stopActiveListeningAudio();
        const files = JSON.parse(btn.dataset.files || "[]");
        const idx = Number(btn.dataset.index);
        const status = document.getElementById(`c21-audio-${idx}`);
        btn.disabled = true;
        btn.textContent = "Playing…";
        const audio = new Audio();
        activeListeningAudio = audio;
        activeListeningReset = () => {
          btn.disabled = false;
          btn.textContent = "▶ Play once";
          status.textContent = "Stopped";
        };
        let pos = 0;
        const next = () => {
          if (pos >= files.length) {
            status.textContent = "Finished";
            btn.textContent = "✓ Played";
            activeListeningAudio = null;
            activeListeningReset = null;
            return;
          }
          const file = files[pos++];
          audio.src = audioUrl(mockId, testName, file);
          status.textContent = `Playing ${pos}/${files.length}`;
          audio.play().catch(() => { status.textContent = "Playback was blocked by the browser. Press Play again."; });
        };
        audio.addEventListener("ended", next);
        audio.addEventListener("timeupdate", () => {
          if (audio.duration) status.textContent = `Playing · ${fmtTime(Math.floor(audio.currentTime))} / ${fmtTime(Math.floor(audio.duration))}`;
        });
        audio.addEventListener("pause", () => {
          if (!audio.ended && activeListeningAudio === audio) audio.play().catch(() => {});
        });
        next();
      });
    });

    const doSubmit = auto => submitSection({
      attemptId: attempt.attempt_id, mockId, testName,
      section: "listening", prefix: "c21l", label: "Listening", auto, groups
    });
    document.getElementById("submitBtn").addEventListener("click", () => {
      const left = unansweredCount("c21l");
      if (left > 0) {
        confirmModal({
          title: "Submit with blanks?",
          body: `${left} question${left === 1 ? " is" : "s are"} still unanswered. Blank answers are marked wrong.`,
          confirmLabel: "Submit anyway",
          onConfirm: () => doSubmit(false)
        });
      } else doSubmit(false);
    });
    startTimer(totalSeconds, r => tickTimer(r, 300), () => doSubmit(true));
  }

  async function startWritingV3(mockId, testName) {
    const content = await fetchV3(mockId, testName);
    if (!content) return originalStartWriting(mockId, testName);

    const section = content.sections.find(s => s.type === "writing");
    if (!section) return originalStartWriting(mockId, testName);

    const tasks = section.tasks || [];
    let index = 0;
    const runTask = async () => {
      const task = tasks[index];
      if (!task) return renderMockTests(mockId);
      loading(`Preparing Cambridge 21 Writing Task ${task.task_number}…`);
      const cfg = await api(`/api/mocks/${encodeURIComponent(mockId)}/tests/${encodeURIComponent(testName)}`);
      const key = task.task_number === 1 ? "task1" : "task2";
      const taskCfg = cfg.writing?.[key] || { duration_minutes: task.task_number === 1 ? 20 : 40 };
      const totalSeconds = taskCfg.duration_minutes * 60;
      const attempt = await api("/api/attempts/start", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mock_id: mockId, test_name: testName, section: "writing", time_allowed_seconds: totalSeconds })
      });

      const page = task.page;
      app.innerHTML = `${examBarHtml(`Writing · Task ${task.task_number} · Cambridge 21`, { mockId })}
        <div class="c21-writing-shell">
          <div class="c21-writing-prompt">
            ${renderBlocks(page.blocks || [{ type: "paragraph", text: page.text || "" }])}
            ${page.visual_fallback ? `<div class="c21-visual-fallback">${safePageImages(mockId, task.source_pages, "Writing task source page")}</div>` : ""}
          </div>
          <div class="c21-writing-response">
            <h3>Your response</h3>
            <textarea id="essayBox" class="c21-essay" placeholder="Write your response here…"></textarea>
            <div id="wc" class="c21-word-count">0 words</div>
            <button class="btn btn-primary" id="submitBtn">Submit Task ${task.task_number}</button>
          </div>
        </div>`;

      examInProgress = true;
      const box = document.getElementById("essayBox");
      box.addEventListener("input", () => {
        const words = box.value.trim().split(/\s+/).filter(Boolean).length;
        document.getElementById("wc").textContent = `${words} words`;
      });

      const finish = async auto => {
        clearTimer(); examInProgress = false;
        const essay = box.value;
        loading("Submitting your response…");
        await api(`/api/attempts/${attempt.attempt_id}/submit`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mock_id: mockId, test_name: testName, section: "writing", answers: { essay }, auto_submitted: auto })
        });
        loading("Getting examiner feedback on your writing…");
        let feedback;
        try {
          feedback = await api("/api/writing/feedback", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ task_type: key, prompt_description: `Cambridge IELTS 21 ${testName} Writing Task ${task.task_number}`, essay_text: essay })
          });
        } catch (err) { feedback = { error: err.message }; }
        app.innerHTML = `<div class="results-box results-wide">
          <h2>Writing Task ${task.task_number} submitted${auto ? " <span class='auto-note'>(time expired)</span>" : ""}</h2>
          ${feedback.error ? `<p class="feedback-text">Feedback isn't available: ${esc(feedback.error)}</p>` : `
            <div class="score-line"><span class="band-chip">Band ${esc(String(feedback.overall_band))}</span></div>
            ${bandRibbonHtml(feedback.overall_band)}
            <div class="criteria-grid">
              <div class="criterion"><div class="label">Task achievement</div><div class="value">${esc(String(feedback.task_achievement))}</div></div>
              <div class="criterion"><div class="label">Coherence &amp; cohesion</div><div class="value">${esc(String(feedback.coherence_cohesion))}</div></div>
              <div class="criterion"><div class="label">Lexical resource</div><div class="value">${esc(String(feedback.lexical_resource))}</div></div>
              <div class="criterion"><div class="label">Grammar accuracy</div><div class="value">${esc(String(feedback.grammar_accuracy))}</div></div>
            </div>
            <p class="feedback-text">${esc(feedback.feedback)}</p>`}
          <div class="submit-area"><button class="btn btn-primary" id="writingContinue">${index + 1 < tasks.length ? "Continue to Task 2" : "Back to tests"}</button></div>
        </div>`;
        document.getElementById("writingContinue").addEventListener("click", () => { index += 1; runTask(); });
      };

      document.getElementById("submitBtn").addEventListener("click", () => {
        const words = box.value.trim().split(/\s+/).filter(Boolean).length;
        const min = task.task_number === 1 ? 150 : 250;
        if (words < min) {
          confirmModal({
            title: "Under the word minimum",
            body: `You've written ${words} words; the task expects at least ${min}. Submit anyway?`,
            confirmLabel: "Submit anyway",
            onConfirm: () => finish(false)
          });
        } else finish(false);
      });
      startTimer(totalSeconds, r => tickTimer(r, 120), () => finish(true));
    };
    runTask();
  }

  function install() {
    originalStartReading = routes.startReading;
    originalStartListening = routes.startListening;
    originalStartWriting = routes.startWriting;
    routes.startReading = d => startReadingV3(d.mock, d.test);
    routes.startListening = d => startListeningV3(d.mock, d.test);
    routes.startWriting = d => startWritingV3(d.mock, d.test);
  }

  install();
})();
