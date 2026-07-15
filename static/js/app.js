const app = document.getElementById("app");
let timerInterval = null;

document.querySelectorAll("header nav button").forEach(btn => {
  btn.onclick = () => {
    if (btn.dataset.view === "home") renderHome();
    if (btn.dataset.view === "dashboard") renderDashboard();
  };
});

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.headers.get("content-type")?.includes("json") ? res.json() : res;
}

// ---------------- HOME: pick a mock, then a test within it ----------------

async function renderHome() {
  clearTimer();
  const mocks = await api("/api/mocks");
  app.innerHTML = `<h2>Mocks</h2>` + (mocks.length === 0
    ? `<p>No mocks found. Add a mock folder under <code>tests/</code> following the README convention.</p>`
    : mocks.map(m => `
      <div class="test-card">
        <div>
          <h3>${m.mock_name}</h3>
          <div class="badges">${Object.keys(m.tests).map(t => `<span>${t}</span>`).join("")}</div>
        </div>
        <div class="section-buttons">
          <button onclick='renderMockTests(${JSON.stringify(m.id)})'>Open</button>
        </div>
      </div>
    `).join(""));
}

async function renderMockTests(mockId) {
  clearTimer();
  const mock = await api(`/api/mocks/${encodeURIComponent(mockId)}`);
  const tests = Object.entries(mock.tests);
  app.innerHTML = `
    <button onclick="renderHome()">&larr; All mocks</button>
    <h2>${mock.mock_name}</h2>
    ${tests.map(([name, cfg]) => `
      <div class="test-card">
        <div><h3>${name}</h3></div>
        <div class="section-buttons">
          ${cfg.reading ? `<button onclick="startReading('${mockId}','${name}')">Reading</button>` : ""}
          ${cfg.listening ? `<button onclick="startListening('${mockId}','${name}')">Listening</button>` : ""}
          ${cfg.writing ? `<button onclick="startWriting('${mockId}','${name}')">Writing</button>` : ""}
        </div>
      </div>
    `).join("")}
  `;
}

// ---------------- SHARED TIMER ----------------

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
    if (remaining <= 0) {
      clearTimer();
      onExpire();
    }
  }, 1000);
}

function fmtTime(sec) {
  sec = Math.max(0, sec);
  const m = Math.floor(sec / 60).toString().padStart(2, "0");
  const s = (sec % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

// ---------------- READING ----------------

async function startReading(mockId, testName) {
  const cfg = await api(`/api/mocks/${encodeURIComponent(mockId)}/tests/${encodeURIComponent(testName)}`);
  const rcfg = cfg.reading;
  const totalSeconds = rcfg.duration_minutes * 60;
  const attempt = await api("/api/attempts/start", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mock_id: mockId, test_name: testName, section: "reading", time_allowed_seconds: totalSeconds })
  });

  const allQuestions = [];
  let materialHtml = "";
  rcfg.passages.forEach(p => {
    p.pages.forEach(pageNum => {
      materialHtml += `<img src="/api/mocks/${encodeURIComponent(mockId)}/page?page=${pageNum}">`;
    });
    for (let q = p.questions[0]; q <= p.questions[1]; q++) allQuestions.push(q);
  });

  app.innerHTML = `
    <div class="timer-bar" id="timerBar">Reading — <span id="timerLabel"></span> remaining</div>
    <div class="exam-shell">
      <div class="exam-material">${materialHtml}</div>
      <div class="exam-answers">
        <h3>Answers</h3>
        ${allQuestions.map(q => `
          <div class="q-row">
            <label>${q}.</label>
            <input type="text" id="ans-${q}" autocomplete="off">
          </div>`).join("")}
        <button class="submit-btn" onclick="submitReading(${attempt.attempt_id}, '${mockId}', '${testName}', false)">Submit Reading</button>
      </div>
    </div>
  `;

  startTimer(totalSeconds, remaining => {
    document.getElementById("timerLabel").textContent = fmtTime(remaining);
    const bar = document.getElementById("timerBar");
    if (bar && remaining <= 300) bar.classList.add("warning");
  }, () => submitReading(attempt.attempt_id, mockId, testName, true));
}

function collectAnswers(prefix) {
  const answers = {};
  document.querySelectorAll(`[id^="${prefix}-"]`).forEach(el => {
    const qnum = el.id.split("-")[1];
    answers[qnum] = el.value;
  });
  return answers;
}

