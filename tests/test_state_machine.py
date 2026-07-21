import asyncio
import sqlite3

import agent
import config
import state_manager


def _use_temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test_state.db")


def test_terminally_failed_run_is_not_picked_up_again(tmp_path, monkeypatch):
    """A run that exhausted its retries must stay halted, not be resumed forever."""
    _use_temp_db(tmp_path, monkeypatch)

    run_id = state_manager.create_run()
    state_manager.update_run(run_id, "failed", "ANALYZE", {}, 3, "Max retries exceeded")

    assert state_manager.get_latest_incomplete_run() is None


def test_interrupted_run_is_still_picked_up(tmp_path, monkeypatch):
    """Crash recovery must keep working: running/failed_retry runs are resumable."""
    _use_temp_db(tmp_path, monkeypatch)

    run_id = state_manager.create_run()
    state_manager.update_run(run_id, "failed_retry", "ANALYZE", {}, 1, "boom")

    assert state_manager.get_latest_incomplete_run() == run_id


def test_new_run_starts_after_terminal_failure(tmp_path, monkeypatch):
    """After a run halts for good, the next cycle starts a fresh run instead of
    re-executing the dead one."""
    _use_temp_db(tmp_path, monkeypatch)
    # Force the ANALYZE step to fail locally (no API key, no network).
    monkeypatch.setattr(config, "DEFAULT_MODEL_PROVIDER", "gemini")
    monkeypatch.setattr(config, "GEMINI_API_KEY", None)

    dead_id = state_manager.create_run()
    state_manager.update_run(dead_id, "failed", "ANALYZE", {}, 3, "Max retries exceeded")

    asyncio.run(agent.run_agent_loop())

    conn = sqlite3.connect(config.DB_PATH)
    runs = {row[0]: (row[1], row[2]) for row in conn.execute(
        "SELECT run_id, status, retry_count FROM agent_runs")}
    conn.close()

    assert len(runs) == 2, "a fresh run should have been created"
    assert runs[dead_id] == ("failed", 3), "the dead run must not be touched"
