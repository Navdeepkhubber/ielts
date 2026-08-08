/* IELTS Practice Portal — front-end
   Views: home (mock library) -> mock (tests) -> exam (reading/listening/writing) -> results
   All state flows through `go()` actions; no inline onclick strings, so mock/test
   names with quotes, apostrophes, or unicode are safe. */

const app = document.getElementById("app");
const modalRoot = document.getElementById("modal-root");
let timerInterval = null;

/* ---------------- utilities ---------------- */

function esc(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[c]);
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.headers.get("content-type")?.includes("json") ? res.json() : res;
}

function loading(label) {
  document.body.classList.remove("has-exam-navbar");
  app.innerHTML = `<div class="loading"><div class="spinner"></div><span>${esc(label)}</span></div>`;
}

function toast(msg) {
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

function clearTimer() {
  if (timerInterval) clearInterval(timerInterval);
  timerInterval = null;
}

function startTimer(totalSeconds, onTick, onExpire) {
  clearTimer();
  let remaining = totalSeconds;
  onTick(remaining);
  timerInterval = setInterval(() => {
    remaining -= 1;
    onTick(remaining);
    if (remaining <= 0) { clearTimer(); onExpire(); }
  }, 1000);
}

function fmtTime(sec) {
  sec = Math.max(0, sec);
  const m = Math.floor(sec / 60).toString().padStart(2, "0");
  const s = (sec % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

function confirmModal({ title, body, confirmLabel, onConfirm }) {
  modalRoot.innerHTML = `
    <div class="modal-overlay" data-close="1">
      <div class="modal" role="dialog" aria-modal="true">
        <h3>${esc(title)}</h3>
        <p>${esc(body)}</p>
        <div class="modal-actions">
          <button class="btn btn-ghost" data-close="1">Keep working</button>
          <button class="btn btn-primary" data-confirm="1">${esc(confirmLabel)}</button>
        </div>
      </div>
    </div>`;
  modalRoot.querySelector(".modal-overlay").addEventListener("click", e => {
    if (e.target.dataset.close) modalRoot.innerHTML = "";
    if (e.target.dataset.confirm) { modalRoot.innerHTML = ""; onConfirm(); }
  });
}

function infoModal({ title, bodyHtml }) {
  modalRoot.innerHTML = `
    <div class="modal-overlay" data-close="1">
      <div class="modal modal-wide" role="dialog" aria-modal="true">
        <div class="modal-head">
          <h3>${esc(title)}</h3>
          <button class="modal-x" data-close="1" aria-label="Close">&times;</button>
        </div>
        ${bodyHtml}
      </div>
    </div>`;
  modalRoot.querySelector(".modal-overlay").addEventListener("click", e => {
    if (e.target.dataset.close) modalRoot.innerHTML = "";
  });
}

async function showBandExplanation(attemptId) {
  if (!attemptId) return;
  let info;
  try {
    info = await api(`/api/attempts/${attemptId}/band-explanation`);
  } catch {
    return; // no score recorded yet -- nothing to explain
  }
  const rows = info.table.map(row => `
    <tr class="${row.threshold === info.matched_threshold ? 'matched-row' : ''}">
      <td>${row.threshold}+ correct</td>
      <td>Band ${row.band}</td>
      ${row.threshold === info.matched_threshold ? '<td class="match-tag">← your score</td>' : '<td></td>'}
    </tr>`).join("");
  const scaleNote = info.was_scaled
    ? `<p class="band-calc-note">Your score was ${info.correct_count}/${info.total}, scaled to a
       40-question equivalent: <strong>${info.scaled_score}/40</strong>.</p>`
    : `<p class="band-calc-note">Your score: <strong>${info.correct_count}/${info.total}</strong>.</p>`;
  infoModal({
    title: `How Band ${info.band} was calculated`,
    bodyHtml: `
      <div class="band-calc-body">
        ${scaleNote}
        <p class="band-calc-note">Matched against the <strong>${esc(info.table_name)}</strong> table
        (the standard published approximation — IELTS doesn't release an official conversion,
        so treat this as a close estimate, not a certified score):</p>
        <table class="band-calc-table">
          <tr><th>Threshold</th><th>Band</th><th></th></tr>
          ${rows}
        </table>
      </div>`
  });
}

/* ---------------- navigation (event delegation) ---------------- */

const routes = {};
function go(action, payload) { routes[action](payload); }

document.addEventListener("click", e => {
  const el = e.target.closest("[data-action]");
  if (!el || el.disabled) return;
  const action = el.dataset.action;
  if (routes[action]) routes[action](el.dataset);
});

let examInProgress = false; // set while a timed section is running
let activeListeningAudio = null;  // the single Audio object currently playing, if any
let activeListeningReset = null;  // resets the UI of whichever button's audio just got force-stopped

function stopActiveListeningAudio() {
  if (activeListeningAudio) {
    activeListeningAudio.pause();
    activeListeningAudio = null;
  }
  if (activeListeningReset) {
    activeListeningReset();
    activeListeningReset = null;
  }
}
window.addEventListener("beforeunload", stopActiveListeningAudio);
window.addEventListener("pagehide", stopActiveListeningAudio);

function navigateTo(view) {
  const doNav = () => {
    examInProgress = false;
    stopActiveListeningAudio();
    document.querySelectorAll(".topnav .nav-link").forEach(b =>
      b.classList.toggle("active", b.dataset.view === view));
    if (view === "home") renderHome();
    if (view === "dashboard") renderDashboard();
  };
  if (examInProgress) {
    confirmModal({
      title: "Leave the test?",
      body: "Your answers for this section will be lost and the attempt won't be scored.",
      confirmLabel: "Leave test",
      onConfirm: doNav,
    });
  } else doNav();
}

document.querySelectorAll(".topnav .nav-link").forEach(btn => {
  btn.addEventListener("click", () => navigateTo(btn.dataset.view));
});
document.querySelector(".wordmark").addEventListener("click", () => navigateTo("home"));
document.querySelector(".wordmark").style.cursor = "pointer";

/* ---------------- HOME: mock library ---------------- */

async function renderHome() {
  clearTimer();
  loading("Loading your mock tests…");
  let mocks;
  try { mocks = await api("/api/mocks"); }
  catch (err) { app.innerHTML = `<div class="empty-state"><h3>Couldn't load tests</h3><p>${esc(err.message)}</p></div>`; return; }

  if (mocks.length === 0) {
    app.innerHTML = `
      <div class="page-head"><h2>Mock tests</h2></div>
      <div class="empty-state">
        <h3>No mock tests yet</h3>
        <p>Drop a mock folder into <code>tests/</code> — a PDF plus an <code>audio/Test&nbsp;N/</code> folder —<br>
        then restart the app. Everything else is generated for you.</p>
      </div>`;
    return;
  }

  app.innerHTML = `
    <div class="page-head">
      <h2>Mock tests</h2>
      <p class="sub">${mocks.length} book${mocks.length === 1 ? "" : "s"} in your library. Pick one to begin.</p>
    </div>
    <div class="mock-grid">
      ${mocks.map(m => {
        const tests = Object.entries(m.tests);
        const has = k => tests.some(([, cfg]) => cfg[`has_${k}`]);
        return `
        <button class="mock-card" data-action="openMock" data-mock="${esc(m.id)}">
          <h3>${esc(m.mock_name)}</h3>
          <span class="meta">${tests.length} test${tests.length === 1 ? "" : "s"}</span>
          <span class="chips">
            <span class="chip ${has("listening") ? "on" : ""}">Listening</span>
            <span class="chip ${has("reading") ? "on" : ""}">Reading</span>
            <span class="chip ${has("writing") ? "on" : ""}">Writing</span>
          </span>
        </button>`;
      }).join("")}
    </div>`;
}
routes.openMock = d => renderMockTests(d.mock);
routes.showBand = d => showBandExplanation(d.attempt);
routes.enterScore = d => {
  const total = Number(d.total);
  infoModal({
    title: "Enter your score",
    bodyHtml: `<div class="band-calc-body">${manualScoreFormHtml(total)}</div>`,
  });
  wireManualScoreForm(modalRoot, d.attempt, total, () => {
    modalRoot.innerHTML = "";
    renderDashboard();
  });
};

/* ---------------- MOCK: tests within ---------------- */

async function renderMockTests(mockId) {
  clearTimer();
  loading("Opening mock…");
  const mock = await api(`/api/mocks/${encodeURIComponent(mockId)}`);
  const tests = Object.entries(mock.tests);

  app.innerHTML = `
    <button class="back-link" data-action="goHome">&larr; All mocks</button>
    <div class="page-head">
      <h2>${esc(mock.mock_name)}</h2>
      <p class="sub">Choose a section to sit under timed, exam-day conditions.</p>
    </div>
    ${tests.map(([name, cfg]) => `
      <div class="test-row">
        <h3>${esc(name)}</h3>
        <div class="section-buttons">
          <button class="btn ${cfg.listening ? "btn-primary" : ""}" ${cfg.listening ? "" : "disabled title='Not configured in manifest.json yet'"}
                  data-action="startListening" data-mock="${esc(mockId)}" data-test="${esc(name)}">Listening</button>
          <button class="btn ${cfg.reading ? "btn-primary" : ""}" ${cfg.reading ? "" : "disabled title='Not configured in manifest.json yet'"}
                  data-action="startReading" data-mock="${esc(mockId)}" data-test="${esc(name)}">Reading</button>
          <button class="btn ${cfg.writing ? "btn-primary" : ""}" ${cfg.writing ? "" : "disabled title='Not configured in manifest.json yet'"}
                  data-action="startWriting" data-mock="${esc(mockId)}" data-test="${esc(name)}">Writing</button>
        </div>
      </div>`).join("")}
  `;
}
routes.goHome = () => renderHome();
routes.startListening = d => startListening(d.mock, d.test);
routes.startReading = d => startReading(d.mock, d.test);
routes.startWriting = d => startWriting(d.mock, d.test);

/* ---------------- shared exam pieces ---------------- */

function answerSheetHtml(groups, prefix) {
  // groups: [{label, from, to}] -- renders each part/passage as its own
  // block with a header, like a real IELTS answer sheet.
  return groups.map(g => {
    const qs = [];
    for (let q = g.from; q <= g.to; q++) qs.push(q);
    return `
      <div class="sheet-group">
        <div class="sheet-group-head">${esc(g.label)} <span class="sheet-group-range">Questions ${g.from}–${g.to}</span></div>
        <div class="answer-sheet">
          ${qs.map(q => `
            <div class="sheet-cell" id="cell-${q}">
              <span class="num">${q}</span>
              <input type="text" id="${prefix}-${q}" data-q="${q}" autocomplete="off" spellcheck="false" aria-label="Answer for question ${q}">
            </div>`).join("")}
        </div>
      </div>`;
  }).join("");
}

function wireAnswerSheet(container) {
  const inputs = [...container.querySelectorAll(".sheet-cell input")];

  const refresh = () => {
    const counter = document.getElementById("answeredCount");
    if (counter) {
      const done = inputs.filter(i => i.value.trim() !== "").length;
      counter.textContent = `${done} / ${inputs.length} answered`;
    }
    if (inputs.length) syncNavAnswered(inputs[0].id.split("-")[0]);
  };

  inputs.forEach((inp, idx) => {
    inp.addEventListener("input", refresh);
    inp.addEventListener("focus", () => {
      const [prefix, q] = inp.id.split("-");
      syncNavCurrent(prefix, q);
    });
    inp.addEventListener("keydown", e => {
      if (e.key === "Enter" && inputs[idx + 1]) { e.preventDefault(); inputs[idx + 1].focus(); }
    });
  });
}

function collectAnswers(prefix) {
  const answers = {};
  document.querySelectorAll(`[id^="${prefix}-"]`).forEach(el => {
    answers[el.id.split("-")[1]] = el.value;
  });
  return answers;
}

function unansweredCount(prefix) {
  return [...document.querySelectorAll(`[id^="${prefix}-"]`)].filter(el => el.value.trim() === "").length;
}

function examBarHtml(sectionName, { mockId } = {}) {
  return `
    <div class="exam-bar">
      <div class="exam-bar-left">
        <button class="btn-exit" data-action="exitExam" data-mock="${esc(mockId || "")}" title="Exit this test">&larr; Exit</button>
        <span class="exam-bar-divider"></span>
        <span class="exam-bar-brand">IELTS</span>
        <span class="exam-bar-section">${esc(sectionName)}</span>
      </div>
      <div class="exam-bar-right">
        <span class="answered-count" id="answeredCount"></span>
        <div class="settings-wrap">
          <button class="exam-tool-btn" data-action="toggleSettings" id="settingsBtn" aria-haspopup="true" aria-label="Settings">
            <svg viewBox="0 0 20 20" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="10" cy="10" r="2.6"/><path d="M10 2.5v2M10 15.5v2M17.5 10h-2M4.5 10h-2M15.4 4.6l-1.4 1.4M6 12.6l-1.4 1.4M15.4 15.4l-1.4-1.4M6 7.4 4.6 6"/></svg>
            Settings
          </button>
          <div class="settings-panel" id="settingsPanel" hidden>
            <div class="settings-row">
              <span>Text size</span>
              <div class="settings-btns">
                <button data-action="setFontScale" data-scale="md" class="active" aria-label="Normal text size">A</button>
                <button data-action="setFontScale" data-scale="lg" aria-label="Large text size">A</button>
                <button data-action="setFontScale" data-scale="xl" aria-label="Extra large text size">A</button>
              </div>
            </div>
            <div class="settings-row">
              <span>High contrast</span>
              <button class="settings-toggle" data-action="toggleContrast" id="contrastToggle">Off</button>
            </div>
          </div>
        </div>
        <button class="exam-tool-btn" data-action="toggleHide" id="hideBtn">Hide</button>
        <div class="exam-timer-box" id="timerPill">
          <span class="exam-timer-label">Time remaining</span>
          <span class="exam-timer-value" id="timerValue">--:--</span>
        </div>
      </div>
    </div>`;
}
routes.exitExam = d => {
  confirmModal({
    title: "Exit this test?",
    body: "Your answers for this section will be lost and the attempt won't be scored.",
    confirmLabel: "Exit test",
    onConfirm: () => { examInProgress = false; stopActiveListeningAudio(); clearTimer(); d.mock ? renderMockTests(d.mock) : renderHome(); },
  });
};
routes.toggleSettings = () => {
  const p = document.getElementById("settingsPanel");
  if (p) p.hidden = !p.hidden;
};
routes.setFontScale = d => {
  const shell = document.querySelector(".exam-shell");
  if (shell) {
    shell.classList.remove("text-lg", "text-xl");
    if (d.scale !== "md") shell.classList.add(`text-${d.scale}`);
  }
  document.querySelectorAll(".settings-btns button").forEach(b => b.classList.toggle("active", b.dataset.scale === d.scale));
};
routes.toggleHide = () => {
  const shell = document.querySelector(".exam-shell");
  const btn = document.getElementById("hideBtn");
  if (!shell || !btn) return;
  const hidden = shell.classList.toggle("is-hidden");
  btn.textContent = hidden ? "Resume test" : "Hide";
};
routes.toggleContrast = () => {
  const on = document.body.classList.toggle("high-contrast");
  const btn = document.getElementById("contrastToggle");
  if (btn) btn.textContent = on ? "On" : "Off";
};
routes.jumpTo = d => {
  const input = document.getElementById(d.target);
  if (input) { input.focus(); input.scrollIntoView({ behavior: "smooth", block: "center" }); }
};
routes.toggleFlag = d => {
  const nav = document.getElementById(`navq-${d.target}`);
  if (nav) nav.classList.toggle("is-flagged");
};
routes.navPrev = () => stepQuestion(window._navPrefix, -1);
routes.navNext = () => stepQuestion(window._navPrefix, 1);

document.addEventListener("click", e => {
  const panel = document.getElementById("settingsPanel");
  if (panel && !panel.hidden && !e.target.closest(".settings-wrap")) panel.hidden = true;
});

function tickTimer(remaining, warnAt) {
  const box = document.getElementById("timerPill");
  const val = document.getElementById("timerValue");
  if (!box || !val) return;
  val.textContent = fmtTime(remaining);
  if (remaining <= warnAt) box.classList.add("warning");
}

/* ---------------- bottom question navigator ---------------- */

function navBarHtml(groups, prefix) {
  const groupsHtml = groups.map(g => {
    let btns = "";
    for (let q = g.from; q <= g.to; q++) {
      const target = `${prefix}-${q}`;
      btns += `
        <div class="navq" id="navq-${target}">
          <button class="navq-num" data-action="jumpTo" data-target="${target}" aria-label="Go to question ${q}">${q}</button>
          <button class="navq-flag" data-action="toggleFlag" data-target="${target}" aria-label="Flag question ${q} for review"></button>
        </div>`;
    }
    return `<div class="navq-group"><span class="navq-group-label">${esc(g.label)}</span><div class="navq-row">${btns}</div></div>`;
  }).join("");
  return `
    <div class="exam-navbar">
      <button class="navbar-arrow" data-action="navPrev" aria-label="Previous question">&#10094;</button>
      <div class="exam-navbar-scroll">${groupsHtml}</div>
      <button class="navbar-arrow" data-action="navNext" aria-label="Next question">&#10095;</button>
    </div>`;
}

function syncNavAnswered(prefix) {
  document.querySelectorAll(`.exam-answers [id^="${prefix}-"]`).forEach(inp => {
    const q = inp.id.split("-")[1];
    const nav = document.getElementById(`navq-${prefix}-${q}`);
    if (nav) nav.classList.toggle("is-answered", inp.value.trim() !== "");
  });
}

function syncNavCurrent(prefix, q) {
  document.querySelectorAll(".navq.is-current").forEach(n => n.classList.remove("is-current"));
  const nav = document.getElementById(`navq-${prefix}-${q}`);
  if (nav) {
    nav.classList.add("is-current");
    nav.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
  }
}

function stepQuestion(prefix, dir) {
  if (!prefix) return;
  const inputs = [...document.querySelectorAll(`.exam-answers [id^="${prefix}-"]`)];
  if (!inputs.length) return;
  const activeIdx = inputs.findIndex(i => i.id === document.activeElement?.id);
  const idx = activeIdx === -1 ? 0 : Math.min(inputs.length - 1, Math.max(0, activeIdx + dir));
  inputs[idx].focus();
  inputs[idx].scrollIntoView({ behavior: "smooth", block: "center" });
}

/* ---------------- text view (extracted content) ---------------- */

async function fetchContent(mockId, testName) {
  try {
    return await api(`/api/mocks/${encodeURIComponent(mockId)}/tests/${encodeURIComponent(testName)}/content`);
  } catch { return null; }
}

const _BLOCK_PATTERNS = {
  qrange: /^(?:[QO]uestions?\s+\d|READING PASSAGE\s+\d|(?:SECTION|PART)\s+\d+$)/i,
  instruction: /^(Complete|Choose|Write|Circle|Label)\b.{0,70}$/i,
  letterMark: /^[A-H]$/,
  allCaps: /^[A-Z][A-Z\s'.,\-]{3,60}$/,
};

function classifyBlock(text) {
  if (_BLOCK_PATTERNS.letterMark.test(text)) return "letter-mark";
  if (_BLOCK_PATTERNS.qrange.test(text)) return "q-range";
  if (_BLOCK_PATTERNS.instruction.test(text) || _BLOCK_PATTERNS.allCaps.test(text)) return "instruction";
  return "prose";
}

function textWithInlineInputs(text, prefix, qFrom, qTo) {
  // Turn numbered gaps ("7 ........" / "7 ____") into inline inputs
  // synced with the answer sheet. Only numbers in this section's range
  // become inputs, so years/quantities in prose are left alone.
  const addGaps = raw => esc(raw).replace(/\b(\d{1,2})\s*(?:[.…·]{3,}|_{3,})/g, (m, num) => {
    const q = Number(num);
    if (q < qFrom || q > qTo) return m;
    return `<span class="inline-q"><span class="inline-qnum">${q}</span><input class="inline-input" data-inline-q="${q}" data-prefix="${prefix}" autocomplete="off" spellcheck="false" aria-label="Answer for question ${q}"></span>`;
  });

  return text.split(/\n{2,}/).filter(b => b.trim()).map(block => {
    const kind = classifyBlock(block.trim());
    if (kind === "letter-mark") return `<div class="para-letter">${esc(block.trim())}</div>`;
    if (kind === "q-range") return `<div class="q-range-head">${esc(block.trim())}</div>`;
    if (kind === "instruction") return `<div class="q-instruction">${addGaps(block.trim())}</div>`;
    return `<p>${addGaps(block)}</p>`;
  }).join("");
}

function wireInlineInputs(container) {
  container.querySelectorAll(".inline-input").forEach(inp => {
    const q = inp.dataset.inlineQ, prefix = inp.dataset.prefix;
    const sheet = document.getElementById(`${prefix}-${q}`);
    if (!sheet) return;
    inp.addEventListener("input", () => {
      sheet.value = inp.value;
      sheet.dispatchEvent(new Event("input"));
    });
    inp.addEventListener("focus", () => syncNavCurrent(prefix, q));
    sheet.addEventListener("input", () => {
      if (document.activeElement !== inp) inp.value = sheet.value;
    });
  });
}

function viewToggleHtml(hasText) {
  if (!hasText) return "";
  return `
    <div class="view-toggle">
      <button class="vt-btn active" data-vt="text">Text</button>
      <button class="vt-btn" data-vt="book">Book view</button>
    </div>`;
}

function wireViewToggle(container) {
  const tabs = container.querySelector(".view-toggle");
  if (!tabs) return;
  tabs.addEventListener("click", e => {
    const btn = e.target.closest(".vt-btn");
    if (!btn) return;
    tabs.querySelectorAll(".vt-btn").forEach(b => b.classList.toggle("active", b === btn));
    const mode = btn.dataset.vt;
    container.querySelectorAll(".content-text").forEach(el => el.style.display = mode === "text" ? "" : "none");
    container.querySelectorAll(".content-book").forEach(el => el.style.display = mode === "book" ? "" : "none");
  });
}

/* ---------------- READING ---------------- */

async function startReading(mockId, testName) {
  loading("Preparing reading section…");
  const cfg = await api(`/api/mocks/${encodeURIComponent(mockId)}/tests/${encodeURIComponent(testName)}`);
  const rcfg = cfg.reading;
  const totalSeconds = rcfg.duration_minutes * 60;
  const attempt = await api("/api/attempts/start", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mock_id: mockId, test_name: testName, section: "reading", time_allowed_seconds: totalSeconds })
  });

  const content = await fetchContent(mockId, testName);
  const rtexts = content?.reading?.passages || [];
  const groups = rcfg.passages.map((p, i) => ({ label: `Passage ${i + 1}`, from: p.questions[0], to: p.questions[1] }));
  let totalQ = 0;
  let materialHtml = "";
  rcfg.passages.forEach((p, i) => {
    const imgs = p.pages.map(pg =>
      `<img src="/api/mocks/${encodeURIComponent(mockId)}/page?page=${pg}" alt="Reading passage page ${pg}" loading="lazy">`).join("");
    const txt = rtexts[i]?.text;
    if (txt) {
      materialHtml += `
        <div class="passage-block">
          <div class="passage-head">Reading Passage ${i + 1}</div>
          <div class="content-text">${textWithInlineInputs(txt, "ans", p.questions[0], p.questions[1])}</div>
          <div class="content-book" style="display:none">${imgs}</div>
        </div>`;
    } else {
      materialHtml += `<div class="passage-block"><div class="passage-head">Reading Passage ${i + 1}</div>${imgs}</div>`;
    }
    totalQ += p.questions[1] - p.questions[0] + 1;
  });
  const hasText = rtexts.some(t => t?.text);

  app.innerHTML = `
    ${examBarHtml("Reading", { mockId })}
    ${viewToggleHtml(hasText)}
    <div class="exam-shell">
      <div class="exam-material">${materialHtml}</div>
      <div class="exam-answers">
        <h3>Answer sheet</h3>
        ${answerSheetHtml(groups, "ans")}
        <div class="submit-area">
          <button class="btn btn-primary" id="submitBtn">Submit reading</button>
        </div>
      </div>
    </div>
    ${navBarHtml(groups, "ans")}`;

  examInProgress = true;
  window._navPrefix = "ans";
  document.body.classList.add("has-exam-navbar");
  wireAnswerSheet(app);
  wireInlineInputs(app);
  wireViewToggle(app);
  syncNavAnswered("ans");
  document.getElementById("answeredCount").textContent = `0 / ${totalQ} answered`;

  const doSubmit = auto => submitSection({
    attemptId: attempt.attempt_id, mockId, testName,
    section: "reading", prefix: "ans", label: "Reading", auto, groups,
  });
  document.getElementById("submitBtn").addEventListener("click", () => {
    const left = unansweredCount("ans");
    if (left > 0) {
      confirmModal({
        title: "Submit with blanks?",
        body: `${left} question${left === 1 ? " is" : "s are"} still unanswered. Blank answers are marked wrong.`,
        confirmLabel: "Submit anyway",
        onConfirm: () => doSubmit(false),
      });
    } else doSubmit(false);
  });

  startTimer(totalSeconds, r => tickTimer(r, 300), () => doSubmit(true));
}

/* ---------------- LISTENING ---------------- */

async function startListening(mockId, testName) {
  loading("Preparing listening section…");
  const cfg = await api(`/api/mocks/${encodeURIComponent(mockId)}/tests/${encodeURIComponent(testName)}`);
  const lcfg = cfg.listening;
  // Real IELTS listening: ~30 min of audio + 10 min transfer = 40 min total.
  const totalSeconds = (lcfg.duration_minutes || 40) * 60;
  const attempt = await api("/api/attempts/start", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mock_id: mockId, test_name: testName, section: "listening", time_allowed_seconds: totalSeconds })
  });

  const groups = lcfg.parts.map((p, i) => ({ label: `Part ${p.part_number || i + 1}`, from: p.questions[0], to: p.questions[1] }));
  const totalQ = groups.reduce((a, g) => a + g.to - g.from + 1, 0);

  const content = await fetchContent(mockId, testName);
  const ltexts = content?.listening?.parts || [];
  let materialHtml = "";
  lcfg.parts.forEach((p, i) => {
    const pages = p.pages || [];
    const imgs = pages.length
      ? pages.map(pg => `<img src="/api/mocks/${encodeURIComponent(mockId)}/page?page=${pg}" alt="Listening part ${i + 1} question sheet, page ${pg}" loading="lazy">`).join("")
      : `<div class="missing-sheet">The question sheet for this part isn't configured yet. Add its page numbers to the <strong>pages</strong> list for this part in manifest.json.</div>`;
    const txt = ltexts[i]?.text;
    const sheetHtml = txt
      ? `<div class="content-text">${textWithInlineInputs(txt, "lans", p.questions[0], p.questions[1])}</div>
         <div class="content-book" style="display:none">${imgs}</div>`
      : imgs;
    // A part can be split across multiple audio files (e.g. two halves of
    // one recording) -- these must play back-to-back as ONE continuous
    // "once only" listen, not as separate parts. Old manifests may still
    // have a singular "file" instead of "files"; support both.
    const partFiles = p.files || (p.file ? [p.file] : []);
    materialHtml += `
      <div class="listening-part">
        <div class="audio-bar">
          <span class="part-label">Part ${p.part_number || i + 1} · Q${p.questions[0]}–${p.questions[1]}</span>
          <button class="btn btn-primary btn-play" data-part="${i}" data-files='${esc(JSON.stringify(partFiles))}'>▶ Play (once only)</button>
          <div class="audio-progress"><div class="audio-progress-fill" id="audioFill-${i}"></div></div>
          <span class="audio-time" id="audioTime-${i}">not started</span>
        </div>
        <div class="question-sheet">${sheetHtml}</div>
      </div>`;
  });
  const hasText = ltexts.some(t => t?.text);

  app.innerHTML = `
    ${examBarHtml("Listening", { mockId })}
    ${viewToggleHtml(hasText)}
    <div class="exam-shell">
      <div class="exam-material">${materialHtml}</div>
      <div class="exam-answers">
        <h3>Answer sheet</h3>
        ${answerSheetHtml(groups, "lans")}
        <div class="submit-area">
          <button class="btn btn-primary" id="submitBtn">Submit listening</button>
        </div>
      </div>
    </div>
    ${navBarHtml(groups, "lans")}`;

  examInProgress = true;
  window._navPrefix = "lans";
  document.body.classList.add("has-exam-navbar");
  wireAnswerSheet(app);
  wireInlineInputs(app);
  wireViewToggle(app);
  syncNavAnswered("lans");
  document.getElementById("answeredCount").textContent = `0 / ${totalQ} answered`;

  // Exam-condition audio: plays exactly once, no pause, no seeking, no
  // replay. A part's files play back-to-back as ONE continuous listen, and
  // starting any part always stops whatever else was playing first --
  // only one part can ever be audible at a time.
  document.querySelectorAll(".btn-play").forEach(btn => {
    btn.addEventListener("click", () => {
      stopActiveListeningAudio(); // kill whatever else was playing

      const i = btn.dataset.part;
      const files = JSON.parse(btn.dataset.files);
      const fillEl = document.getElementById(`audioFill-${i}`);
      const timeEl = document.getElementById(`audioTime-${i}`);

      btn.disabled = true;
      btn.textContent = "Playing…";

      const audio = new Audio();
      activeListeningAudio = audio;
      activeListeningReset = () => {
        btn.disabled = false;
        btn.textContent = "▶ Play (once only)";
        timeEl.textContent = "stopped";
      };

      let fileIdx = 0;
      const playNext = () => {
        if (fileIdx >= files.length) {
          btn.textContent = "✓ Played";
          timeEl.textContent = "finished";
          if (activeListeningAudio === audio) activeListeningAudio = null;
          activeListeningReset = null;
          return;
        }
        audio.src = `/api/mocks/${encodeURIComponent(mockId)}/tests/${encodeURIComponent(testName)}/audio?file=${encodeURIComponent(files[fileIdx])}`;
        fileIdx++;
        audio.play();
      };

      audio.addEventListener("timeupdate", () => {
        if (audio.duration) {
          fillEl.style.width = `${audio.currentTime / audio.duration * 100}%`;
          timeEl.textContent = `${fmtTime(Math.floor(audio.currentTime))} / ${fmtTime(Math.floor(audio.duration))}`;
        }
      });
      audio.addEventListener("ended", playNext);
      // if the browser pauses it for any reason mid-play (not our own
      // stopActiveListeningAudio call), resume -- heard once, straight
      // through, like the real exam
      audio.addEventListener("pause", () => {
        if (!audio.ended && activeListeningAudio === audio) audio.play();
      });

      playNext();
    });
  });

  const doSubmit = auto => submitSection({
    attemptId: attempt.attempt_id, mockId, testName,
    section: "listening", prefix: "lans", label: "Listening", auto, groups,
  });

  document.getElementById("submitBtn").addEventListener("click", () => {
    const left = unansweredCount("lans");
    if (left > 0) {
      confirmModal({
        title: "Submit with blanks?",
        body: `${left} question${left === 1 ? " is" : "s are"} still unanswered. Blank answers are marked wrong.`,
        confirmLabel: "Submit anyway",
        onConfirm: () => doSubmit(false),
      });
    } else doSubmit(false);
  });

  startTimer(totalSeconds, r => tickTimer(r, 300), () => doSubmit(true));
}

