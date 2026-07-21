import config
import state_manager


def _use_temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test_state.db")
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")


def _client():
    import dashboard
    dashboard.app.config["TESTING"] = True
    return dashboard.app.test_client()


# --- state_manager read helpers ---

def test_list_runs_newest_first(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    first = state_manager.create_run()
    second = state_manager.create_run()
    state_manager.update_run(second, "completed", "FINISHED", {}, 0)

    runs = state_manager.list_runs()

    assert [r["run_id"] for r in runs] == [second, first]
    assert runs[0]["status"] == "completed"
    assert {"run_id", "created_at", "status", "current_step", "retry_count"} <= runs[0].keys()


def test_list_steps_in_order(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    run_id = state_manager.create_run()
    state_manager.log_step(run_id, "FETCH", "success", "ok")
    state_manager.log_step(run_id, "FILTER", "failed", "boom")

    steps = state_manager.list_steps(run_id)

    assert [s["step_name"] for s in steps] == ["FETCH", "FILTER"]
    assert steps[1]["status"] == "failed"


def test_weekly_seen_counts(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    state_manager.mark_seen([
        {"id": "a", "company": "X", "title": "T", "url": "u"},
        {"id": "b", "company": "Y", "title": "T", "url": "u"},
    ])

    counts = state_manager.weekly_seen_counts()

    assert len(counts) == 1
    assert counts[0]["count"] == 2
    assert "week" in counts[0]


# --- dashboard routes ---

def test_index_shows_stats_and_statuses(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    run_id = state_manager.create_run()
    state_manager.update_run(run_id, "completed", "FINISHED", {}, 0)
    state_manager.mark_seen([{"id": "a", "company": "X", "title": "T", "url": "u"}])

    resp = _client().get("/")

    assert resp.status_code == 200
    page = resp.get_data(as_text=True)
    assert "completed" in page
    assert "Run Now" in page


def test_run_detail_shows_steps_and_unknown_404s(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    run_id = state_manager.create_run()
    state_manager.log_step(run_id, "FETCH", "success", "fetched 500 postings")

    client = _client()
    ok = client.get(f"/runs/{run_id}")
    missing = client.get("/runs/does-not-exist")

    assert ok.status_code == 200
    assert "FETCH" in ok.get_data(as_text=True)
    assert missing.status_code == 404


def test_report_route_renders_digest_and_blocks_traversal(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "2026-07-20-internship-digest.md").write_text(
        "# Digest\n\n- **Acme Robotics**", encoding="utf-8")
    (tmp_path / "secret.md").write_text("password", encoding="utf-8")

    client = _client()
    ok = client.get("/reports/2026-07-20-internship-digest.md")
    traversal = client.get("/reports/..%2Fsecret.md")

    assert ok.status_code == 200
    assert "Acme Robotics" in ok.get_data(as_text=True)
    assert traversal.status_code == 404


def test_run_now_triggers_once_and_respects_active_guard(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    import dashboard

    calls = []
    monkeypatch.setattr(dashboard, "_trigger_run", lambda: calls.append(1))

    client = _client()
    resp = client.post("/run")
    assert resp.status_code == 302
    assert calls == [1], "run should be triggered exactly once"

    # With a live run in flight, the button must do nothing.
    active = state_manager.create_run()
    state_manager.update_run(active, "running", "FETCH", {}, 0)
    resp = client.post("/run")
    assert resp.status_code == 302
    assert calls == [1], "no trigger while a run is active"
