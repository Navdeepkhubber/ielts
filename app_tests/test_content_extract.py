from lib.content_extract import build_content_for_test


def test_reading_questions_are_separate_from_passage_numbers():
    pages = [
        """
        Test 1
        READING PASSAGE 1
        The year 1998 marked an important change in the industry.
        In 2004 the researchers published their findings.

        Questions 1-3
        Complete the sentences below.
        1. The first study was conducted in ______.
        2. Researchers worked in ______ for three years.
        3. The final report was published in ______.
        """
    ]
    cfg = {
        "reading": {"passages": [{"pages": [1], "questions": [1, 3]}]}
    }

    result = build_content_for_test(pages, cfg)
    passage = result["reading"]["passages"][0]

    assert result["schema_version"] == 2
    assert [q["question"] for q in passage["questions"]] == [1, 2, 3]
    assert "1998" in passage["blocks"][0]["text"]
    assert "2004" in passage["blocks"][0]["text"]
    assert "The first study" not in passage["blocks"][0]["text"]


def test_listening_questions_keep_individual_blocks():
    pages = [
        """
        Test 1
        PART 1
        Questions 1-3
        Complete the form below.
        Name: ______
        1. Address: ______
        2. Date of visit: ______
        3. Number of people: ______
        """
    ]
    cfg = {
        "listening": {
            "parts": [{"pages": [1], "questions": [1, 3]}]
        }
    }

    result = build_content_for_test(pages, cfg)
    part = result["listening"]["parts"][0]

    assert [q["question"] for q in part["questions"]] == [1, 2, 3]
    assert all("text" in q for q in part["questions"])
