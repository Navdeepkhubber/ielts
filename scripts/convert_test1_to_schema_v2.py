"""Convert the manually transcribed Cambridge 21 Test 1 content to schema v2.

The source JSON already contains human-corrected prompts and passage prose. This
script only reshapes that material into typed render blocks; it performs no OCR.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOCK = os.path.join(ROOT, "tests", "Cambridge 21")
CONTENT = os.path.join(MOCK, "content", "Test 1.json")
ANSWERS = os.path.join(MOCK, "answers", "Test 1")


def options(value):
    if isinstance(value, dict):
        return [{"id": str(key), "text": text} for key, text in value.items()]
    if isinstance(value, list):
        return [{"id": item, "text": item} for item in value]
    return []


def instructions(group):
    text = group.get("text", "")
    bits = text.split(" · ", 1)
    result = {"range": bits[0], "text": bits[-1]}
    if "ONE WORD ONLY" in text:
        result["word_limit"] = "ONE WORD ONLY for each answer"
    elif "ONE WORD AND/OR A NUMBER" in text:
        result["word_limit"] = "ONE WORD AND/OR A NUMBER for each answer"
    return result


def question_block(section, group, questions, index):
    kind = group.get("kind", "short_answer")
    page = group.get("page")
    qnums = group.get("questions", [])
    selected = [item for item in questions if item.get("question") in qnums]
    block_id = f"t1-{section}-{index + 1}-q{qnums[0]}-{qnums[-1]}"

    if kind == "short_answer" and section == "listening" and qnums == list(range(1, 7)):
        table = {
            "title": "Oyster Bay Sailing Club Courses",
            "headers": ["Name of course", "What you learn", "Cost", "Other information"],
            "rows": [
                ["Taster day", "introduction to sailing", "£120 if booking one place", "small groups (max {{1}} people)"],
                ["Level 1", "basic theory e.g. understanding the {{2}} and tides\nbasic sailing skills including {{3}}", "£200\n{{4}} available for club members\nall inclusive (plus a useful {{5}})", "a {{6}} at the end of the course for all participants"],
            ],
        }
        return {"id": block_id, "type": "table-completion", "page": page, "instructions": instructions(group), "table": table, "blanks": {str(n): {"question": n} for n in qnums}}

    if kind == "short_answer" and section == "listening" and qnums == list(range(31, 41)):
        content = [{"kind": "text", "text": "Three resources which are essential for industrial civilisation"},
                   {"kind": "bullet", "text": "fossil fuels"}, {"kind": "bullet", "text": "rubber"},
                   {"kind": "heading", "text": "Natural rubber"},
                   {"kind": "text", "text": "This mainly comes from the Para rubber tree, now cultivated in South-East Asia. The supply is limited because"}]
        content.extend({"kind": "bullet", "text": item["text"].replace("______", "{{" + str(item["question"]) + "}}")}
                       for item in selected)
        return {"id": block_id, "type": "note-completion", "page": page, "instructions": instructions(group), "title": "Sources of rubber", "content": content, "blanks": {str(n): {"question": n} for n in qnums}}

    if kind == "note_completion" and section == "reading" and qnums == list(range(1, 8)):
        content = [
            {"kind": "heading", "text": "Family and early life"},
            {"kind": "bullet", "text": "their grandfather's wealth came from {{1}} and transportation businesses"},
            {"kind": "bullet", "text": "their upbringing gave them a sense of social responsibility"},
            {"kind": "bullet", "text": "their {{2}} was designed to give them an interest in activities such as collecting art"},
            {"kind": "bullet", "text": "their governess took them on trips to art galleries"},
            {"kind": "bullet", "text": "they took lengthy {{3}} about the things they saw in art galleries"},
            {"kind": "heading", "text": "The sisters as art collectors"},
            {"kind": "bullet", "text": "their {{4}} showed they liked Old Master paintings, but they were expensive to buy"},
            {"kind": "bullet", "text": "their early purchases were safe, popular paintings"},
            {"kind": "bullet", "text": "the first Impressionist paintings they bought showed places in {{5}}"},
            {"kind": "heading", "text": "Impact of First World War"},
            {"kind": "bullet", "text": "they helped bring artists from Belgium to Wales"},
            {"kind": "bullet", "text": "they worked in a {{6}} for soldiers in France"},
            {"kind": "heading", "text": "Opinions about the sisters as art collectors"},
            {"kind": "bullet", "text": "they were not considered typical collectors - they lived in isolation in the countryside and did not have any {{7}} who were artists"},
        ]
        return {"id": block_id, "type": "note-completion", "page": page, "instructions": instructions(group), "title": "Gwendoline and Margaret Davies", "content": content, "blanks": {str(n): {"question": n} for n in qnums}}

    if kind in {"multiple_choice", "multiple_select"}:
        items = []
        for item in selected:
            entry = {"question": item["question"], "prompt": item["text"], "options": options(item.get("options"))}
            items.append(entry)
        block = {"id": block_id, "type": "multiple-choice", "page": page, "instructions": instructions(group), "choose": 2 if kind == "multiple_select" else 1, "items": items}
        if section == "listening" and qnums == list(range(11, 17)):
            block["heading"] = "Working as a makeup trainee"
        return block

    if kind in {"matching", "matching_headings", "matching_people"}:
        return {"id": block_id, "type": "matching", "page": page, "instructions": instructions(group), "options": options(selected[0].get("options") if selected else group.get("options")), "allow_repeat": kind == "matching_people", "items": [{"question": item["question"], "text": item["text"]} for item in selected]}

    if kind in {"true_false_not_given", "yes_no_not_given"}:
        block_type = "true-false-not-given" if kind == "true_false_not_given" else "yes-no-not-given"
        return {"id": block_id, "type": block_type, "page": page, "instructions": instructions(group), "items": [{"question": item["question"], "statement": item["text"]} for item in selected]}

    if kind == "summary_completion":
        return {"id": block_id, "type": "summary-completion", "page": page, "instructions": instructions(group), "title": "Sugar cultivation and production" if qnums[0] == 31 else "Flotation Tanks", "paragraphs": [item["text"].replace("______", "{{" + str(item["question"]) + "}}") for item in selected], "word_bank": options(selected[0].get("options") if selected else group.get("options"))}

    return {"id": block_id, "type": "note-completion", "page": page, "instructions": instructions(group), "content": [{"kind": "bullet", "text": item["text"].replace("______", "{{" + str(item["question"]) + "}}")} for item in selected], "blanks": {str(n): {"question": n} for n in qnums}}


def convert_section(section, section_name, index):
    document = section.get("document", [])
    groups = [node for node in document if node.get("type") == "question_group"]
    questions = section.get("questions", [])
    if section_name == "listening":
        page = (document[0].get("page") if document else None)
        if index == 0:
            groups = [
                {"page": page, "text": "Questions 1-6 · Complete the table below. Write ONE WORD AND/OR A NUMBER for each answer.", "questions": list(range(1, 7)), "kind": "short_answer"},
                {"page": page, "text": "Questions 7-10 · Complete the notes below. Write ONE WORD ONLY for each answer.", "questions": list(range(7, 11)), "kind": "short_answer"},
            ]
        elif index == 1:
            groups = [
                {"page": page, "text": "Questions 11-16 · Choose the correct letter, A, B or C.", "questions": list(range(11, 17)), "kind": "multiple_choice"},
                {"page": page + 1 if page else page, "text": "Questions 17-20 · What ability is required for each duty?", "questions": list(range(17, 21)), "kind": "matching"},
            ]
        elif index == 2:
            groups = [
                {"page": page, "text": "Questions 21 and 22 · Choose TWO letters, A-E.", "questions": [21, 22], "kind": "multiple_select"},
                {"page": page, "text": "Questions 23 and 24 · Choose TWO letters, A-E.", "questions": [23, 24], "kind": "multiple_select"},
                {"page": page + 1 if page else page, "text": "Questions 25-30 · Choose SIX answers from the box.", "questions": list(range(25, 31)), "kind": "matching"},
            ]
        elif index == 3:
            groups = [{"page": page, "text": "Questions 31-40 · Complete the notes below. Write ONE WORD ONLY for each answer.", "questions": list(range(31, 41)), "kind": "short_answer"}]
    blocks = []
    for node in document:
        if node.get("type") in {"title", "heading"}:
            blocks.append({"id": f"t1-{section_name}-{index + 1}-{node['type']}-{node['page']}", "type": node["type"], "page": node["page"], "text": node["text"]})
        elif node.get("type") == "paragraphs_from_existing":
            paragraphs = [item for item in section.get("paragraphs", []) if item.get("page") in node.get("pages", [])]
            blocks.append({"id": f"t1-{section_name}-{index + 1}-passage", "type": "passage", "page_range": node.get("pages", []), "paragraphs": [{"label": None, "text": item["text"]} for item in paragraphs]})
    for group_index, group in enumerate(groups):
        blocks.append(question_block(section_name, group, questions, group_index))
    section["blocks_v2"] = blocks
    section["blocks"] = blocks
    section["schema_version"] = 2
    return section


def main():
    with open(CONTENT, encoding="utf-8") as handle:
        content = json.load(handle)
    for index, section in enumerate(content.get("listening", {}).get("parts", [])):
        convert_section(section, "listening", index)
    for index, section in enumerate(content.get("reading", {}).get("passages", [])):
        convert_section(section, "reading", index)
    with open(os.path.join(ANSWERS, "reading.json"), encoding="utf-8") as handle:
        reading_answers = json.load(handle)
    with open(os.path.join(ANSWERS, "listening.json"), encoding="utf-8") as handle:
        listening_answers = json.load(handle)
    content["schema_version"] = 2
    content["mock_name"] = "Mock 21"
    content["test_name"] = "Test 1"
    content["answer_key"] = {"listening": listening_answers, "reading": reading_answers}
    content["authoring"] = "manual transcription reshaped into typed blocks; no OCR used"
    with open(CONTENT, "w", encoding="utf-8") as handle:
        json.dump(content, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


if __name__ == "__main__":
    main()