/* ---------------- shared submit for reading/listening ---------------- */

async function submitSection({ attemptId, mockId, testName, section, prefix, label, auto, groups }) {
  clearTimer();
  examInProgress = false;
  const answers = collectAnswers(prefix); // must run before loading() replaces the DOM
  loading("Marking your answers…");
  const result = await api(`/api/attempts/${attemptId}/submit`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mock_id: mockId, test_name: testName, section, answers, auto_submitted: auto })
  });
  await renderResults(label, result, auto, mockId, groups, { testName, section, attemptId });
}

/* ---------------- WRITING ---------------- */

async function startWriting(mockId, testName) {
  const cfg = await api(`/api/mocks/${encodeURIComponent(mockId)}/tests/${encodeURIComponent(testName)}`);
  const wcfg = cfg.writing;
  startWritingTask(mockId, testName, "task1", wcfg.task1,
    () => startWritingTask(mockId, testName, "task2", wcfg.task2, () => renderMockTests(mockId)));
}

async function startWritingTask(mockId, testName, taskKey, taskCfg, onDone) {
  loading("Preparing writing task…");
  const totalSeconds = taskCfg.duration_minutes * 60;
  const attempt = await api("/api/attempts/start", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mock_id: mockId, test_name: testName, section: "writing", time_allowed_seconds: totalSeconds })
  });

  const label = taskKey === "task1" ? "Writing · Task 1" : "Writing · Task 2";
  app.innerHTML = `
    ${examBarHtml(label, { mockId })}
    <div class="exam-shell">
      <div class="exam-material">
        <img src="/api/mocks/${encodeURIComponent(mockId)}/page?page=${taskCfg.page}" alt="${esc(label)} prompt">
      </div>
      <div class="exam-answers">
        <h3>Your response</h3>
        <textarea class="essay" id="essayBox" placeholder="Write your response here…"></textarea>
        <div class="word-count" id="wc">0 words</div>
        <div class="submit-area">
          <button class="btn btn-primary" id="submitBtn">Submit ${taskKey === "task1" ? "Task 1" : "Task 2"}</button>
        </div>
      </div>
    </div>`;

  examInProgress = true;
  const box = document.getElementById("essayBox");
  box.addEventListener("input", () => {
    const words = box.value.trim().split(/\s+/).filter(Boolean).length;
    document.getElementById("wc").textContent = `${words} words`;
  });

  const doSubmit = auto => submitWriting(attempt.attempt_id, mockId, testName, taskKey, taskCfg, auto, onDone);
  document.getElementById("submitBtn").addEventListener("click", () => {
    const words = box.value.trim().split(/\s+/).filter(Boolean).length;
    const minWords = taskKey === "task1" ? 150 : 250;
    if (words < minWords) {
      confirmModal({
        title: "Under the word minimum",
        body: `You've written ${words} words; the exam expects at least ${minWords}. Short responses lose marks.`,
        confirmLabel: "Submit anyway",
        onConfirm: () => doSubmit(false),
      });
    } else doSubmit(false);
  });

  startTimer(totalSeconds, r => tickTimer(r, 120), () => doSubmit(true));
}

