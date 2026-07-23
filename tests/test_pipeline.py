import sqlite3

import agent
import config
import state_manager
import tools

POSTING = {
    "id": "p1",
    "company": "Acme Robotics",
    "title": "Software Engineer Intern",
    "locations": ["San Jose, CA"],
    "url": "https://example.com/apply",
    "date_posted": 1750000000,
}


def _setup(tmp_path, monkeypatch, postings):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test_state.db")
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")
    # No LLM key: SUMMARIZE must degrade to a placeholder, not fail the run.
    monkeypatch.setattr(config, "DEFAULT_MODEL_PROVIDER", "gemini")
    monkeypatch.setattr(config, "GEMINI_API_KEY", None)
    # Keep tests off the network: no watchlist file, Handshake disabled.
    monkeypatch.setattr(config, "WATCHLIST_PATH", tmp_path / "no-watchlist.json")
    monkeypatch.setattr(config, "HANDSHAKE_IMAP_USER", None)
    monkeypatch.setattr(tools, "fetch_postings", lambda url, terms: list(postings))


def _reports(tmp_path):
    reports_dir = tmp_path / "reports"
    return sorted(reports_dir.glob("*-internship-digest.md")) if reports_dir.exists() else []


def test_full_run_publishes_dated_digest_and_marks_seen(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, [POSTING])

    agent.run_agent_loop()

    reports = _reports(tmp_path)
    assert len(reports) == 1
    content = reports[0].read_text(encoding="utf-8")
    assert "Acme Robotics" in content
    assert "Software Engineer Intern" in content

    conn = sqlite3.connect(config.DB_PATH)
    seen = [row[0] for row in conn.execute("SELECT posting_id FROM seen_postings")]
    status = conn.execute("SELECT status FROM agent_runs").fetchone()[0]
    conn.close()
    assert seen == ["p1"]
    assert status == "completed"


def test_second_run_reports_nothing_new_and_keeps_existing_digest(tmp_path, monkeypatch):
    """Postings already published must never reappear, and a same-day re-run with
    nothing new must not clobber the digest that was already written."""
    _setup(tmp_path, monkeypatch, [POSTING])

    agent.run_agent_loop()
    agent.run_agent_loop()

    reports = _reports(tmp_path)
    assert len(reports) == 1
    assert "Acme Robotics" in reports[0].read_text(encoding="utf-8")

    conn = sqlite3.connect(config.DB_PATH)
    statuses = [row[0] for row in conn.execute("SELECT status FROM agent_runs")]
    seen_count = conn.execute("SELECT COUNT(*) FROM seen_postings").fetchone()[0]
    conn.close()
    assert statuses == ["completed", "completed"]
    assert seen_count == 1


def test_same_day_second_run_with_new_postings_keeps_both_digests(tmp_path, monkeypatch):
    """A second run on the same date that finds NEW postings must not clobber
    the digest already written that day — every posting appears in exactly one
    preserved digest, or it is lost forever (it is already marked seen)."""
    _setup(tmp_path, monkeypatch, [POSTING])
    agent.run_agent_loop()

    second = dict(POSTING, id="p2", company="Beta Corp")
    monkeypatch.setattr(tools, "fetch_postings", lambda url, terms: [POSTING, second])
    agent.run_agent_loop()

    reports = _reports(tmp_path)
    assert len(reports) == 2, "second same-day run must write its own file"
    combined = "".join(r.read_text(encoding="utf-8") for r in reports)
    assert "Acme Robotics" in combined, "first digest's postings must survive"
    assert "Beta Corp" in combined


def test_failed_run_does_not_mark_postings_seen(tmp_path, monkeypatch):
    """Postings from a run that never published must stay eligible for the next
    digest — otherwise they silently vanish."""
    _setup(tmp_path, monkeypatch, [POSTING])

    def broken_publish(state):
        raise OSError("disk full")

    handlers = dict(agent.STEP_HANDLERS)
    handlers["PUBLISH"] = broken_publish
    monkeypatch.setattr(agent, "STEP_HANDLERS", handlers)

    agent.run_agent_loop()

    conn = sqlite3.connect(config.DB_PATH)
    seen_count = conn.execute("SELECT COUNT(*) FROM seen_postings").fetchone()[0]
    conn.close()
    assert seen_count == 0