async function submitReading(attemptId, mockId, testName, autoSubmitted) {
  clearTimer();
  const answers = collectAnswers("ans");
  const result = await api(`/api/attempts/${attemptId}/submit`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mock_id: mockId, test_name: testName, section: "reading", answers, auto_submitted: autoSubmitted })
  });
  renderResults("Reading", result, autoSubmitted, mockId);
}

// ---------------- LISTENING ----------------

async function startListening(mockId, testName) {
  const cfg = await api(`/api/mocks/${encodeURIComponent(mockId)}/tests/${encodeURIComponent(testName)}`);
  const lcfg = cfg.listening;
  const transferSeconds = 10 * 60;
  const attempt = await api("/api/attempts/start", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mock_id: mockId, test_name: testName, section: "listening", time_allowed_seconds: 0 })
  });

  const allQuestions = [];
  let audioHtml = "";
  lcfg.parts.forEach((p, i) => {
    const pages = p.pages || [];
    const pagesHtml = pages.length
      ? pages.map(pageNum => `<img src="/api/mocks/${encodeURIComponent(mockId)}/page?page=${pageNum}">`).join("")
      : `<div class="missing-sheet">No question sheet pages configured for this part yet — add a "pages" array to this part in manifest.json.</div>`;
    audioHtml += `
      <div class="listening-part">
        <div class="audio-bar">
          <strong>Part ${i + 1}</strong>
          <audio controls src="/api/mocks/${encodeURIComponent(mockId)}/tests/${encodeURIComponent(testName)}/audio?file=${encodeURIComponent(p.file)}"></audio>
        </div>
        <div class="question-sheet">${pagesHtml}</div>
      </div>`;
    for (let q = p.questions[0]; q <= p.questions[1]; q++) allQuestions.push(q);
  });

  app.innerHTML = `
    <div class="timer-bar" id="timerBar">Listening — play each part, then answer</div>
    <div class="exam-shell">
      <div class="exam-material">${audioHtml}</div>
      <div class="exam-answers">
        <h3>Answers</h3>
        ${allQuestions.map(q => `
          <div class="q-row">
            <label>${q}.</label>
            <input type="text" id="lans-${q}" autocomplete="off">
          </div>`).join("")}
        <button class="submit-btn" onclick="beginTransferTime(${attempt.attempt_id}, '${mockId}', '${testName}')">Finished listening — start 10 min check time</button>
      </div>
    </div>
  `;

  window._listeningTransferSeconds = transferSeconds;
}

function beginTransferTime(attemptId, mockId, testName) {
  const totalSeconds = window._listeningTransferSeconds;
  document.querySelector(".submit-btn").outerHTML =
    `<button class="submit-btn" onclick="submitListening(${attemptId}, '${mockId}', '${testName}', false)">Submit Listening</button>`;
  startTimer(totalSeconds, remaining => {
    document.querySelector("#timerBar").innerHTML =
      `Transfer time — <span>${fmtTime(remaining)}</span> remaining`;
    if (remaining <= 60) document.querySelector("#timerBar").classList.add("warning");
  }, () => submitListening(attemptId, mockId, testName, true));
}

async function submitListening(attemptId, mockId, testName, autoSubmitted) {
  clearTimer();
  const answers = collectAnswers("lans");
  const result = await api(`/api/attempts/${attemptId}/submit`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mock_id: mockId, test_name: testName, section: "listening", answers, auto_submitted: autoSubmitted })
  });
  renderResults("Listening", result, autoSubmitted, mockId);
}

// ---------------- WRITING ----------------

async function startWriting(mockId, testName) {
  const cfg = await api(`/api/mocks/${encodeURIComponent(mockId)}/tests/${encodeURIComponent(testName)}`);
  const wcfg = cfg.writing;
  startWritingTask(mockId, testName, "task1", wcfg.task1,
    () => startWritingTask(mockId, testName, "task2", wcfg.task2, () => renderMockTests(mockId)));
}