async function submitWriting(attemptId, mockId, testName, taskKey, taskCfg, auto, onDone) {
  clearTimer();
  examInProgress = false;
  const essay = document.getElementById("essayBox").value;
  loading("Submitting your response…");
  await api(`/api/attempts/${attemptId}/submit`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mock_id: mockId, test_name: testName, section: "writing", answers: { essay }, auto_submitted: auto })
  });

  loading("Getting examiner feedback on your writing…");
  let feedback;
  try {
    feedback = await api("/api/writing/feedback", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_type: taskKey, prompt_description: `${taskKey} for ${testName}`, essay_text: essay })
    });
  } catch (err) {
    feedback = { error: err.message };
  }

  window._writingOnDone = onDone;
  const taskLabel = taskKey === "task1" ? "Task 1" : "Task 2";
  app.innerHTML = `
    <div class="results-box">
      <h2>${taskLabel} submitted${auto ? " <span class='auto-note'>(time expired)</span>" : ""}</h2>
      ${feedback.error
        ? `<p class="feedback-text">Feedback isn't available: ${esc(feedback.error)}</p>`
        : `
          <div class="score-line"><span class="band-chip">Band ${esc(String(feedback.overall_band))}</span></div>
          ${bandRibbonHtml(feedback.overall_band)}
          <div class="criteria-grid">
            <div class="criterion"><div class="label">Task achievement</div><div class="value">${esc(String(feedback.task_achievement))}</div></div>
            <div class="criterion"><div class="label">Coherence &amp; cohesion</div><div class="value">${esc(String(feedback.coherence_cohesion))}</div></div>
            <div class="criterion"><div class="label">Lexical resource</div><div class="value">${esc(String(feedback.lexical_resource))}</div></div>
            <div class="criterion"><div class="label">Grammar accuracy</div><div class="value">${esc(String(feedback.grammar_accuracy))}</div></div>
          </div>
          <p class="feedback-text">${esc(feedback.feedback)}</p>
        `}
      ${(taskCfg.sample_pages || []).length ? `
        <h3 class="results-subhead">Sample answers from your book</h3>
        <p class="sample-note">Real candidate responses to this task with the examiner's band score and comments — compare them with what you wrote.</p>
        <div class="sample-pages">
          ${taskCfg.sample_pages.map(pg => `<img src="/api/mocks/${encodeURIComponent(mockId)}/page?page=${pg}" alt="Sample answer page ${pg}" loading="lazy">`).join("")}
        </div>` : ""}
      <div class="submit-area"><button class="btn btn-primary" data-action="writingContinue">Continue</button></div>
    </div>`;
}
routes.writingContinue = () => (window._writingOnDone || renderHome)();

/* ---------------- RESULTS ---------------- */

function bandRibbonHtml(band) {
  const pct = Math.max(0, Math.min(9, Number(band))) / 9 * 100;
  return `
    <div class="band-ribbon">
      <div class="track"><div class="marker" style="left:${pct}%"></div></div>
      <div class="scale">${[0,1,2,3,4,5,6,7,8,9].map(n => `<span>${n}</span>`).join("")}</div>
    </div>`;
}

/* ---------------- answer-key page viewer (for manual comparison) ---------------- */

async function answerKeyPageHtml(mockId, testInfo) {
  if (!testInfo) return "";
  try {
    const { page } = await api(
      `/api/mocks/${encodeURIComponent(mockId)}/tests/${encodeURIComponent(testInfo.testName)}/answer-key-page?section=${encodeURIComponent(testInfo.section)}`
    );
    return `
      <div class="key-page-toggle">
        <button class="btn-key-page" data-action="toggleKeyPage">📖 View answer key page ${page} (compare manually)</button>
      </div>
      <div class="key-page-viewer" id="keyPageViewer" style="display:none">
        <img src="/api/mocks/${encodeURIComponent(mockId)}/page?page=${page}" alt="Answer key page ${page}" loading="lazy">
      </div>`;
  } catch {
    return ""; // no known answer-key page for this section -- omit the button entirely
  }
}

function wireKeyPageToggle(container) {
  const btn = container.querySelector("[data-action='toggleKeyPage']");
  const viewer = container.querySelector("#keyPageViewer");
  if (!btn || !viewer) return;
  btn.addEventListener("click", () => {
    const showing = viewer.style.display !== "none";
    viewer.style.display = showing ? "none" : "";
    btn.textContent = showing
      ? btn.textContent.replace("Hide", "View")
      : btn.textContent.replace("View", "Hide");
  });
}

/* ---------------- manual score entry ---------------- */

function manualScoreFormHtml(total) {
  return `
    <div class="manual-score-box" id="manualScoreBox">
      <h4>Tally your own answers?</h4>
      <p>If you've checked your answers against the key page above, enter how many you got
      right and the band will be calculated automatically.</p>
      <div class="manual-score-row">
        <input type="number" id="manualScoreInput" min="0" max="${total}" placeholder="0" aria-label="Correct answers">
        <span>/ ${total} correct</span>
        <button class="btn btn-primary" id="manualScoreSave">Save score</button>
      </div>
      <div id="manualScoreResult"></div>
    </div>`;
}

function wireManualScoreForm(container, attemptId, total, onSaved) {
  const box = container.querySelector("#manualScoreBox");
  if (!box || !attemptId) return;
  const input = box.querySelector("#manualScoreInput");
  const btn = box.querySelector("#manualScoreSave");
  const resultEl = box.querySelector("#manualScoreResult");
  btn.addEventListener("click", async () => {
    const n = Number(input.value);
    if (!Number.isInteger(n) || n < 0 || n > total) {
      resultEl.innerHTML = `<p class="manual-score-error">Enter a whole number from 0 to ${total}.</p>`;
      return;
    }
    btn.disabled = true;
    try {
      const saved = await api(`/api/attempts/${attemptId}/manual-score`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ correct_count: n }),
      });
      resultEl.innerHTML = `
        <p class="manual-score-done">Saved: ${saved.correct_count}/${saved.total} —
        <span class="band-chip band-chip-clickable" data-action="showBand" data-attempt="${attemptId}"
          title="Click to see how this was calculated">Band ${saved.band_estimate}</span></p>`;
      if (onSaved) onSaved(saved);
    } catch {
      resultEl.innerHTML = `<p class="manual-score-error">Couldn't save that — try again.</p>`;
    }
    btn.disabled = false;
  });
}

