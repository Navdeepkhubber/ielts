/* Structured content renderer.
 * Loaded after app.js so the existing exam flow remains unchanged. The
 * backend's schema_version=2 content is flattened only at the UI boundary:
 * prose stays prose, while each detected question gets its own card.
 */

function _structuredQuestionText(section) {
  const prose = (section.blocks || []).map(b => b.text).filter(Boolean);
  const questions = (section.questions || []).map(q => `__IELTS_Q__${q.question}__\n${q.text}`);
  return prose.concat(questions).join("\n\n");
}

const _legacyFetchContent = fetchContent;
async function fetchContent(mockId, testName) {
  const content = await _legacyFetchContent(mockId, testName);
  if (!content || content.schema_version !== 2) return content;

  // Keep the old API shape so startReading/startListening need no rewrite.
  for (const section of [
    ...(content.reading?.passages || []),
    ...(content.listening?.parts || []),
  ]) {
    section.text = _structuredQuestionText(section);
  }
  return content;
}

function _structuredInlineGaps(raw, prefix, qFrom, qTo) {
  return esc(raw).replace(/\b(\d{1,2})\s*(?:[.…·]{3,}|_{3,})/g, (m, num) => {
    const q = Number(num);
    if (q < qFrom || q > qTo) return m;
    return `<span class="inline-q"><span class="inline-qnum">${q}</span>` +
      `<input class="inline-input" data-inline-q="${q}" data-prefix="${prefix}" ` +
      `autocomplete="off" spellcheck="false" aria-label="Answer for question ${q}"></span>`;
  });
}

function textWithInlineInputs(text, prefix, qFrom, qTo) {
  const chunks = text.split(/\n{2,}/).filter(b => b.trim());
  return chunks.map(block => {
    const marker = block.match(/^__IELTS_Q__([0-9]{1,2})__\n([\s\S]*)$/);
    if (marker) {
      const q = Number(marker[1]);
      const body = marker[2].trim();
      return `<div class="question-box" id="question-box-${prefix}-${q}">` +
        `<div class="question-box-number">${q}</div>` +
        `<div class="question-box-body">${_structuredInlineGaps(body, prefix, qFrom, qTo)}</div>` +
        `</div>`;
    }

    const kind = classifyBlock(block.trim());
    const safe = _structuredInlineGaps(block.trim(), prefix, qFrom, qTo);
    if (kind === "letter-mark") return `<div class="para-letter">${esc(block.trim())}</div>`;
    if (kind === "q-range") return `<div class="q-range-head">${esc(block.trim())}</div>`;
    if (kind === "instruction") return `<div class="q-instruction">${safe}</div>`;
    return `<p>${safe}</p>`;
  }).join("");
}