async function startWritingTask(mockId, testName, taskKey, taskCfg, onDone) {
  const totalSeconds = taskCfg.duration_minutes * 60;
  const attempt = await api("/api/attempts/start", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mock_id: mockId, test_name: testName, section: "writing", time_allowed_seconds: totalSeconds })
  });

  const imgSrc = `/api/mocks/${encodeURIComponent(mockId)}/page?page=${taskCfg.page}`;

  app.innerHTML = `
    <div class="timer-bar" id="timerBar">${taskKey.toUpperCase()} — <span id="timerLabel"></span> remaining</div>
    <div class="exam-shell">
      <div class="exam-material"><img src="${imgSrc}"></div>
      <div class="exam-answers">
        <textarea class="essay" id="essayBox" placeholder="Write your response here..."></textarea>
        <div class="word-count" id="wc">0 words</div>
        <button class="submit-btn" onclick="submitWriting(${attempt.attempt_id}, '${mockId}', '${testName}', '${taskKey}', false)">Submit ${taskKey}</button>
      </div>
    </div>
  `;

  document.getElementById("essayBox").addEventListener("input", e => {
    const words = e.target.value.trim().split(/\s+/).filter(Boolean).length;
    document.getElementById("wc").textContent = `${words} words`;
  });

  startTimer(totalSeconds, remaining => {
    document.getElementById("timerLabel").textContent = fmtTime(remaining);
    if (remaining <= 120) document.getElementById("timerBar").classList.add("warning");
  }, () => submitWriting(attempt.attempt_id, mockId, testName, taskKey, true));

  window._writingOnDone = onDone;
}

async function submitWriting(attemptId, mockId, testName, taskKey, autoSubmitted) {
  clearTimer();
  const essay = document.getElementById("essayBox").value;
  await api(`/api/attempts/${attemptId}/submit`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mock_id: mockId, test_name: testName, section: "writing", answers: { essay }, auto_submitted: autoSubmitted })
  });

  app.innerHTML = `<div class="results-box"><p>Getting AI feedback on your ${taskKey}...</p></div>`;
  const feedback = await api("/api/writing/feedback", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_type: taskKey, prompt_description: `${taskKey} for ${testName}`, essay_text: essay })
  });

  app.innerHTML = `
    <div class="results-box">
      <h2>${taskKey.toUpperCase()} submitted</h2>
      ${feedback.error
        ? `<p><em>${feedback.error}</em></p>`
        : `
          <p class="score">Overall Band: ${feedback.overall_band}</p>
          <p>Task Achievement: ${feedback.task_achievement} · Coherence & Cohesion: ${feedback.coherence_cohesion} ·
             Lexical Resource: ${feedback.lexical_resource} · Grammar: ${feedback.grammar_accuracy}</p>
          <p>${feedback.feedback}</p>
        `}
      <button class="submit-btn" onclick="(${window._writingOnDone ? "window._writingOnDone" : "renderHome"})()">Continue</button>
    </div>
  `;
}

// ---------------- RESULTS ----------------

function renderResults(sectionLabel, result, autoSubmitted, mockId) {
  const rows = Object.entries(result.results).map(([q, r]) => `
    <div class="q-result ${r.is_correct ? "correct" : "incorrect"}">
      <span>${q}.</span>
      <span>Your answer: ${r.given || "—"}</span>
      <span>Correct: ${Array.isArray(r.correct_answer) ? r.correct_answer.join(" / ") : r.correct_answer}</span>
    </div>`).join("");

  app.innerHTML = `
    <div class="results-box">
      <h2>${sectionLabel} Results ${autoSubmitted ? "(auto-submitted — time expired)" : ""}</h2>
      <p class="score">${result.correct_count} / ${result.total} correct — Band ${result.band_estimate}</p>
      <p>Time taken: ${fmtTime(result.time_taken_seconds)}</p>
      ${rows}
      <button class="submit-btn" onclick="renderMockTests('${mockId}')">Back to tests</button>
    </div>
  `;
}

// ---------------- DASHBOARD ----------------

async function renderDashboard() {
  clearTimer();
  const history = await api("/api/history");
  app.innerHTML = `
    <h2>Progress History</h2>
    ${history.length === 0 ? "<p>No attempts yet.</p>" : `
      <table class="history">
        <tr><th>Date</th><th>Mock / Test</th><th>Section</th><th>Score</th><th>Band</th><th>Time</th></tr>
        ${history.map(h => `
          <tr>
            <td>${new Date(h.submitted_at * 1000).toLocaleString()}</td>
            <td>${h.test_id.replace("::", " — ")}</td>
            <td>${h.section}</td>
            <td>${h.correct_count !== null ? `${h.correct_count}/${h.total}` : "—"}</td>
            <td>${h.band_estimate ?? "—"}</td>
            <td>${fmtTime(h.time_taken_seconds)}</td>
          </tr>`).join("")}
      </table>
    `}
  `;
}

renderHome();