async function renderUnmarkedResults(sectionLabel, result, mockId, testInfo) {
  const rows = Object.entries(result.results)
    .sort((a, b) => Number(a[0]) - Number(b[0]))
    .map(([q, r]) => `
      <div class="q-result skipped">
        <span class="qn">${q}</span>
        <span class="given">${r.given ? esc(r.given) : "<em>not answered</em>"}</span>
        <span class="expected"><em>key not entered</em></span>
      </div>`).join("");
  const keyPageHtml = await answerKeyPageHtml(mockId, testInfo);
  app.innerHTML = `
    <div class="results-box results-wide">
      <h2>${esc(sectionLabel)} — answers recorded (unmarked)</h2>
      <p class="unmarked-note">This test's answer key hasn't been filled in yet, so no score
      can be calculated — but your answers below are saved, and you can mark them yourself
      against the key in your book. To get auto-marking next time, fill in
      <code>answers/&lt;Test&gt;/${sectionLabel.toLowerCase()}.json</code> — see
      <strong>ANSWER_KEYS.md</strong> and <strong>NEEDS_ATTENTION.md</strong> for exactly
      what's missing and where to find it in the PDF.</p>
      ${keyPageHtml}
      ${testInfo?.attemptId ? manualScoreFormHtml(result.total) : ""}
      <div class="q-result q-result-head"><span class="qn">Q</span><span>Your answer</span><span></span></div>
      <div class="review-list">${rows}</div>
      <div class="submit-area">
        <button class="btn btn-primary" data-action="openMock" data-mock="${esc(mockId)}">Back to tests</button>
      </div>
    </div>`;
  wireKeyPageToggle(app);
  wireManualScoreForm(app, testInfo?.attemptId, result.total);
}

