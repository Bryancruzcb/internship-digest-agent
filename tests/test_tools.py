import tools

RAW = [
    {
        "id": "keep-1",
        "company_name": "Acme Robotics",
        "title": "Software Engineer Intern",
        "locations": ["San Jose, CA"],
        "url": "https://example.com/apply",
        "terms": ["Summer 2026"],
        "active": True,
        "is_visible": True,
        "date_posted": 1750000000,
    },
    {
        "id": "drop-inactive",
        "company_name": "Gone Inc",
        "title": "SWE Intern",
        "locations": [],
        "url": "https://example.com/x",
        "terms": ["Summer 2026"],
        "active": False,
        "is_visible": True,
        "date_posted": 1750000000,
    },
    {
        "id": "drop-wrong-term",
        "company_name": "Fall Corp",
        "title": "SWE Intern",
        "locations": [],
        "url": "https://example.com/y",
        "terms": ["Fall 2026"],
        "active": True,
        "is_visible": True,
        "date_posted": 1750000000,
    },
]


def test_normalize_keeps_only_active_visible_matching_term():
    result = tools.normalize_postings(RAW, ["Summer 2026"])

    assert [p["id"] for p in result] == ["keep-1"]
    p = result[0]
    assert p["company"] == "Acme Robotics"
    assert p["title"] == "Software Engineer Intern"
    assert p["url"] == "https://example.com/apply"
    assert p["locations"] == ["San Jose, CA"]


def test_normalize_accepts_multiple_terms():
    result = tools.normalize_postings(RAW, ["Summer 2026", "Fall 2026"])

    assert [p["id"] for p in result] == ["keep-1", "drop-wrong-term"], (
        "a posting matching ANY configured term must be kept")


def test_compile_report_lists_postings_and_summary():
    postings = tools.normalize_postings(RAW, ["Summer 2026"])
    report = tools.compile_report(postings, "One new robotics internship.", "2026-07-20")

    assert "2026-07-20" in report
    assert "One new robotics internship." in report
    assert "Acme Robotics" in report
    assert "https://example.com/apply" in report


def test_publish_report_writes_dated_file(tmp_path):
    path = tools.publish_report("# hello", tmp_path / "reports", "2026-07-20")

    assert path.name == "2026-07-20-internship-digest.md"
    assert path.read_text(encoding="utf-8") == "# hello"
