"""Author Cambridge 21 Test 2 into typed schema blocks.

Listening blocks are transcribed from PDF pages 33-38. Reading prose/question
records are retained as structured records, while the corrupted flat OCR text is
removed. No OCR reading-order text is copied into the output.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOCK = os.path.join(ROOT, "tests", "Cambridge 21")
CONTENT = os.path.join(MOCK, "content", "Test 2.json")
ANSWERS = os.path.join(MOCK, "answers", "Test 2")


def ins(rng, text, word_limit=None):
    value = {"range": rng, "text": text}
    if word_limit:
        value["word_limit"] = word_limit
    return value


def opts(values):
    if not values:
        return []
    return [{"id": key, "text": text} for key, text in values.items()]


def q(number, text, kind="short_answer", options=None):
    value = {"question": number, "text": text, "kind": kind}
    if options:
        value["options"] = options
    return value


def block(block_id, block_type, page, instructions, **extra):
    return {"id": block_id, "type": block_type, "page": page, "instructions": instructions, **extra}


def listening_blocks():
    abc = {"A": "", "B": "", "C": "", "D": "", "E": ""}
    p1_table = block(
        "t2-listening-p1-q1-10", "table-completion", 33,
        ins("Questions 1-10", "Complete the table below.", "ONE WORD AND/OR A NUMBER for each answer"),
        table={
            "title": "One-day classes at Steynford College",
            "headers": ["Class", "Date", "Cost", "Other information"],
            "rows": [
                ["Vietnamese food", "", "£59", "It provides information on the use of herbs. There are no places at {{1}}."],
                ["Bread making", "20 March", "{{2}}", "There is also an extra charge for ingredients. Participants make white bread, sourdough and {{3}}."],
                ["Face massage", "23 February", "£35", "The teacher trained in {{4}}. Bring a {{5}}."],
                ["Candle making", "{{6}}", "£52", "Only {{7}} ingredients are used. The candles can be used as presents."],
                ["Silk painting", "18 May", "", "Bring an apron or old {{8}}."],
                ["DIY for beginners", "24 February", "£125", "Learn how to use a drill, saw and {{9}}; put up a shelf; {{10}}."],
            ],
        },
        blanks={str(n): {"question": n} for n in range(1, 11)},
    )
    p2 = [
        block("t2-listening-p2-q11-12", "multiple-choice", 34, ins("Questions 11 and 12", "Choose TWO letters, A-E."), choose=2, items=[{"questions": [11, 12], "prompt": "Which TWO pieces of advice are given about the Marsden Coastal Walk?", "options": opts({"A": "Stop for lunch in an ancient town.", "B": "Don't miss the ruins of a certain building.", "C": "Catch a boat to the start of this walk.", "D": "Be careful of the steep and rocky paths.", "E": "Don't worry about getting lost."})}]),
        block("t2-listening-p2-q13-14", "multiple-choice", 34, ins("Questions 13 and 14", "Choose TWO letters, A-E."), choose=2, items=[{"questions": [13, 14], "prompt": "Which TWO things are said about the Melby Heritage Walk?", "options": opts({"A": "This walk is mostly downhill.", "B": "The paths can get busy during the day.", "C": "This is a circular walk.", "D": "A tower stands on the site of an older structure.", "E": "There are far-reaching views the whole way."})}]),
        block("t2-listening-p2-q15-20", "matching", 35, ins("Questions 15-20", "Label the map below. Write the correct letter, A-I, next to Questions 15-20."), options=[{"id": letter, "text": "Map location"} for letter in "ABCDEFGHI"], items=[{"question": n, "text": label} for n, label in zip(range(15, 21), ["Exhibition", "Baths", "Tools", "Vehicles", "Ponies", "Education centre"])], allow_repeat=False),
    ]
    p3 = [
        block("t2-listening-p3-q21-22", "multiple-choice", 36, ins("Questions 21 and 22", "Choose TWO letters, A-E."), choose=2, items=[{"questions": [21, 22], "prompt": "Which TWO facts in the sessions on food safety were new information for Nadia and Fergus?", "options": opts({"A": "the amount of plastic in the ocean", "B": "the number of diseases caused by contaminated food", "C": "the amount of food that is wasted", "D": "the number of people who are obese", "E": "the result of treating animals with antibiotics"})}]),
        block("t2-listening-p3-q23-24", "multiple-choice", 36, ins("Questions 23 and 24", "Choose TWO letters, A-E."), choose=2, items=[{"questions": [23, 24], "prompt": "Which TWO features of a project aiming to prevent food fraud impressed Fergus?", "options": opts({"A": "the new technology it used", "B": "the publicity it received", "C": "the use of multiple tests on food items", "D": "the variety of dietary requirements included", "E": "the way information was made widely accessible"})}]),
        block("t2-listening-p3-q25-26", "multiple-choice", 36, ins("Questions 25 and 26", "Choose TWO letters, A-E."), choose=2, items=[{"questions": [25, 26], "prompt": "Which TWO topics do both students recommend should be included in the course?", "options": opts({"A": "sustainable fishing", "B": "targeted nutrition", "C": "global differences in consumption", "D": "sustainable agriculture", "E": "digital technology and food"})}]),
        block("t2-listening-p3-q27-30", "multiple-choice", 37, ins("Questions 27-30", "Complete the flow-chart below. Choose FOUR answers from the box."), choose=4, heading="Student project: developing a new food product", items=[{"question": n, "prompt": label, "options": opts({"A": "This was challenging but enjoyable.", "B": "This led to some disagreement.", "C": "This was easy to decide on.", "D": "This was helped by the guidelines provided.", "E": "This seemed like an unnecessary stage.", "F": "This involved selecting a new ingredient."})} for n, label in zip(range(27, 31), ["Initial aim", "Literature review", "Product development", "Product production"])])
    ]
    p4 = block("t2-listening-p4-q31-40", "note-completion", 38, ins("Questions 31-40", "Complete the notes below.", "ONE WORD ONLY for each answer"), title="Challenges facing the cruise ship industry", content=[
        {"kind": "heading", "text": "Problems with overtourism"},
        {"kind": "bullet", "text": "{{31}} is one of the worst problems."},
        {"kind": "bullet", "text": "A tourist {{32}} is being introduced in some cities to reduce numbers, e.g. Barcelona."},
        {"kind": "bullet", "text": "Bruges: many shops were only stocking {{33}} and souvenirs."},
        {"kind": "bullet", "text": "Dubrovnik limits the number of tourists by managing the {{34}} of cruise ship arrivals."},
        {"kind": "heading", "text": "Problems of perception"},
        {"kind": "bullet", "text": "There is an assumption about the {{35}} of cruises."},
        {"kind": "bullet", "text": "People think there may be too many {{36}}."},
        {"kind": "heading", "text": "Solutions"},
        {"kind": "bullet", "text": "Activities include boxing, {{37}} and well-being programmes."},
        {"kind": "bullet", "text": "Food includes {{38}} options."},
        {"kind": "bullet", "text": "Providing reliable {{39}}."},
        {"kind": "bullet", "text": "Improving marketing with high quality {{40}}."},
    ], blanks={str(n): {"question": n} for n in range(31, 41)})
    return [[p1_table], p2, p3, [p4]]


def generic_reading_blocks(section, index, pages, question_range):
    blocks = [{"id": f"t2-reading-p{index + 1}-passage", "type": "passage", "page_range": pages, "paragraphs": [{"label": None, "text": item.get("text", "")} for item in section.get("paragraphs", []) if item.get("text")]}]
    questions = section.get("questions", [])
    groups = {
        0: [(1, 5, "table-completion", "Complete the table below. Choose ONE WORD ONLY from the passage for each answer."), (6, 13, "true-false-not-given", "Do the following statements agree with the information given in Reading Passage 1?" )],
        1: [(14, 19, "matching", "Which paragraph contains the following information?"), (20, 21, "multiple-choice", "Choose TWO letters, A-E."), (22, 26, "summary-completion", "Complete the summary below. Choose ONE WORD ONLY from the passage for each answer.")],
        2: [(27, 29, "multiple-choice", "Choose the correct letter, A, B, C or D."), (30, 35, "summary-completion", "Complete the summary using the list of words, A-I, below."), (36, 39, "yes-no-not-given", "Do the following statements agree with the claims of the writer in Reading Passage 3?"), (40, 40, "multiple-choice", "What would be a suitable subtitle for Reading Passage 3?")],
    }[index]
    for group_index, (start, end, kind, instruction) in enumerate(groups):
        selected = [item for item in questions if start <= int(item.get("question", 0)) <= end]
        items = [{"question": item.get("question"), "text": item.get("text", ""), "statement": item.get("text", ""), "prompt": item.get("text", ""), "options": opts(item.get("options"))} for item in selected]
        block = {"id": f"t2-reading-p{index + 1}-q{start}-{end}", "type": kind, "page": pages[min(group_index + 1, len(pages) - 1)] if pages else None, "instructions": {"range": f"Questions {start}-{end}", "text": instruction}, "items": items}
        if kind == "table-completion":
            block["table"] = {"title": "Research into sleep and dreaming", "headers": ["Research findings", "Comment"], "rows": [[item.get("text", "")] for item in selected]}
            block["blanks"] = {str(n): {"question": n} for n in range(start, end + 1)}
        if kind == "summary-completion":
            block["title"] = "Summary completion"
            block["paragraphs"] = [item.get("text", "") for item in selected]
        blocks.append(block)
    return blocks


def main():
    with open(CONTENT, encoding="utf-8") as handle:
        old = json.load(handle)
    content = {"schema_version": 2, "mock_name": "Mock 21", "test_name": "Test 2", "listening": {"parts": []}, "reading": {"passages": []}, "writing": {}, "authoring": "Test 2 typed blocks authored from PDF pages; corrupted flat OCR text omitted"}
    manifest = json.load(open(os.path.join(MOCK, "manifest.json"), encoding="utf-8"))["tests"]["Test 2"]
    listening_blocks_by_part = listening_blocks()
    for index, cfg in enumerate(manifest["listening"]["parts"]):
        content["listening"]["parts"].append({"part_number": cfg["part_number"], "questions_range": cfg["questions"], "audio_files": cfg["files"], "page": cfg["pages"][0], "blocks": listening_blocks_by_part[index]})
    for index, cfg in enumerate(manifest["reading"]["passages"]):
        section = old["reading"]["passages"][index]
        content["reading"]["passages"].append({"passage_number": index + 1, "page_range": cfg["pages"], "questions_range": cfg["questions"], "blocks": generic_reading_blocks(section, index, cfg["pages"], cfg["questions"])})
    for key, value in manifest.get("writing", {}).items():
        content["writing"][key] = value
    with open(os.path.join(ANSWERS, "reading.json"), encoding="utf-8") as handle: reading_answers = json.load(handle)
    with open(os.path.join(ANSWERS, "listening.json"), encoding="utf-8") as handle: listening_answers = json.load(handle)
    content["answer_key"] = {"listening": listening_answers, "reading": reading_answers}
    with open(CONTENT, "w", encoding="utf-8") as handle:
        json.dump(content, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


if __name__ == "__main__":
    main()