async function renderResults(sectionLabel, result, autoSubmitted, mockId, groups, testInfo) {
  if (result.unmarked) {
    await renderUnmarkedResults(sectionLabel, result, mockId, testInfo);
    return;
  }
  // Classify each question: correct / incorrect / skipped (blank)
  const entries = Object.entries(result.results).map(([q, r]) => ({
    q: Number(q),
    given: r.given || "",
    correct: Array.isArray(r.correct_answer) ? r.correct_answer.join(" / ") : String(r.correct_answer),
    status: r.is_correct === null ? "unmarkable"
      : r.is_correct ? "correct"
      : (String(r.given || "").trim() === "" ? "skipped" : "incorrect"),
  })).sort((a, b) => a.q - b.q);

  const counts = {
    correct: entries.filter(e => e.status === "correct").length,
    incorrect: entries.filter(e => e.status === "incorrect").length,
    skipped: entries.filter(e => e.status === "skipped").length,
  };
  const accuracy = entries.length ? Math.round(counts.correct / entries.length * 100) : 0;

  // Per-part / per-passage breakdown
  const groupRows = (groups || []).map(g => {
    const inGroup = entries.filter(e => e.q >= g.from && e.q <= g.to);
    const ok = inGroup.filter(e => e.status === "correct").length;
    const pct = inGroup.length ? Math.round(ok / inGroup.length * 100) : 0;
    return { ...g, ok, total: inGroup.length, pct };
  });
  const weakest = groupRows.length > 1
    ? groupRows.reduce((a, b) => (b.pct < a.pct ? b : a))
    : null;

  const reviewRow = e => `
    <div class="q-result ${e.status === "unmarkable" ? "skipped" : e.status}" data-status="${e.status}">
      <span class="qn">${e.status === "correct" ? "✓" : e.status === "incorrect" ? "✗" : "—"} ${e.q}</span>
      <span class="given">${e.given ? esc(e.given) : "<em>not answered</em>"}</span>
      <span class="expected">${e.status === "unmarkable" ? "<em>key not entered</em>" : esc(e.correct)}</span>
    </div>`;

  app.innerHTML = `
    <div class="results-box results-wide">
      <h2>${esc(sectionLabel)} results ${autoSubmitted ? "<span class='auto-note'>(auto-submitted — time expired)</span>" : ""}</h2>
      <div class="score-line">
        <span class="score-frac">${result.correct_count} / ${result.total}</span>
        <span class="band-chip band-chip-clickable" data-action="showBand" data-attempt="${testInfo?.attemptId ?? ''}" title="Click to see how this was calculated">Band ${esc(String(result.band_estimate))}</span>
        <span class="time-taken">${fmtTime(result.time_taken_seconds)} taken</span>
      </div>
      ${bandRibbonHtml(result.band_estimate)}

      <div class="summary-tiles">
        <div class="tile good"><div class="tile-num">${counts.correct}</div><div class="tile-label">Correct</div></div>
        <div class="tile bad"><div class="tile-num">${counts.incorrect}</div><div class="tile-label">Incorrect</div></div>
        <div class="tile skip"><div class="tile-num">${counts.skipped}</div><div class="tile-label">Skipped</div></div>
        <div class="tile"><div class="tile-num">${accuracy}%</div><div class="tile-label">Accuracy</div></div>
      </div>

      ${groupRows.length ? `
        <h3 class="results-subhead">Where you gained and lost marks</h3>
        <div class="group-breakdown">
          ${groupRows.map(g => `
            <div class="group-row">
              <span class="group-label">${esc(g.label)} <span class="group-range">Q${g.from}–${g.to}</span></span>
              <div class="group-bar"><div class="group-fill ${g.pct >= 70 ? "good" : g.pct >= 40 ? "mid" : "low"}" style="width:${g.pct}%"></div></div>
              <span class="group-score">${g.ok}/${g.total}</span>
            </div>`).join("")}
        </div>
        ${weakest && weakest.pct < 70 ? `<p class="weak-note">Weakest area: <strong>${esc(weakest.label)}</strong> (${weakest.pct}% correct) — review those questions first.</p>` : ""}
      ` : ""}

      <h3 class="results-subhead">Answer review</h3>
      <div class="filter-tabs" id="filterTabs">
        <button class="ftab active" data-filter="all">All <span class="fcount">${entries.length}</span></button>
        <button class="ftab" data-filter="incorrect">Incorrect <span class="fcount">${counts.incorrect}</span></button>
        <button class="ftab" data-filter="skipped">Skipped <span class="fcount">${counts.skipped}</span></button>
        <button class="ftab" data-filter="correct">Correct <span class="fcount">${counts.correct}</span></button>
      </div>
      <div class="q-result q-result-head">
        <span class="qn">Q</span><span>Your answer</span><span>Correct answer</span>
      </div>
      <div class="review-list" id="reviewList">${entries.map(reviewRow).join("")}</div>

      ${await answerKeyPageHtml(mockId, testInfo)}

      <div class="submit-area">
        <button class="btn btn-primary" data-action="openMock" data-mock="${esc(mockId)}">Back to tests</button>
      </div>
    </div>`;

  wireKeyPageToggle(app);

  // Filter tab behavior
  const tabs = document.getElementById("filterTabs");
  tabs.addEventListener("click", e => {
    const tab = e.target.closest(".ftab");
    if (!tab) return;
    tabs.querySelectorAll(".ftab").forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    const f = tab.dataset.filter;
    document.querySelectorAll("#reviewList .q-result").forEach(row => {
      row.style.display = (f === "all" || row.dataset.status === f) ? "" : "none";
    });
  });
}

/* ---------------- DASHBOARD ---------------- */

async function renderDashboard() {
  clearTimer();
  loading("Loading your progress…");
  const history = await api("/api/history");

  if (history.length === 0) {
    app.innerHTML = `
      <div class="page-head"><h2>Progress</h2></div>
      <div class="empty-state">
        <h3>No attempts yet</h3>
        <p>Sit any section of a mock test and your scores will show up here.</p>
      </div>`;
    return;
  }

  const scored = history.filter(h => h.band_estimate != null);
  const best = scored.length ? Math.max(...scored.map(h => h.band_estimate)) : null;
  const avg = scored.length ? (scored.reduce((a, h) => a + h.band_estimate, 0) / scored.length).toFixed(1) : null;

  app.innerHTML = `
    <div class="page-head">
      <h2>Progress</h2>
      <p class="sub">Every attempt you've made, most recent first.</p>
    </div>
    <div class="stat-row">
      <div class="stat-card"><div class="label">Attempts</div><div class="value">${history.length}</div></div>
      <div class="stat-card"><div class="label">Best band</div><div class="value band">${best ?? "—"}</div></div>
      <div class="stat-card"><div class="label">Average band</div><div class="value band">${avg ?? "—"}</div></div>
    </div>
    <table class="history">
      <tr><th>Date</th><th>Mock / test</th><th>Section</th><th>Score</th><th>Band</th><th>Time</th></tr>
      ${history.map(h => `
        <tr>
          <td class="mono">${new Date(h.submitted_at * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}</td>
          <td>${esc(h.test_id.replace("::", " — "))}</td>
          <td><span class="section-tag">${esc(h.section)}</span></td>
          <td class="mono">${h.correct_count !== null ? `${h.correct_count}/${h.total}`
            : (["reading", "listening"].includes(h.section) && h.total)
              ? `<button class="btn-enter-score" data-action="enterScore" data-attempt="${h.id}" data-total="${h.total}">Enter score</button>`
              : "—"}</td>
          <td>${h.band_estimate != null ? `<span class="band-chip band-chip-clickable" data-action="showBand" data-attempt="${h.id}" title="Click to see how this was calculated">${h.band_estimate}</span>` : "—"}</td>
          <td class="mono">${fmtTime(h.time_taken_seconds)}</td>
        </tr>`).join("")}
    </table>`;
}

/* ---------------- boot ---------------- */
renderHome();
